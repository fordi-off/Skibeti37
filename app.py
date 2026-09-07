"""
Skibeti37 - local chat app with saved conversations, a document library and skills.

Run with: python app.py  (or double-click Skibeti37.pyw for a windowless launch)
Requires: pip install pywebview llama-cpp-python numpy

The actual logic lives in dedicated modules:
  config.py          - settings and model discovery
  model_manager.py   - loading/unloading GGUF models
  chat_store.py      - raw file storage for conversations
  chats.py           - conversation CRUD and context building/compression
  documents.py       - document library and RAG search
  skills.py          - file-based skills
  generation.py      - the text generation itself (streaming)
  api.py             - the Api class exposed to JavaScript
"""

import os

# Work from the app's own folder no matter how it was launched (shortcut,
# double-click, cmd from elsewhere). All data paths below are relative, and
# without this a shortcut starting in C:\Windows\System32 hits "access denied"
# trying to create ./skills, ./chats, etc.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import webview

import applog
import chat_store
import config
import runtime
import skills
from api import Api


def _startup_census():
    """One-time summary printed to the launching terminal."""
    try:
        models = config.scan_model_files()
        chats = [f for f in os.listdir(chat_store.CHATS_DIR)
                 if f.endswith(".json") and not f.startswith("_")] if os.path.isdir(chat_store.CHATS_DIR) else []
        docs = [f for f in os.listdir("documents") if f.endswith(".json")] if os.path.isdir("documents") else []
        commands = skills.list_commands()
        applog.log(
            f"census: {len(models)} model file(s), {len(chats)} chat(s), "
            f"{len(docs)} document(s), {len(commands)} command(s)"
        )
        if models:
            applog.log("models: " + ", ".join(models))
    except Exception as e:
        applog.error(f"census failed: {e}")


def main():
    applog.log("starting Skibeti37")
    skills.seed_default_skills()
    api = Api()
    _startup_census()
    window = webview.create_window(
        "Skibeti37",
        "static/index.html",
        js_api=api,
        text_select=True,
    )
    window.events.shown += window.maximize
    runtime.window = window
    applog.log("opening window")
    webview.start()
    applog.log("window closed - exiting")


if __name__ == "__main__":
    main()
