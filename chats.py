"""Samtale-CRUD, og selve kontekstbyggingen: slår sammen system-prompt,
aktive skills, dokumentkontekst (RAG) og en eventuelt komprimert
samtalehistorikk til meldingene som faktisk sendes til modellen."""

import time
import uuid

import chat_store
import config
import documents
import model_manager
import skills

RECENT_KEEP_MESSAGES = 10  # antall siste meldinger som alltid sendes ordrett


def list_chats():
    import os
    chats = []
    for fname in os.listdir(chat_store.CHATS_DIR):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        data = chat_store.load_chat_raw(fname[:-5])
        if not data or "id" not in data:
            continue
        chats.append({
            "id": data["id"],
            "name": data.get("name", "Ny samtale"),
            "model": data.get("model"),
            "updated_at": data.get("updated_at", 0),
        })
    chats.sort(key=lambda c: c["updated_at"], reverse=True)
    return chats


def load_chat(chat_id):
    return chat_store.load_chat_raw(chat_id)


def save_chat(chat_id, name, model_name, messages, language="no"):
    if not chat_id:
        chat_id = str(uuid.uuid4())
    existing = chat_store.load_chat_raw(chat_id) or {}
    data = {
        "id": chat_id,
        "name": name,
        "model": model_name,
        "language": language,
        "messages": messages,
        "attached_docs": existing.get("attached_docs", {}),
        "updated_at": time.time(),
    }
    chat_store.save_chat_raw(chat_id, data)
    return chat_id


def rename_chat(chat_id, new_name):
    data = chat_store.load_chat_raw(chat_id)
    if not data:
        return False
    data["name"] = new_name
    chat_store.save_chat_raw(chat_id, data)
    return True


def delete_chat(chat_id):
    import os
    path = chat_store.chat_path(chat_id)
    if os.path.exists(path):
        os.remove(path)
    cache_path = chat_store.summary_cache_path(chat_id)
    if os.path.exists(cache_path):
        os.remove(cache_path)
    return True


def count_tokens(llm, messages):
    total = 0
    for m in messages:
        total += len(llm.tokenize(m["content"].encode("utf-8"), add_bos=False))
    return total


def build_context(chat_id, model_name, messages):
    system_content = messages[0]["content"]
    history = messages[1:]

    skills_text = skills.active_skills_text()
    if skills_text:
        system_content += "\n\n" + skills_text

    last_user_msg = next(
        (m["content"] for m in reversed(history) if m["role"] == "user"), ""
    )
    doc_context = documents.document_context_for_query(chat_id, last_user_msg)
    if doc_context:
        system_content += "\n\n" + doc_context

    compressed = False
    if len(history) > RECENT_KEEP_MESSAGES and chat_id:
        cache = chat_store.load_summary_cache(chat_id)
        summarized_count = cache.get("summarized_count", 0)
        keep_from = len(history) - RECENT_KEEP_MESSAGES
        new_chunk = history[summarized_count:keep_from]

        if new_chunk:
            utility_filename = config.get_utility_model_filename()
            small = model_manager.get_model(utility_filename)
            chunk_str = "\n".join(f"{m['role']}: {m['content']}" for m in new_chunk)
            prompt = [
                {
                    "role": "system",
                    "content": (
                        "Du oppdaterer et løpende sammendrag av en samtale mellom en "
                        "bruker og en AI-assistent, på norsk. Slå sammen det eksisterende "
                        "sammendraget med de nye meldingene under, til ett kort, konkret "
                        "sammendrag som bevarer viktige fakta, navn, tall og beslutninger. "
                        "Hold det under 300 ord - prioriter det nyeste og det som fortsatt "
                        "er relevant, dropp smalltalk og detaljer uten betydning videre."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Eksisterende sammendrag:\n{cache.get('summary', '(ingen ennå)')}\n\n"
                        f"Nye meldinger å innlemme:\n{chunk_str}"
                    )
                }
            ]
            resp = small.create_chat_completion(messages=prompt, max_tokens=500, temperature=0.3)
            new_summary = resp["choices"][0]["message"]["content"].strip()
            chat_store.save_summary_cache(chat_id, new_summary, keep_from)
            cache = {"summary": new_summary, "summarized_count": keep_from}

        summary_text = cache.get("summary", "")
        recent = history[keep_from:]
        if summary_text:
            system_content += (
                "\n\nSammendrag av tidligere deler av denne samtalen (eldre meldinger "
                "er komprimert for å spare plass, men brukeren har fortsatt hele "
                "historikken lagret):\n" + summary_text
            )
            compressed = True
    else:
        recent = history

    final_messages = [{"role": "system", "content": system_content}] + recent
    return final_messages, compressed


def estimate_context(chat_id, model_name, messages):
    llm = model_manager.ensure_only_model_loaded(model_name)
    final_messages, compressed = build_context(chat_id, model_name, messages)
    context_used = count_tokens(llm, final_messages)
    context_max = config.load_config().get("context_window", config.DEFAULT_CONTEXT)
    return {"context_used": context_used, "context_max": context_max, "compressed": compressed}