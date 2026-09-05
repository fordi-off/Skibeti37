"""
Skibeti37 - lokal chat-app med lagrede samtaler, dokumentbibliotek og skills.

Kjør med: python app.py
Krever: pip install pywebview llama-cpp-python numpy

Selve logikken bor i egne moduler:
  config.py          - innstillinger og modell-oppdagelse
  model_manager.py   - lasting/lossing av GGUF-modeller
  chat_store.py       - rå fil-lagring for samtaler
  chats.py            - samtale-CRUD og kontekstbygging/komprimering
  documents.py        - dokumentbibliotek og RAG-søk
  skills.py           - fil-baserte skills
  generation.py        - selve tekstgenereringen (streaming)
  api.py              - Api-klassen eksponert til JavaScript
"""

import webview

import runtime
import skills
from api import Api

skills.seed_default_skills()

if __name__ == "__main__":
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
