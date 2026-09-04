"""
Motorrommet - lokal chat-app med lagrede samtaler og dokumentstøtte.

Kjør med: python app.py
Krever: pip install pywebview llama-cpp-python
"""

import webview
import threading
import json
import os
import uuid
import time
import shutil
import numpy as np
from llama_cpp import Llama

MODELS = {
    "Qwen2.5-1.5B": "./models/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "Qwen2.5-7B": "./models/qwen2.5-7b-instruct-q4_k_m.gguf",
    "DeepSeek-R1-7B": "./models/DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q5_K_M.gguf",
}
SMALL_MODEL_NAME = "Qwen2.5-1.5B"  # brukes til dokument-oppsummering
EMBED_MODEL_PATH = "./models/nomic-embed-text-v1.5.Q4_K_M.gguf"

RETRIEVAL_CHUNK_WORDS = 300      # størrelse på biter brukt til søk/henting
RETRIEVAL_CHUNK_OVERLAP = 50
SUMMARY_CHUNK_WORDS = 1200       # større biter brukt til det lange sammendraget
MAX_SUMMARY_CHUNKS = 25          # tak for å unngå at kjempestore bøker tar evigheter
TOP_K_CHUNKS = 5                 # antall relevante biter som hentes per spørsmål

CHATS_DIR = "./chats"
DOCS_DIR = "./documents"
os.makedirs(CHATS_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

N_THREADS = 6
N_CTX = 8192
SAMPLING_PARAMS = {
    "temperature": 0.6,
    "repeat_penalty": 1.1,
    "frequency_penalty": 0.05,
}

loaded_models = {}
window = None


def get_model(name):
    if name not in loaded_models:
        path = MODELS[name]
        if not os.path.exists(path):
            raise FileNotFoundError(f"Fant ikke modellfil: {path}")
        loaded_models[name] = Llama(
            model_path=path, n_ctx=N_CTX, n_threads=N_THREADS,
            n_gpu_layers=0, verbose=False
        )
    return loaded_models[name]


embedder = None


def get_embedder():
    global embedder
    if embedder is None:
        if not os.path.exists(EMBED_MODEL_PATH):
            raise FileNotFoundError(
                f"Fant ikke embedding-modell: {EMBED_MODEL_PATH}. "
                "Last ned nomic-embed-text-v1.5.Q4_K_M.gguf til models/-mappen."
            )
        embedder = Llama(
            model_path=EMBED_MODEL_PATH, embedding=True,
            n_ctx=2048, n_threads=N_THREADS, verbose=False
        )
    return embedder


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


def chat_path(chat_id):
    return os.path.join(CHATS_DIR, f"{chat_id}.json")


def doc_dir(chat_id):
    d = os.path.join(DOCS_DIR, chat_id)
    os.makedirs(d, exist_ok=True)
    return d


def doc_path(chat_id, doc_id):
    return os.path.join(doc_dir(chat_id), f"{doc_id}.json")


class Api:
    # ---------------- Modeller ----------------

    def list_models(self):
        return list(MODELS.keys())

    # ---------------- Samtaler ----------------

    def list_chats(self):
        chats = []
        for fname in os.listdir(CHATS_DIR):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(CHATS_DIR, fname), encoding="utf-8") as f:
                data = json.load(f)
            chats.append({
                "id": data["id"],
                "name": data["name"],
                "model": data.get("model"),
                "updated_at": data.get("updated_at", 0),
            })
        chats.sort(key=lambda c: c["updated_at"], reverse=True)
        return chats

    def load_chat(self, chat_id):
        path = chat_path(chat_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save_chat(self, chat_id, name, model_name, messages_json, language="no"):
        messages = json.loads(messages_json)
        if not chat_id:
            chat_id = str(uuid.uuid4())
        data = {
            "id": chat_id,
            "name": name,
            "model": model_name,
            "language": language,
            "messages": messages,
            "updated_at": time.time(),
        }
        with open(chat_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return chat_id

    def rename_chat(self, chat_id, new_name):
        path = chat_path(chat_id)
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["name"] = new_name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def delete_chat(self, chat_id):
        path = chat_path(chat_id)
        if os.path.exists(path):
            os.remove(path)
        chat_doc_dir = os.path.join(DOCS_DIR, chat_id)
        if os.path.isdir(chat_doc_dir):
            shutil.rmtree(chat_doc_dir)
        return True

    # ---------------- Dokumenter ----------------

    def list_documents(self, chat_id):
        if not chat_id:
            return []
        chat_doc_dir = os.path.join(DOCS_DIR, chat_id)
        if not os.path.isdir(chat_doc_dir):
            return []
        docs = []
        for fname in os.listdir(chat_doc_dir):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(chat_doc_dir, fname), encoding="utf-8") as f:
                data = json.load(f)
            docs.append({
                "id": data["id"],
                "filename": data["filename"],
                "summary": data["summary"],
                "active": data.get("active", True),
            })
        return docs

    def add_document(self, chat_id):
        """Åpner en fil-dialog, leser filen, deler den i biter for søk (RAG),
        og lager et langt, strukturert sammendrag til visning i sidepanelet."""
        if not chat_id:
            return {"cancelled": True, "error": "Ingen samtale å knytte dokumentet til"}

        file_types = ("Tekst og Markdown (*.txt;*.md)",)
        result = window.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
        if not result:
            return {"cancelled": True}

        filepath = result[0]
        filename = os.path.basename(filepath)

        with open(filepath, encoding="utf-8", errors="ignore") as f:
            content = f.read()

        def status(text):
            window.evaluate_js(f"onDocStatus({json.dumps(text)})")

        # --- 1. Del opp og lag embeddings for søk (RAG) ---
        status(f"Deler opp {filename} for søk...")
        retrieval_chunks = chunk_text(content, RETRIEVAL_CHUNK_WORDS, RETRIEVAL_CHUNK_OVERLAP)
        embed_model = get_embedder()

        chunk_data = []
        for i, chunk in enumerate(retrieval_chunks):
            status(f"Lager søkeindeks for {filename}: bit {i + 1}/{len(retrieval_chunks)}")
            vec = embed_model.create_embedding(chunk)["data"][0]["embedding"]
            chunk_data.append({"text": chunk, "embedding": vec})

        # --- 2. Lag et langt, strukturert sammendrag (map-reduce) ---
        summary_chunks = chunk_text(content, SUMMARY_CHUNK_WORDS, 0)[:MAX_SUMMARY_CHUNKS]
        small = get_model(SMALL_MODEL_NAME)
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
        data = {
            "id": doc_id,
            "filename": filename,
            "summary": final_summary,
            "chunks": chunk_data,
            "active": True,
        }
        with open(doc_path(chat_id, doc_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        status("")
        return {"cancelled": False, "documents": self.list_documents(chat_id)}

    def toggle_document(self, chat_id, doc_id):
        path = doc_path(chat_id, doc_id)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["active"] = not data.get("active", True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data["active"]

    def delete_document(self, chat_id, doc_id):
        path = doc_path(chat_id, doc_id)
        if os.path.exists(path):
            os.remove(path)
        return True

    def _document_context_for_query(self, chat_id, query_text):
        if not chat_id:
            return None
        chat_doc_dir = os.path.join(DOCS_DIR, chat_id)
        if not os.path.isdir(chat_doc_dir):
            return None

        all_chunks = []       # (text, filename) for hver bit
        all_vectors = []
        for fname in os.listdir(chat_doc_dir):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(chat_doc_dir, fname), encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("active", True):
                continue
            for chunk in data.get("chunks", []):
                all_chunks.append((chunk["text"], data["filename"]))
                all_vectors.append(chunk["embedding"])

        if not all_chunks:
            return None

        embed_model = get_embedder()
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

    # ---------------- Chat-generering ----------------

    def send_message(self, model_name, messages_json, chat_id=None):
        thread = threading.Thread(
            target=self._generate, args=(model_name, messages_json, chat_id), daemon=True
        )
        thread.start()
        return {"started": True}

    def _generate(self, model_name, messages_json, chat_id=None):
        messages = json.loads(messages_json)

        last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        doc_context = self._document_context_for_query(chat_id, last_user_msg)
        if doc_context:
            # Slås sammen med den ORIGINALE system-meldingen istedenfor å legges til
            # som en egen system-melding nr. 2 - flere system-meldinger forvirrer
            # chat-malen til mindre modeller og gir hallusinerte "policy"-svar.
            combined_system = messages[0]["content"] + "\n\n" + doc_context
            messages = [{"role": "system", "content": combined_system}] + messages[1:]

        try:
            llm = get_model(model_name)
            max_tokens = 1500 if "DeepSeek" in model_name else 700

            stream = llm.create_chat_completion(
                messages=messages, max_tokens=max_tokens, stream=True, **SAMPLING_PARAMS
            )

            for chunk in stream:
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    window.evaluate_js(f"onChunk({json.dumps(delta)})")

            window.evaluate_js("onDone()")

        except Exception as e:
            window.evaluate_js(f"onError({json.dumps(str(e))})")


if __name__ == "__main__":
    api = Api()
    window = webview.create_window(
        "Skibeti37",
        "static/index.html",
        js_api=api,
        width=1100,
        height=750,
        min_size=(750, 550),
    )
    webview.start()