"""Shared document library. Each document is stored once (chunking +
embeddings for search, plus a long summary), and linked to one or more
conversations via chat_store's "attached_docs" field."""

import json
import os
import uuid
import numpy as np
import webview

import applog
import chat_store
import config
import model_manager
import runtime

DOCS_DIR = "./documents"
os.makedirs(DOCS_DIR, exist_ok=True)

RETRIEVAL_CHUNK_WORDS = 300
RETRIEVAL_CHUNK_OVERLAP = 50
MAX_RETRIEVAL_CHUNKS = 800   # ceiling so a pathologically large file can't stall indexing
SUMMARY_CHUNK_WORDS = 2400
MAX_SUMMARY_CHUNKS = 8       # each is one utility-model call - keep the total bounded
TOP_K_CHUNKS = 5

# Framing text prepended to the retrieved excerpts, read in-context by the
# main chat model. English instruction; the model answers in the user's
# language regardless.
RAG_PREFIX = (
    "The following are the most relevant excerpts from the user's documents, retrieved "
    "for this question. Use them to answer precisely, and reply in the language of the "
    "user's latest message even when the excerpts are in another language. If the answer "
    "is not in the excerpts, say so instead of guessing:\n\n"
)


def doc_path(doc_id):
    return os.path.join(DOCS_DIR, f"{doc_id}.json")


def _load_doc_meta(doc_id):
    """id/filename/summary for one stored document, or None if it is missing."""
    p = doc_path(doc_id)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return {"id": doc_id, "filename": data["filename"], "summary": data["summary"]}


def _all_doc_metas():
    """id/filename/summary for every document in the library."""
    metas = []
    for fname in os.listdir(DOCS_DIR):
        if not fname.endswith(".json"):
            continue
        meta = _load_doc_meta(fname[:-5])
        if meta:
            metas.append(meta)
    return metas


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
    result = []
    for doc_id, active in chat.get("attached_docs", {}).items():
        meta = _load_doc_meta(doc_id)
        if meta:
            result.append({**meta, "active": active})
    return result


def list_available_documents(chat_id):
    chat = chat_store.load_chat_raw(chat_id) or {}
    attached_ids = set(chat.get("attached_docs", {}).keys())
    return [meta for meta in _all_doc_metas() if meta["id"] not in attached_ids]


def list_all_documents_settings():
    return _all_doc_metas()


def _summarize_chunk_prompt(chunk):
    return [
        {
            "role": "system",
            "content": (
                "You summarise parts of a document. Capture concrete facts, names, "
                "numbers and the structure of the text. Be precise, not generic. "
                "Write the summary in the same language as the document."
            ),
        },
        {"role": "user", "content": f"Summarise this part:\n\n{chunk}"},
    ]


def _combine_summaries_prompt(partial_summaries):
    return [
        {
            "role": "system",
            "content": (
                "You are given several partial summaries of the same document, in order. "
                "Merge them into one thorough, structured summary with headings "
                "(markdown ##) for the different parts/themes. Keep concrete details and "
                "facts - do not generalise away important content. Aim for 400-700 words. "
                "Write the summary in the same language as the partial summaries."
            ),
        },
        {
            "role": "user",
            "content": "\n\n---\n\n".join(
                f"Part {i + 1}:\n{s}" for i, s in enumerate(partial_summaries)
            ),
        },
    ]


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
    applog.log(f"indexing document: {filename} ({len(content)} chars)")

    def status(text):
        runtime.window.evaluate_js(f"onDocStatus({json.dumps(text)})")

    # Indexing needs the embedder + the small utility model. Drop any large
    # chat model from RAM first so the three don't pile up and push a
    # low-memory machine into swap (which looks like a freeze).
    model_manager.unload_all_but_utility()

    status(f"Deler opp {filename} for søk...")
    retrieval_chunks = chunk_text(content, RETRIEVAL_CHUNK_WORDS, RETRIEVAL_CHUNK_OVERLAP)
    truncated_index = len(retrieval_chunks) > MAX_RETRIEVAL_CHUNKS
    if truncated_index:
        retrieval_chunks = retrieval_chunks[:MAX_RETRIEVAL_CHUNKS]
        applog.log(f"  document large - capped at {MAX_RETRIEVAL_CHUNKS} search chunks")
    embed_model = model_manager.get_embedder()

    applog.log(f"  embedding {len(retrieval_chunks)} chunks ...")
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

    applog.log(f"  summarizing in {len(summary_chunks)} part(s) with {utility_filename} ...")
    for i, chunk in enumerate(summary_chunks):
        status(f"Oppsummerer {filename}: del {i + 1}/{len(summary_chunks)}")
        resp = small.create_chat_completion(
            messages=_summarize_chunk_prompt(chunk), max_tokens=350, temperature=0.3
        )
        partial_summaries.append(resp["choices"][0]["message"]["content"].strip())

    status(f"Setter sammen sluttsammendrag for {filename}...")
    if len(partial_summaries) > 1:
        resp = small.create_chat_completion(
            messages=_combine_summaries_prompt(partial_summaries),
            max_tokens=1200, temperature=0.3,
        )
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

    applog.log(f"indexed: {filename} -> doc {doc_id[:8]} ({len(chunk_data)} chunks)")
    status("")
    result = {"cancelled": False, "documents": list_documents(chat_id)}
    if truncated_index:
        result["notice"] = (
            f"«{filename}» er stort - bare de første delene ble indeksert for søk."
        )
    return result


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


def _snippet(text, words=40):
    parts = text.split()
    return " ".join(parts[:words]) + ("..." if len(parts) > words else "")


def document_context_for_query(chat_id, query_text):
    """Returns (context_string_or_None, sources). `sources` is a list of
    {filename, snippet, score} for the chunks actually included, so the UI
    can show which document excerpts a reply was based on."""
    empty = (None, [])
    if not chat_id:
        return empty
    chat = chat_store.load_chat_raw(chat_id)
    if not chat:
        return empty
    attached = chat.get("attached_docs", {})
    if not attached:
        return empty

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
        return empty

    embed_model = model_manager.get_embedder()
    query_vec = embed_model.create_embedding(query_text)["data"][0]["embedding"]
    matrix = np.array(all_vectors, dtype=np.float32)
    similarities = cosine_similarity(query_vec, matrix)
    top_indices = np.argsort(similarities)[::-1][:TOP_K_CHUNKS]

    excerpts = []
    sources = []
    for idx in top_indices:
        text, filename = all_chunks[idx]
        excerpts.append(f"[From {filename}]\n{text}")
        sources.append({
            "filename": filename,
            "snippet": _snippet(text),
            "score": round(float(similarities[idx]), 3),
        })

    return RAG_PREFIX + "\n\n---\n\n".join(excerpts), sources
