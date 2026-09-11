"""In-app model downloader. Holds the catalog of downloadable GGUF files,
runs a sequential download queue in a background thread (resumable via HTTP
Range), and streams progress to the frontend through window.evaluate_js.

Only the standard library is used - urllib handles the HuggingFace CDN
redirect and Range resume fine."""

import json
import os
import threading
import time
import urllib.request

import applog
import config
import runtime

MODELS_DIR = config.MODELS_DIR
CHUNK = 256 * 1024

# role: embed | utility | main | reasoning
#   embed + utility  -> always downloaded (auto)
#   main + reasoning -> user picks a size, or skips
#
# Main + utility are Qwen3.5 (2026). The plain Qwen3/3.5 models are "hybrid" -
# they can think or answer directly; generation.py/model_manager.py force
# thinking off for the chat slot (see complete_no_think there - llama.cpp
# currently ignores these models' own enable_thinking=false, so the app
# primes an already-closed <think></think> in the raw prompt instead). The
# reasoning slot uses single-mode models (Qwen3-*-Thinking, the
# DeepSeek-R1 distill) whose names encode "thinking"/"deepseek" so the app can
# tell them apart. Older Qwen2.5 / DeepSeek .gguf files keep working.
_HF = "https://huggingface.co"
CATALOG = [
    {
        "id": "embed", "role": "embed",
        "filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "display_name": "nomic-embed-text v1.5",
        "size_bytes": 84_000_000,
        "url": f"{_HF}/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf",
    },
    {
        "id": "utility", "role": "utility",
        "filename": "Qwen_Qwen3.5-2B-Q5_K_M.gguf",
        "display_name": "Qwen3.5 2b",
        "size_bytes": 1_568_476_256,
        "url": f"{_HF}/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/Qwen_Qwen3.5-2B-Q5_K_M.gguf",
    },

    # --- main model (normal chat): choose a size ---
    {
        "id": "main-4b", "role": "main", "size_label": "4B", "note": "raskest, minst minne",
        "filename": "Qwen_Qwen3.5-4B-Q4_K_M.gguf", "display_name": "Qwen3.5 4b",
        "size_bytes": 3_013_027_808,
        "url": f"{_HF}/bartowski/Qwen_Qwen3.5-4B-GGUF/resolve/main/Qwen_Qwen3.5-4B-Q4_K_M.gguf",
    },
    {
        "id": "main-8b", "role": "main", "size_label": "8B", "note": "sterkere enn 7B, ~7 GB RAM",
        # Plain Qwen3 (not 3.5) - one generation newer/stronger than a 7B like
        # Qwen2.5, still noticeably lighter than the 9B. It's hybrid like the
        # 3.5 line, so generation.py forces thinking off for it in this slot
        # (see _wants_no_think there).
        "filename": "Qwen_Qwen3-8B-Q4_K_M.gguf", "display_name": "Qwen3 8b",
        "size_bytes": 5_027_783_040,
        "url": f"{_HF}/bartowski/Qwen_Qwen3-8B-GGUF/resolve/main/Qwen_Qwen3-8B-Q4_K_M.gguf",
    },
    {
        "id": "main-9b", "role": "main", "size_label": "9B", "default": True, "note": "anbefalt, ~8 GB RAM",
        "filename": "Qwen_Qwen3.5-9B-Q4_K_M.gguf", "display_name": "Qwen3.5 9b",
        "size_bytes": 6_169_341_984,
        "url": f"{_HF}/bartowski/Qwen_Qwen3.5-9B-GGUF/resolve/main/Qwen_Qwen3.5-9B-Q4_K_M.gguf",
    },
    {
        "id": "main-9b-compact", "role": "main", "size_label": "9B", "note": "kompakt (Q3), ~7 GB RAM",
        "filename": "Qwen_Qwen3.5-9B-Q3_K_M.gguf", "display_name": "Qwen3.5 9b (Q3)",
        "size_bytes": 5_178_748_960,
        "url": f"{_HF}/bartowski/Qwen_Qwen3.5-9B-GGUF/resolve/main/Qwen_Qwen3.5-9B-Q3_K_M.gguf",
    },

    # --- reasoning model (math / logic, shows its thinking): choose a size ---
    {
        "id": "reason-4b", "role": "reasoning", "size_label": "4B", "default": True,
        "note": "raskest",
        "filename": "Qwen_Qwen3-4B-Thinking-2507-Q4_K_M.gguf", "display_name": "Qwen3 4b (tenkning)",
        "size_bytes": 2_497_280_736,
        "url": f"{_HF}/bartowski/Qwen_Qwen3-4B-Thinking-2507-GGUF/resolve/main/Qwen_Qwen3-4B-Thinking-2507-Q4_K_M.gguf",
    },
    {
        "id": "reason-8b", "role": "reasoning", "size_label": "8B", "note": "anbefalt, sterk pa matte",
        "filename": "deepseek-ai_DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
        "display_name": "DeepSeek R1 (Qwen3 8b)",
        "size_bytes": 5_027_783_040,
        "url": f"{_HF}/bartowski/deepseek-ai_DeepSeek-R1-0528-Qwen3-8B-GGUF/resolve/main/deepseek-ai_DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
    },
]

AUTO_IDS = ["embed", "utility"]
_by_id = {e["id"]: e for e in CATALOG}

_lock = threading.Lock()
_cancel = threading.Event()
_thread = None
_state = {"phase": "idle", "queue": [], "current": None, "completed": [], "failed": []}


def _dest(entry):
    return os.path.join(MODELS_DIR, entry["filename"])


def is_installed(entry):
    return os.path.isfile(_dest(entry))


def catalog_with_status():
    return [{**e, "installed": is_installed(e)} for e in CATALOG]


def needs_setup():
    """True while the two always-required files aren't both on disk. That is
    the only thing that forces the setup panel; everything else is optional."""
    return not all(is_installed(_by_id[i]) for i in AUTO_IDS)


def state():
    return dict(_state)


def _emit():
    try:
        runtime.window.evaluate_js(f"onDownloadState({json.dumps(_state)})")
    except Exception:
        pass


def _register_in_config(entry):
    if entry["role"] == "embed":
        return
    cfg = config.load_config()
    models = cfg.setdefault("models", {})
    if entry["filename"] not in models:
        models[entry["filename"]] = {
            "display_name": entry.get("display_name") or config.humanize_filename(entry["filename"]),
            "active": True, "device": "cpu",
        }
        config.save_config(cfg)


def _download_one(entry, on_progress):
    if _cancel.is_set():
        return "cancelled"
    dest = _dest(entry)
    if os.path.isfile(dest):
        return "already"
    os.makedirs(MODELS_DIR, exist_ok=True)
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0

    headers = {"User-Agent": "Skibeti37"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(entry["url"] + "?download=true", headers=headers)

    with urllib.request.urlopen(req, timeout=60) as resp:
        clen = int(resp.headers.get("Content-Length") or 0)
        if resp.status == 206:
            total, mode, downloaded = have + clen, "ab", have
        else:
            total, mode, downloaded = clen, "wb", 0
        on_progress(downloaded, total, 0.0)

        last_t, last_b = time.time(), downloaded
        with open(part, mode) as f:
            while True:
                if _cancel.is_set():
                    return "cancelled"
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_t >= 0.4:
                    on_progress(downloaded, total, (downloaded - last_b) / (now - last_t))
                    last_t, last_b = now, downloaded

    if total and os.path.getsize(part) < total * 0.999:
        raise IOError("nedlastingen ble avbrutt før den var ferdig")
    os.replace(part, dest)
    return "done"


def _run(entries):
    global _thread
    applog.log(f"download queue ({len(entries)}): {', '.join(e['id'] for e in entries)}")
    for entry in entries:
        if _cancel.is_set():
            break
        applog.log(f"downloading {entry['filename']} "
                   f"(~{entry.get('size_bytes', 0) / 1e9:.1f} GB) ...")
        _state["current"] = {
            "id": entry["id"], "name": entry["display_name"], "filename": entry["filename"],
            "downloaded": 0, "total": entry.get("size_bytes", 0), "speed": 0.0,
        }
        _emit()

        def progress(done, total, speed, _e=entry):
            _state["current"].update(downloaded=done, total=total or _e.get("size_bytes", 0), speed=speed)
            _emit()

        try:
            result = _download_one(entry, progress)
            if result in ("done", "already"):
                _register_in_config(entry)
                _state["completed"].append(entry["id"])
                applog.log(f"downloaded {entry['filename']}"
                           + (" (already on disk)" if result == "already" else ""))
            elif result == "cancelled":
                applog.log("download cancelled")
                break
        except Exception as exc:  # network, disk, SSL...
            _state["failed"].append({"id": entry["id"], "name": entry["display_name"], "error": str(exc)})
            applog.error(f"download failed for {entry['id']}: {exc}")

        _state["queue"] = [q for q in _state["queue"] if q != entry["id"]]
        _emit()

    _state["current"] = None
    if _cancel.is_set():
        _state["phase"] = "cancelled"
    elif _state["failed"]:
        _state["phase"] = "error"
    else:
        _state["phase"] = "done"
    applog.log(f"download queue finished: {_state['phase']} "
               f"({len(_state['completed'])} ok, {len(_state['failed'])} failed)")
    _emit()
    _thread = None


def start(entry_ids):
    """entry_ids from the UI. The two auto files are always prepended."""
    global _thread, _state
    with _lock:
        if _thread and _thread.is_alive():
            return {"error": "already running"}
        wanted = list(dict.fromkeys(AUTO_IDS + [i for i in entry_ids if i in _by_id]))
        entries = [_by_id[i] for i in wanted if not is_installed(_by_id[i])]
        _cancel.clear()
        _state = {
            "phase": "running" if entries else "done",
            "queue": [e["id"] for e in entries],
            "current": None, "completed": [], "failed": [],
        }
        if not entries:
            _emit()
            return {"started": True, "count": 0}
        _thread = threading.Thread(target=_run, args=(entries,), daemon=True)
        _thread.start()
    return {"started": True, "count": len(entries)}


def cancel():
    _cancel.set()
    return {"cancelling": True}
