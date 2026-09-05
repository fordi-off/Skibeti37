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

import runtime
import skills
from api import Api


def main():
    skills.seed_default_skills()
    api = Api()
    window = webview.create_window(
        "Skibeti37",
        "static/index.html",
        js_api=api,
        text_select=True,
    )
    window.events.shown += window.maximize
    runtime.window = window
    webview.start()


if __name__ == "__main__":
    main()
