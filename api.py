"""Api-klassen som pywebview eksponerer til JavaScript (window.pywebview.api.*).
Selve logikken bor i de andre modulene - denne klassen er bare en tynn
kobling mellom JS-kall og Python-funksjonene."""

import json

import chats
import config
import documents
import generation
import model_manager
import skills


class Api:
    # ---------------- Modeller ----------------

    def list_models(self):
        models_cfg = config.get_models_config()
        return [
            {"id": fname, "name": cfg["display_name"]}
            for fname, cfg in models_cfg.items() if cfg.get("active", True)
        ]

    def list_all_models_settings(self):
        models_cfg = config.get_models_config()
        return [
            {"filename": fname, "display_name": cfg["display_name"],
             "active": cfg.get("active", True), "device": cfg.get("device", "cpu")}
            for fname, cfg in sorted(models_cfg.items())
        ]

    def update_model_settings(self, filename, display_name, active, device):
        cfg = config.load_config()
        models_cfg = cfg.setdefault("models", {})
        models_cfg[filename] = {"display_name": display_name, "active": active, "device": device}
        config.save_config(cfg)
        model_manager.unload_model(filename)
        return self.list_all_models_settings()

    def get_settings_overview(self):
        cfg = config.load_config()
        return {
            "context_window": cfg.get("context_window", config.DEFAULT_CONTEXT),
            "context_steps": config.CONTEXT_STEPS,
            "n_threads": cfg.get("n_threads", config.DEFAULT_THREADS),
            "utility_model": config.get_utility_model_filename(),
        }

    def set_context_window(self, value):
        cfg = config.load_config()
        cfg["context_window"] = int(value)
        config.save_config(cfg)
        model_manager.unload_all()
        return {"context_window": cfg["context_window"]}

    def set_thread_count(self, value):
        cfg = config.load_config()
        cfg["n_threads"] = int(value)
        config.save_config(cfg)
        model_manager.unload_all()
        model_manager.reset_embedder()
        return {"n_threads": cfg["n_threads"]}

    # ---------------- Samtaler ----------------

    def list_chats(self):
        return chats.list_chats()

    def load_chat(self, chat_id):
        return chats.load_chat(chat_id)

    def save_chat(self, chat_id, name, model_name, messages_json, language="no"):
        return chats.save_chat(chat_id, name, model_name, json.loads(messages_json), language)

    def rename_chat(self, chat_id, new_name):
        return chats.rename_chat(chat_id, new_name)

    def delete_chat(self, chat_id):
        return chats.delete_chat(chat_id)

    # ---------------- Dokumenter ----------------

    def list_documents(self, chat_id):
        return documents.list_documents(chat_id)

    def list_available_documents(self, chat_id):
        return documents.list_available_documents(chat_id)

    def list_all_documents_settings(self):
        return documents.list_all_documents_settings()

    def add_document(self, chat_id):
        return documents.add_document(chat_id)

    def attach_existing_document(self, chat_id, doc_id):
        return documents.attach_existing_document(chat_id, doc_id)

    def detach_document(self, chat_id, doc_id):
        return documents.detach_document(chat_id, doc_id)

    def toggle_document(self, chat_id, doc_id):
        return documents.toggle_document(chat_id, doc_id)

    def delete_document_entirely(self, doc_id):
        return documents.delete_document_entirely(doc_id)

    def preview_document(self, doc_id):
        return documents.preview_document(doc_id)

    # ---------------- Skills ----------------

    def list_skills(self):
        return skills.list_skills()

    def toggle_skill(self, skill_id):
        return skills.toggle_skill(skill_id)

    def add_skill(self, name, content):
        return skills.add_skill(name, content)

    def delete_skill(self, skill_id):
        return skills.delete_skill(skill_id)

    # ---------------- Kontekst og generering ----------------

    def estimate_context(self, chat_id, model_name, messages_json):
        try:
            return chats.estimate_context(chat_id, model_name, json.loads(messages_json))
        except Exception as e:
            return {"error": str(e)}

    def send_message(self, model_name, messages_json, chat_id=None):
        return generation.send_message(model_name, json.loads(messages_json), chat_id)

    def continue_message(self, model_name, messages_json, chat_id=None):
        return generation.continue_message(model_name, json.loads(messages_json), chat_id)
