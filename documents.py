"""Delt dokumentbibliotek. Hvert dokument lagres én gang (chunking +
embeddings for søk, pluss et langt sammendrag), og knyttes til én eller
flere samtaler via chat_store sitt "attached_docs"-felt."""

import json
import os
import uuid
import numpy as np
import webview

import chat_store
import config
import model_manager
import runtime

DOCS_DIR = "./documents"
os.makedirs(DOCS_DIR, exist_ok=True)

RETRIEVAL_CHUNK_WORDS = 300
RETRIEVAL_CHUNK_OVERLAP = 50
SUMMARY_CHUNK_WORDS = 1200
MAX_SUMMARY_CHUNKS = 25
TOP_K_CHUNKS = 5


def doc_path(doc_id):
    return os.path.join(DOCS_DIR, f"{doc_id}.json")


def chunk_text(text, chunk_size, overlap):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


def cosine_similarity(query_vec, matrix):
    query_vec = np.array(query_vec, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vec)
    norms[norms == 0] = 1e-10
    return np.dot(matrix, query_vec) / norms


def list_documents(chat_id):
    if not chat_id:
        return []
    chat = chat_store.load_chat_raw(chat_id)
    if not chat:
        return []
    attached = chat.get("attached_docs", {})
    result = []
    for doc_id, active in attached.items():
        p = doc_path(doc_id)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        result.append({
            "id": doc_id, "filename": data["filename"],
            "summary": data["summary"], "active": active,
        })
    return result


def list_available_documents(chat_id):
    chat = chat_store.load_chat_raw(chat_id) or {}
    attached_ids = set(chat.get("attached_docs", {}).keys())
    result = []
    for fname in os.listdir(DOCS_DIR):
        if not fname.endswith(".json"):
            continue
        doc_id = fname[:-5]
        if doc_id in attached_ids:
            continue
        with open(os.path.join(DOCS_DIR, fname), encoding="utf-8") as f:
            data = json.load(f)
        result.append({"id": doc_id, "filename": data["filename"], "summary": data["summary"]})
    return result


def list_all_documents_settings():
    result = []
    for fname in os.listdir(DOCS_DIR):
        if not fname.endswith(".json"):
            continue
        doc_id = fname[:-5]
        with open(os.path.join(DOCS_DIR, fname), encoding="utf-8") as f:
            data = json.load(f)
        result.append({"id": doc_id, "filename": data["filename"], "summary": data["summary"]})
    return result


def add_document(chat_id):
    if not chat_id:
        return {"cancelled": True, "error": "Ingen samtale å knytte dokumentet til"}

    file_types = ("Tekst og Markdown (*.txt;*.md)",)
    result = runtime.window.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
    if not result:
        return {"cancelled": True}

    filepath = result[0]
    filename = os.path.basename(filepath)
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    def status(text):
        runtime.window.evaluate_js(f"onDocStatus({json.dumps(text)})")

    status(f"Deler opp {filename} for søk...")
    retrieval_chunks = chunk_text(content, RETRIEVAL_CHUNK_WORDS, RETRIEVAL_CHUNK_OVERLAP)
    embed_model = model_manager.get_embedder()

    chunk_data = []
    for i, chunk in enumerate(retrieval_chunks):
        status(f"Lager søkeindeks for {filename}: bit {i + 1}/{len(retrieval_chunks)}")
        vec = embed_model.create_embedding(chunk)["data"][0]["embedding"]
        chunk_data.append({"text": chunk, "embedding": vec})

    summary_chunks = chunk_text(content, SUMMARY_CHUNK_WORDS, 0)[:MAX_SUMMARY_CHUNKS]
    utility_filename = config.get_utility_model_filename()
    if not utility_filename:
        return {"cancelled": True, "error": "Ingen modeller funnet i models/-mappen"}
    small = model_manager.get_model(utility_filename)
    partial_summaries = []

    for i, chunk in enumerate(summary_chunks):
        status(f"Oppsummerer {filename}: del {i + 1}/{len(summary_chunks)}")
        prompt = [
            {
                "role": "system",
                "content": (
                    "Du oppsummerer deler av et dokument på norsk. Fang opp konkrete "
                    "fakta, navn, tall og strukturen i teksten. Vær presis, ikke generisk."
                )
            },
            {"role": "user", "content": f"Oppsummer denne delen:\n\n{chunk}"}
        ]
        resp = small.create_chat_completion(messages=prompt, max_tokens=350, temperature=0.3)
        partial_summaries.append(resp["choices"][0]["message"]["content"].strip())

    status(f"Setter sammen sluttsammendrag for {filename}...")
    if len(partial_summaries) > 1:
        combine_prompt = [
            {
                "role": "system",
                "content": (
                    "Du får flere delsammendrag av samme dokument, i rekkefølge. Slå dem "
                    "sammen til ett grundig, strukturert sammendrag på norsk med overskrifter "
                    "(markdown ##) for de ulike delene/temaene. Behold konkrete detaljer og "
                    "fakta - ikke generaliser bort viktig innhold. Sikt på 400-700 ord."
                )
            },
            {
                "role": "user",
                "content": "\n\n---\n\n".join(
                    f"Del {i+1}:\n{s}" for i, s in enumerate(partial_summaries)
                )
            }
        ]
        resp = small.create_chat_completion(messages=combine_prompt, max_tokens=1200, temperature=0.3)
        final_summary = resp["choices"][0]["message"]["content"].strip()
    else:
        final_summary = partial_summaries[0] if partial_summaries else "(tomt dokument)"

    doc_id = str(uuid.uuid4())
    data = {"id": doc_id, "filename": filename, "summary": final_summary, "chunks": chunk_data}
    with open(doc_path(doc_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    chat = chat_store.load_chat_raw(chat_id) or {"id": chat_id, "attached_docs": {}}
    chat.setdefault("attached_docs", {})[doc_id] = True
    chat_store.save_chat_raw(chat_id, chat)

    status("")
    return {"cancelled": False, "documents": list_documents(chat_id)}


def attach_existing_document(chat_id, doc_id):
    chat = chat_store.load_chat_raw(chat_id)
    if not chat:
        return []
    chat.setdefault("attached_docs", {})[doc_id] = True
    chat_store.save_chat_raw(chat_id, chat)
    return list_documents(chat_id)


def detach_document(chat_id, doc_id):
    chat = chat_store.load_chat_raw(chat_id)
    if chat and "attached_docs" in chat:
        chat["attached_docs"].pop(doc_id, None)
        chat_store.save_chat_raw(chat_id, chat)
    return True


def toggle_document(chat_id, doc_id):
    chat = chat_store.load_chat_raw(chat_id)
    if not chat:
        return False
    attached = chat.setdefault("attached_docs", {})
    attached[doc_id] = not attached.get(doc_id, True)
    chat_store.save_chat_raw(chat_id, chat)
    return attached[doc_id]


def delete_document_entirely(doc_id):
    p = doc_path(doc_id)
    if os.path.exists(p):
        os.remove(p)
    for fname in os.listdir(chat_store.CHATS_DIR):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        path = os.path.join(chat_store.CHATS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                chat = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if "attached_docs" in chat and doc_id in chat["attached_docs"]:
            del chat["attached_docs"][doc_id]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(chat, f, ensure_ascii=False, indent=2)
    return True


def preview_document(doc_id):
    p = doc_path(doc_id)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    full_text = "\n\n".join(c["text"] for c in data.get("chunks", []))
    return {"filename": data["filename"], "summary": data["summary"], "full_text": full_text}


def document_context_for_query(chat_id, query_text):
    if not chat_id:
        return None
    chat = chat_store.load_chat_raw(chat_id)
    if not chat:
        return None
    attached = chat.get("attached_docs", {})
    if not attached:
        return None

    all_chunks = []
    all_vectors = []
    for doc_id, active in attached.items():
        if not active:
            continue
        p = doc_path(doc_id)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for chunk in data.get("chunks", []):
            all_chunks.append((chunk["text"], data["filename"]))
            all_vectors.append(chunk["embedding"])

    if not all_chunks:
        return None

    embed_model = model_manager.get_embedder()
    query_vec = embed_model.create_embedding(query_text)["data"][0]["embedding"]
    matrix = np.array(all_vectors, dtype=np.float32)
    similarities = cosine_similarity(query_vec, matrix)
    top_indices = np.argsort(similarities)[::-1][:TOP_K_CHUNKS]

    excerpts = []
    for idx in top_indices:
        text, filename = all_chunks[idx]
        excerpts.append(f"[Fra {filename}]\n{text}")

    return (
        "Følgende er de mest relevante utdragene fra brukerens dokumenter, hentet basert "
        "på spørsmålet. Bruk dem til å svare presist. Hvis svaret ikke finnes i utdragene, "
        "si ifra istedenfor å gjette:\n\n" + "\n\n---\n\n".join(excerpts)
    )