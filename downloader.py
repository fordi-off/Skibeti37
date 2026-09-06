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

import config
import runtime

MODELS_DIR = config.MODELS_DIR
CHUNK = 256 * 1024

# role: embed | utility | main | reasoning
#   embed + utility  -> always downloaded (auto)
#   main + reasoning -> user picks a size, or skips
CATALOG = [
    {
        "id": "embed", "role": "embed",
        "filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "display_name": "nomic-embed-text v1.5",
        "size_bytes": 84_000_000,
        "url": "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf",
    },
    {
        "id": "utility", "role": "utility",
        "filename": "qwen2.5-1.5b-instruct-q5_k_m.gguf",
        "display_name": "Qwen2.5 1.5b",
        "size_bytes": 1_290_000_000,
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q5_k_m.gguf",
    },

    # --- main model: choose a size ---
    {
        "id": "main-3b", "role": "main", "size_label": "3B", "note": "raskest, minst minne",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf", "display_name": "Qwen2.5 3b",
        "size_bytes": 1_930_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "main-7b", "role": "main", "size_label": "7B", "default": True, "note": "anbefalt",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf", "display_name": "Qwen2.5 7b",
        "size_bytes": 4_680_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "main-14b", "role": "main", "size_label": "14B", "note": "best kvalitet, trenger ~16 GB RAM",
        "filename": "qwen2.5-14b-instruct-q4_k_m.gguf", "display_name": "Qwen2.5 14b",
        "size_bytes": 8_990_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
    },
    # --- reasoning model: choose a size ---
    {
        "id": "reason-7b", "role": "reasoning", "size_label": "7B", "default": True,
        "note": "anbefalt (uncensored)",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q5_K_M.gguf", "display_name": "DeepSeek R1",
        "size_bytes": 5_440_000_000,
        "url": "https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-Uncensored-i1-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q5_K_M.gguf",
    },
    {
        "id": "reason-14b", "role": "reasoning", "size_label": "14B", "note": "best kvalitet, trenger ~16 GB RAM",
        "filename": "deepseek-r1-distill-qwen-14b-q4_k_m.gguf", "display_name": "DeepSeek R1 14b",
        "size_bytes": 8_990_000_000,
        "url": "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf",
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
    for entry in entries:
        if _cancel.is_set():
            break
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
            elif result == "cancelled":
                break
        except Exception as exc:  # network, disk, SSL...
            _state["failed"].append({"id": entry["id"], "name": entry["display_name"], "error": str(exc)})

        _state["queue"] = [q for q in _state["queue"] if q != entry["id"]]
        _emit()

    _state["current"] = None
    if _cancel.is_set():
        _state["phase"] = "cancelled"
    elif _state["failed"]:
        _state["phase"] = "error"
    else:
        _state["phase"] = "done"
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
