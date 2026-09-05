"""Innstillinger og modell-oppdagelse. config.json lagrer visningsnavn,
aktiv-status og CPU/GPU-valg per modellfil, samt kontekstvindu og tråd-antall."""

import json
import os

MODELS_DIR = "./models"
EMBED_MODEL_PATH = "./models/nomic-embed-text-v1.5.Q4_K_M.gguf"
CONFIG_PATH = "./config.json"

CONTEXT_STEPS = [4096, 8192, 16384, 32768, 65536, 131072]
DEFAULT_CONTEXT = 16384
DEFAULT_THREADS = 6


def default_config():
    return {"context_window": DEFAULT_CONTEXT, "n_threads": DEFAULT_THREADS, "utility_model": None, "models": {}}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(default_config())
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for key, val in default_config().items():
        cfg.setdefault(key, val)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def humanize_filename(fname):
    stem = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").strip()
    return (stem[:1].upper() + stem[1:]) if stem else fname


def scan_model_files():
    if not os.path.isdir(MODELS_DIR):
        return []
    embed_basename = os.path.basename(EMBED_MODEL_PATH)
    return sorted(
        f for f in os.listdir(MODELS_DIR)
        if f.lower().endswith(".gguf") and f != embed_basename
    )


def get_models_config():
    """Slår sammen filene som faktisk finnes i models/-mappen med lagrede
    innstillinger fra config.json. Nye filer får fornuftige standardverdier."""
    cfg = load_config()
    files = scan_model_files()
    models_cfg = cfg.get("models", {})
    result = {}
    changed = False
    for f in files:
        entry = models_cfg.get(f)
        if entry is None:
            entry = {"display_name": humanize_filename(f), "active": True, "device": "cpu"}
            models_cfg[f] = entry
            changed = True
        else:
            before = dict(entry)
            entry.setdefault("display_name", humanize_filename(f))
            entry.setdefault("active", True)
            entry.setdefault("device", "cpu")
            if entry != before:
                changed = True
        result[f] = entry
    if changed:
        cfg["models"] = models_cfg
        save_config(cfg)
    return result


def get_utility_model_filename():
    """Modellen brukt til bakgrunnsoppgaver (dokument-oppsummering,
    samtale-komprimering): eksplisitt valgt modell hvis satt, ellers den
    minste aktive modellfilen."""
    cfg = load_config()
    models_cfg = get_models_config()
    forced = cfg.get("utility_model")
    active_files = [f for f, c in models_cfg.items() if c.get("active", True)]
    if forced and forced in active_files:
        return forced
    if not active_files:
        return None
    return min(active_files, key=lambda f: os.path.getsize(os.path.join(MODELS_DIR, f)))
