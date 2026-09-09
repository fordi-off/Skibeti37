"""Loads and unloads GGUF models via llama-cpp-python. Always keeps the
background model (get_utility_model_filename) in memory, but unloads other
large chat models when switching, to avoid holding several 7B-class models
in RAM at once."""

import ctypes
import gc
import os
import time
from llama_cpp import Llama

import applog
import config

loaded_models = {}
embedder = None


def is_loaded(filename):
    return filename in loaded_models


def _available_ram_bytes():
    """Free physical RAM, or None if it can't be determined (non-Windows,
    or the call fails)."""
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullAvailPhys)
    except (AttributeError, OSError):
        pass
    return None


def _kv_cache_reserve(weights_bytes, n_ctx, kv_cache="fp16"):
    """Rough RAM the KV cache will need. Scales with context length and (via
    the file size) the model's depth/width. Deliberately a slight
    over-estimate - better to warn early than swap. q8_0 K/V quantisation
    roughly halves this versus the fp16 default."""
    base = (n_ctx / 4096) * (weights_bytes / 4e9) * 0.5e9
    return base * 0.5 if kv_cache == "q8_0" else base


def _check_ram(path, kv_cache="fp16"):
    """Raise a clear error instead of letting llama.cpp hard-crash the whole
    process (or thrash the disk via mmap) when there isn't enough RAM for a
    model this size plus its KV cache."""
    avail = _available_ram_bytes()
    if avail is None:
        return
    size = os.path.getsize(path)
    n_ctx = config.load_config().get("context_window", config.DEFAULT_CONTEXT)
    needed = size * 1.06 + _kv_cache_reserve(size, n_ctx, kv_cache) + 700_000_000
    if avail < needed:
        raise MemoryError(
            f"Ikke nok ledig minne til å laste denne modellen. Den trenger omtrent "
            f"{needed / 1e9:.1f} GB (modell + kontekst), men bare {avail / 1e9:.1f} GB "
            f"er ledig. Lukk andre programmer, velg en mindre modell, eller senk "
            f"kontekstvinduet i Innstillinger."
        )


def _new_llama(path, n_ctx, n_threads, n_gpu_layers, kv_cache="fp16"):
    common = dict(
        model_path=path, n_ctx=n_ctx, n_threads=n_threads,
        n_gpu_layers=n_gpu_layers, verbose=False,
        # Widen the repetition-penalty window past llama.cpp's default of 64
        # tokens, so the penalty can see - and break out of - paragraph loops.
        last_n_tokens_size=320,
    )
    if kv_cache == "q8_0":
        try:
            # q8_0 K/V cache roughly halves the context memory with no
            # meaningful quality loss. llama.cpp only allows a quantised V
            # cache when flash attention is on, so that has to come with it.
            return Llama(**common, flash_attn=True, type_k=8, type_v=8)
        except Exception:
            applog.log("KV-cache quantization unavailable - using fp16 cache")
    return Llama(**common)


def get_model(filename):
    if filename not in loaded_models:
        path = os.path.join(config.MODELS_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        model_cfg = config.get_models_config().get(filename, {})
        kv_cache = model_cfg.get("kv_cache", "fp16")
        _check_ram(path, kv_cache)
        cfg = config.load_config()
        device = model_cfg.get("device", "cpu")
        n_gpu_layers = -1 if device == "gpu" else 0
        n_ctx = cfg.get("context_window", config.DEFAULT_CONTEXT)
        n_threads = cfg.get("n_threads", config.DEFAULT_THREADS)
        gb = os.path.getsize(path) / 1e9
        applog.log(f"loading model: {filename} ({gb:.1f} GB, ctx {n_ctx}, "
                   f"{device}, kv={kv_cache}) ...")
        t0 = time.time()
        loaded_models[filename] = _new_llama(path, n_ctx, n_threads, n_gpu_layers, kv_cache)
        applog.log(f"model ready: {filename} in {time.time() - t0:.1f}s "
                   f"(resident: {len(loaded_models)})")
    return loaded_models[filename]


def unload_model(filename):
    utility = config.get_utility_model_filename()
    if filename in loaded_models and filename != utility:
        del loaded_models[filename]
        gc.collect()
        applog.log(f"unloaded model: {filename}")


def unload_all():
    if loaded_models:
        applog.log(f"unloading all models ({len(loaded_models)})")
    loaded_models.clear()
    gc.collect()


def unload_all_but_utility():
    """Free every loaded chat model except the small background one - used
    before document indexing so the embedder + utility model don't stack on
    top of a resident 7B/14B and push a low-RAM machine into swap."""
    utility = config.get_utility_model_filename()
    freed = [n for n in loaded_models if n != utility]
    for name in freed:
        del loaded_models[name]
    if freed:
        gc.collect()
        applog.log(f"unloaded for indexing: {', '.join(freed)}")


def remove_model(filename):
    """Unload the model (even the background one) and delete its file plus any
    leftover .part. Raises if the file can't be removed (e.g. still in use)."""
    if filename in loaded_models:
        del loaded_models[filename]
        gc.collect()
    path = os.path.join(config.MODELS_DIR, filename)
    for p in (path, path + ".part"):
        if os.path.isfile(p):
            os.remove(p)


def ensure_only_model_loaded(filename):
    """Loads the requested model and unloads other large chat models that
    are no longer in use (always keeps the background model)."""
    utility = config.get_utility_model_filename()
    for loaded_name in list(loaded_models.keys()):
        if loaded_name != filename and loaded_name != utility:
            unload_model(loaded_name)
    return get_model(filename)


def get_embedder():
    global embedder
    if embedder is None:
        if not os.path.exists(config.EMBED_MODEL_PATH):
            raise FileNotFoundError(
                f"Embedding model not found: {config.EMBED_MODEL_PATH}. "
                "Download nomic-embed-text-v1.5.Q4_K_M.gguf into the models/ folder."
            )
        n_threads = config.load_config().get("n_threads", config.DEFAULT_THREADS)
        applog.log("loading embedder ...")
        t0 = time.time()
        embedder = Llama(
            model_path=config.EMBED_MODEL_PATH, embedding=True,
            n_ctx=2048, n_threads=n_threads, verbose=False
        )
        applog.log(f"embedder ready in {time.time() - t0:.1f}s")
    return embedder


def reset_embedder():
    global embedder
    embedder = None
