"""Conversation CRUD, and the context building itself: merges the system
prompt, active skills, document context (RAG) and an optionally compressed
conversation history into the messages actually sent to the model."""

import os
import time
import uuid

import chat_store
import config
import documents
import model_manager
import skills

RECENT_KEEP_MESSAGES = 10  # number of most recent messages always sent verbatim

# Framing text injected into the system prompt ahead of the rolling summary.
SUMMARY_PREFIX = (
    "Summary of earlier parts of this conversation (older messages are "
    "compressed to save space, but the user still has the full history "
    "saved). Keep replying in the language the user is using:\n"
)


def list_chats():
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


def save_chat(chat_id, name, model_name, messages):
    if not chat_id:
        chat_id = str(uuid.uuid4())
    existing = chat_store.load_chat_raw(chat_id) or {}
    data = {
        "id": chat_id,
        "name": name,
        "model": model_name,
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


def _summary_prompt(existing_summary, new_chunk):
    """Build the utility-model prompt that folds new messages into the
    running summary. The instruction is in English (more reliable for the
    small models); the summary itself follows the conversation's language."""
    chunk_str = "\n".join(f"{m['role']}: {m['content']}" for m in new_chunk)
    return [
        {
            "role": "system",
            "content": (
                "You maintain a running summary of a conversation between a user "
                "and an AI assistant. Merge the existing summary with the new "
                "messages below into one short, concrete summary that preserves "
                "important facts, names, numbers and decisions. Keep it under 300 "
                "words - prioritise the most recent and still-relevant content, "
                "and drop small talk and details that no longer matter. "
                "Write the summary in the same language as the messages below."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Existing summary:\n{existing_summary or '(none yet)'}\n\n"
                f"New messages to incorporate:\n{chunk_str}"
            ),
        },
    ]


def build_context(chat_id, model_name, messages):
    system_content = messages[0]["content"]
    history = messages[1:]

    last_user = next((m for m in reversed(history) if m["role"] == "user"), None)
    last_user_msg = last_user["content"] if last_user else ""

    # Slash commands invoked on the most recent user message apply to this
    # reply only. They are stored on the message itself, so regenerate and
    # edit reuse them without any extra plumbing.
    commands_text = skills.command_bodies(last_user.get("commands") if last_user else None)
    if commands_text:
        system_content += "\n\n" + commands_text

    doc_context, doc_sources = documents.document_context_for_query(chat_id, last_user_msg)
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
            prompt = _summary_prompt(cache.get("summary", ""), new_chunk)
            resp = small.create_chat_completion(messages=prompt, max_tokens=500, temperature=0.3)
            new_summary = resp["choices"][0]["message"]["content"].strip()
            chat_store.save_summary_cache(chat_id, new_summary, keep_from)
            cache = {"summary": new_summary, "summarized_count": keep_from}

        summary_text = cache.get("summary", "")
        recent = history[keep_from:]
        if summary_text:
            system_content += "\n\n" + SUMMARY_PREFIX + summary_text
            compressed = True
    else:
        recent = history

    final_messages = [{"role": "system", "content": system_content}] + recent
    return final_messages, {"compressed": compressed, "doc_sources": doc_sources}


def estimate_context(chat_id, model_name, messages):
    llm = model_manager.ensure_only_model_loaded(model_name)
    final_messages, meta = build_context(chat_id, model_name, messages)
    context_used = count_tokens(llm, final_messages)
    context_max = config.load_config().get("context_window", config.DEFAULT_CONTEXT)
    return {"context_used": context_used, "context_max": context_max, "compressed": meta["compressed"]}
