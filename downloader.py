"""In-app model downloader. Holds the catalog of downloadable GGUF files,
runs a sequential download queue in a background thread (resumable via HTTP
Range), and streams progress to the frontend through window.evaluate_js.

Only the standard library is used - urllib handles the HuggingFace CDN
redirect and Range resume fine (see the smoke test in the repo history)."""

import json
import os
import threading
import time
import urllib.request

import config
import runtime

MODELS_DIR = config.MODELS_DIR
CHUNK = 256 * 1024
GB = 1_000_000_000

# role: embed | utility | main | reasoning | extra
# "main" and "reasoning" entries share a slot - the setup screen lets the
# user pick one quant per slot. "basic" marks the four the app expects.
CATALOG = [
    {
        "id": "nomic-embed",
        "name": "nomic-embed-text v1.5 (Q4_K_M)",
        "note": "Kreves for dokumentsøk (RAG). Ikke en chat-modell.",
        "role": "embed", "basic": True,
        "filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "display_name": "nomic-embed-text v1.5",
        "size_bytes": 84_000_000,
        "url": "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf",
    },
    {
        "id": "qwen-1_5b",
        "name": "Qwen2.5 1.5B Instruct (Q5_K_M)",
        "note": "Rask chat + bakgrunnsmodell for sammendrag og komprimering.",
        "role": "utility", "basic": True,
        "filename": "qwen2.5-1.5b-instruct-q5_k_m.gguf",
        "display_name": "Qwen2.5 1.5b",
        "size_bytes": 1_290_000_000,
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q5_k_m.gguf",
    },

    # --- main 7B slot: pick one ---
    {
        "id": "qwen-7b-q4", "name": "Qwen2.5 7B Instruct - Q4_K_M", "role": "main",
        "basic": True, "default": True, "note": "Anbefalt. Best balanse minne/kvalitet.",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf", "display_name": "Qwen2.5 7b",
        "size_bytes": 4_680_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "qwen-7b-q5", "name": "Qwen2.5 7B Instruct - Q5_K_M", "role": "main", "basic": True,
        "note": "Litt bedre kvalitet, ~0,8 GB mer minne.",
        "filename": "qwen2.5-7b-instruct-q5_k_m.gguf", "display_name": "Qwen2.5 7b (Q5)",
        "size_bytes": 5_440_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q5_K_M.gguf",
    },
    {
        "id": "qwen-7b-q6", "name": "Qwen2.5 7B Instruct - Q6_K", "role": "main", "basic": True,
        "note": "Nærmest full kvalitet. Bare for maskiner med rikelig RAM.",
        "filename": "qwen2.5-7b-instruct-q6_k.gguf", "display_name": "Qwen2.5 7b (Q6)",
        "size_bytes": 6_250_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q6_K.gguf",
    },

    # --- reasoning slot: pick one ---
    {
        "id": "deepseek-q4", "name": "DeepSeek-R1 Distill 7B (uncensored) - Q4_K_M",
        "role": "reasoning", "basic": True, "note": "Resonnering/matte/logikk. Minst minne.",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q4_K_M.gguf",
        "display_name": "DeepSeek R1 (Q4)", "size_bytes": 4_680_000_000,
        "url": "https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-Uncensored-i1-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q4_K_M.gguf",
    },
    {
        "id": "deepseek-q5", "name": "DeepSeek-R1 Distill 7B (uncensored) - Q5_K_M",
        "role": "reasoning", "basic": True, "default": True,
        "note": "Anbefalt for denne modellen.",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q5_K_M.gguf",
        "display_name": "DeepSeek R1", "size_bytes": 5_440_000_000,
        "url": "https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-Uncensored-i1-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q5_K_M.gguf",
    },
    {
        "id": "deepseek-q6", "name": "DeepSeek-R1 Distill 7B (uncensored) - Q6_K",
        "role": "reasoning", "basic": True, "note": "Høyest kvalitet, mest minne.",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q6_K.gguf",
        "display_name": "DeepSeek R1 (Q6)", "size_bytes": 6_250_000_000,
        "url": "https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-Uncensored-i1-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q6_K.gguf",
    },

    # --- optional examples ---
    {
        "id": "qwen-0_5b", "name": "Qwen2.5 0.5B Instruct (Q5_K_M)", "role": "extra",
        "note": "Bittesmå, for svake maskiner eller testing.",
        "filename": "qwen2.5-0.5b-instruct-q5_k_m.gguf", "display_name": "Qwen2.5 0.5b",
        "size_bytes": 420_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q5_K_M.gguf",
    },
    {
        "id": "qwen-3b", "name": "Qwen2.5 3B Instruct (Q4_K_M)", "role": "extra",
        "note": "Mellomting - raskere enn 7B, bedre enn 1.5B.",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf", "display_name": "Qwen2.5 3b",
        "size_bytes": 1_930_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "llama-3b", "name": "Llama 3.2 3B Instruct (Q4_K_M)", "role": "extra",
        "note": "Metas lille modell, til sammenligning.",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf", "display_name": "Llama 3.2 3b",
        "size_bytes": 2_020_000_000,
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "qwen-coder-7b", "name": "Qwen2.5 Coder 7B Instruct (Q4_K_M)", "role": "extra",
        "note": "Spesialisert på kode. Fin for programmeringsfag.",
        "filename": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf", "display_name": "Qwen2.5 Coder 7b",
        "size_bytes": 4_680_000_000,
        "url": "https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
    },
]

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


def missing_slots():
    """Which of the four expected pieces are not yet on disk.
    A slot counts as filled if ANY quant for it is installed."""
    have = {e["role"] for e in CATALOG if e["role"] in ("main", "reasoning") and is_installed(e)}
    slots = []
    if not is_installed(_by_id["nomic-embed"]):
        slots.append("embed")
    if not is_installed(_by_id["qwen-1_5b"]):
        slots.append("utility")
    if "main" not in have:
        slots.append("main")
    if "reasoning" not in have:
        slots.append("reasoning")
    return slots


def can_use_app():
    """Minimum to do anything useful: the embedder plus at least one chat model."""
    embed = is_installed(_by_id["nomic-embed"])
    any_chat = any(is_installed(e) for e in CATALOG if e["role"] in ("utility", "main", "reasoning", "extra"))
    return embed and any_chat


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
            "id": entry["id"], "name": entry["name"], "filename": entry["filename"],
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
            _state["failed"].append({"id": entry["id"], "name": entry["name"], "error": str(exc)})

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
    global _thread, _state
    with _lock:
        if _thread and _thread.is_alive():
            return {"error": "already running"}
        entries = [_by_id[i] for i in entry_ids if i in _by_id and not is_installed(_by_id[i])]
        _cancel.clear()
        _state = {
            "phase": "running",
            "queue": [e["id"] for e in entries],
            "current": None, "completed": [], "failed": [],
        }
        _thread = threading.Thread(target=_run, args=(entries,), daemon=True)
        _thread.start()
    return {"started": True, "count": len(entries)}


def cancel():
    _cancel.set()
    return {"cancelling": True}
