"""In-app model downloader. Holds the catalog of downloadable GGUF files,
runs a sequential download queue in a background thread (resumable via HTTP
Range), and streams progress to the frontend through window.evaluate_js.

Only the standard library is used - urllib handles the HuggingFace CDN
redirect and Range resume fine, EXCEPT that on at least one real machine
Python's own (OpenSSL-based) TLS stack was found to get throttled hard by
the network (fast burst, then a few KB/s) on a URL that downloaded at full,
sustained speed via curl.exe and a normal browser - both of which use the
OS's native TLS stack (SChannel on Windows) instead of Python's bundled
one. Some corporate network security appliances rate-limit/deprioritize
traffic with a non-native TLS fingerprint. So curl.exe is used for the
actual transfer whenever it's available (true by default on Windows 10
1803+ and virtually all Linux/macOS installs), with the pure-urllib path
below kept as the fallback for machines that don't have it."""

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

import applog
import config
import runtime

MODELS_DIR = config.MODELS_DIR
CHUNK = 256 * 1024
CURL_PATH = shutil.which("curl") or shutil.which("curl.exe")

# role: embed | utility | main
#   embed + utility -> always downloaded (auto)
#   main            -> user picks a size, or skips
#
# Main + utility are Qwen3.5 (2026). The plain Qwen3/3.5 models are "hybrid" -
# they can think or answer directly; generation.py/model_manager.py force
# thinking off unconditionally for any model with "qwen3" in its filename
# (see complete_no_think there - llama.cpp currently ignores these models'
# own enable_thinking=false, so the app primes an already-closed
# <think></think> in the raw prompt instead). There's no reasoning-model
# support anymore: a dedicated thinking/DeepSeek-R1 .gguf added to models/ by
# hand still loads and runs, but any <think> block it emits just shows up as
# plain text - the app doesn't recognize or collapse it. Older Qwen2.5
# .gguf files keep working as plain chat models.
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
        "id": "main-8b-no", "role": "main", "size_label": "8B", "note": "norsk-tilpasset (NB), ~7 GB RAM",
        # Llama 3.1 8B fine-tuned by the National Library of Norway (NoTraM
        # project) specifically for Norwegian Bokmal/Nynorsk - worth trying
        # since every reply in this app is in Norwegian. Plain Llama, not
        # hybrid - no thinking-mode handling needed.
        "filename": "nb-llama-3.1-8b-instruct-q4_k_m.gguf", "display_name": "NB Llama 3.1 8b (norsk)",
        "size_bytes": 4_920_000_000,
        "url": f"{_HF}/NbAiLab/nb-llama-3.1-8B-Instruct-Q4_K_M-GGUF/resolve/main/nb-llama-3.1-8b-instruct-q4_k_m.gguf",
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

    # No "reasoning" role for now - the dedicated thinking/DeepSeek-R1 models
    # were dropped from the guided installer (buggy, not needed for the
    # common case). generation.py/chat.js still detect and handle a reasoning
    # model by filename ("thinking"/"deepseek"/"-r1-") if one is added to
    # models/ by hand.
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
            "active": True, "device": "cpu", "kv_cache": "fp16",
        }
        config.save_config(cfg)


# A custom User-Agent here was found to get throttled hard by at least one
# corporate network's traffic shaping (fast burst, then down to a few KB/s
# after some seconds) - the exact same URL has no such problem in a normal
# browser tab. A browser-like User-Agent (plus the headers a browser would
# normally send alongside it) is sent on every request below.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Splitting a fresh download into several parallel Range requests instead of
# one long-lived connection: the burst-then-throttle pattern above looks like
# per-connection bandwidth shaping, which parallel connections (same trick
# download managers like aria2/IDM use) route around - each connection gets
# its own burst allowance and its own cap, so total throughput multiplies
# roughly with the connection count instead of being stuck at one cap.
PARALLEL_CONNECTIONS = 4
MIN_PARALLEL_SIZE = 8 * 1024 * 1024  # not worth splitting anything smaller


def _headers(extra=None):
    headers = dict(_BROWSER_HEADERS)
    if extra:
        headers.update(extra)
    return headers


def _probe_total_size(url):
    """Content-Length via HEAD; falls back to a 1-byte ranged GET for
    servers that don't answer HEAD requests usefully."""
    try:
        req = urllib.request.Request(url, headers=_headers(), method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            length = resp.headers.get("Content-Length")
            if length:
                return int(length)
    except Exception:
        pass
    req = urllib.request.Request(url, headers=_headers({"Range": "bytes=0-0"}))
    with urllib.request.urlopen(req, timeout=30) as resp:
        content_range = resp.headers.get("Content-Range")  # "bytes 0-0/12345"
        if content_range and "/" in content_range:
            return int(content_range.rsplit("/", 1)[1])
        return int(resp.headers.get("Content-Length") or 0)


def _download_sequential(url, part, have, on_progress):
    """One connection, resumable via Range - used to resume a partially
    downloaded file (parallel writes don't track which byte ranges of a
    previous run actually finished) and as the fallback when the server's
    total size can't be determined or the file is too small to bother
    splitting."""
    headers = _headers({"Range": f"bytes={have}-"} if have else None)
    req = urllib.request.Request(url, headers=headers)

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
                if now - last_t >= 0.2:
                    on_progress(downloaded, total, (downloaded - last_b) / (now - last_t))
                    last_t, last_b = now, downloaded
    return "done"


def _download_segment(url, part, start, end, counter, lock):
    """Fetch bytes [start, end] (inclusive) and write them straight into the
    destination file at the right offset. Each worker opens its OWN handle to
    the shared,
    pre-sized destination file rather than sharing one file object/descriptor
    across threads: a file position is per-handle, so independent handles
    seeking and writing to disjoint byte ranges can't race each other, with
    no need for os.pwrite (POSIX-only - not available on Windows at all)."""
    req = urllib.request.Request(url, headers=_headers({"Range": f"bytes={start}-{end}"}))
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "r+b") as f:
        f.seek(start)
        while True:
            if _cancel.is_set():
                return
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            f.write(chunk)
            with lock:
                counter[0] += len(chunk)


def _segment_worker(url, part, start, end, counter, lock, errors):
    try:
        _download_segment(url, part, start, end, counter, lock)
    except Exception as exc:
        errors.append(exc)


def _download_parallel(url, part, total, on_progress, n_conns=PARALLEL_CONNECTIONS):
    with open(part, "wb") as f:
        f.truncate(total)  # pre-size so every worker's own handle can seek+write its own region

    bounds = []
    seg_size = total // n_conns
    pos = 0
    for i in range(n_conns):
        start = pos
        end = total - 1 if i == n_conns - 1 else pos + seg_size - 1
        bounds.append((start, end))
        pos = end + 1

    counter = [0]
    lock = threading.Lock()
    errors = []
    threads = [
        threading.Thread(target=_segment_worker, args=(url, part, start, end, counter, lock, errors), daemon=True)
        for start, end in bounds
    ]
    for t in threads:
        t.start()

    last_t, last_b = time.time(), 0
    while any(t.is_alive() for t in threads):
        time.sleep(0.2)
        if _cancel.is_set():
            break
        now = time.time()
        if now - last_t >= 0.2:
            with lock:
                downloaded = counter[0]
            on_progress(downloaded, total, (downloaded - last_b) / (now - last_t))
            last_t, last_b = now, downloaded
    for t in threads:
        t.join(timeout=5)

    if _cancel.is_set():
        return "cancelled"
    if errors:
        raise errors[0]
    with lock:
        on_progress(counter[0], total, 0.0)
    return "done"


def _download_via_curl(url, part, have, total_hint, on_progress):
    """Shell out to curl.exe for the actual transfer (see the module
    docstring for why) - follows redirects, resumes via -C, fails loudly on
    an HTTP error instead of silently saving an error page as the file.
    Progress is sampled by polling the destination file's growing size
    rather than parsing curl's own progress meter, which is meant for a
    terminal, not a script."""
    args = [CURL_PATH, "-L", "--fail", "--silent", "--show-error",
            "-A", _BROWSER_HEADERS["User-Agent"], "-o", part]
    if have:
        args += ["-C", str(have)]
    args.append(url)

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        last_t, last_b = time.time(), have
        while proc.poll() is None:
            if _cancel.is_set():
                proc.terminate()
                return "cancelled"
            time.sleep(0.15)
            downloaded = os.path.getsize(part) if os.path.isfile(part) else have
            now = time.time()
            if now - last_t >= 0.2:
                on_progress(downloaded, total_hint or downloaded, (downloaded - last_b) / (now - last_t))
                last_t, last_b = now, downloaded
    finally:
        stderr = proc.stderr.read() if proc.stderr else ""

    if _cancel.is_set():
        return "cancelled"
    if proc.returncode != 0:
        raise IOError(f"curl feilet (kode {proc.returncode}): {stderr.strip()[:300] or 'ukjent feil'}")
    downloaded = os.path.getsize(part) if os.path.isfile(part) else 0
    on_progress(downloaded, total_hint or downloaded, 0.0)
    return "done"


def _download_one(entry, on_progress):
    if _cancel.is_set():
        return "cancelled"
    dest = _dest(entry)
    if os.path.isfile(dest):
        return "already"
    os.makedirs(MODELS_DIR, exist_ok=True)
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    url = entry["url"] + "?download=true"

    if CURL_PATH:
        result = _download_via_curl(url, part, have, entry.get("size_bytes", 0), on_progress)
    elif have:
        result = _download_sequential(url, part, have, on_progress)
    else:
        total = _probe_total_size(url)
        if total and total >= MIN_PARALLEL_SIZE:
            result = _download_parallel(url, part, total, on_progress)
        else:
            result = _download_sequential(url, part, 0, on_progress)
    if result != "done":
        return result

    expected = entry.get("size_bytes", 0)
    if expected and os.path.getsize(part) < expected * 0.999:
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
