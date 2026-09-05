"""Rå lesing/skriving av samtale-JSON-filer og sammendrag-cache. Brukes av
både chats.py (samtale-CRUD) og documents.py (attach/detach), derfor egen
modul for å unngå sirkulære imports."""

import json
import os

CHATS_DIR = "./chats"
SUMMARY_DIR = "./chats/_context_summaries"
os.makedirs(CHATS_DIR, exist_ok=True)
os.makedirs(SUMMARY_DIR, exist_ok=True)


def chat_path(chat_id):
    return os.path.join(CHATS_DIR, f"{chat_id}.json")


def load_chat_raw(chat_id):
    path = chat_path(chat_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_chat_raw(chat_id, data):
    with open(chat_path(chat_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def summary_cache_path(chat_id):
    return os.path.join(SUMMARY_DIR, f"{chat_id}.json")


def load_summary_cache(chat_id):
    path = summary_cache_path(chat_id)
    if not os.path.exists(path):
        return {"summary": "", "summarized_count": 0}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_summary_cache(chat_id, summary, summarized_count):
    with open(summary_cache_path(chat_id), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "summarized_count": summarized_count}, f, ensure_ascii=False, indent=2)
