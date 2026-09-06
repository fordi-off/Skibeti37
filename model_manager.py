"""Loads and unloads GGUF models via llama-cpp-python. Always keeps the
background model (get_utility_model_filename) in memory, but unloads other
large chat models when switching, to avoid holding several 7B-class models
in RAM at once."""

import ctypes
import gc
import os
from llama_cpp import Llama

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


def _check_ram(path):
    """Raise a clear error instead of letting llama.cpp hard-crash the whole
    process when there isn't enough RAM for a model this size."""
    avail = _available_ram_bytes()
    if avail is None:
        return
    size = os.path.getsize(path)
    needed = size * 1.05 + 600_000_000  # model weights + a little runtime headroom
    if avail < needed:
        raise MemoryError(
            f"Ikke nok ledig minne til å laste denne modellen. Den trenger omtrent "
            f"{size / 1e9:.1f} GB, men bare {avail / 1e9:.1f} GB er ledig. Lukk andre "
            f"programmer, velg en mindre modell, eller senk kontekstvinduet i Innstillinger."
        )


def get_model(filename):
    if filename not in loaded_models:
        path = os.path.join(config.MODELS_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        _check_ram(path)
        cfg = config.load_config()
        model_cfg = config.get_models_config().get(filename, {})
        device = model_cfg.get("device", "cpu")
        n_gpu_layers = -1 if device == "gpu" else 0
        n_ctx = cfg.get("context_window", config.DEFAULT_CONTEXT)
        n_threads = cfg.get("n_threads", config.DEFAULT_THREADS)
        loaded_models[filename] = Llama(
            model_path=path, n_ctx=n_ctx, n_threads=n_threads,
            n_gpu_layers=n_gpu_layers, verbose=False
        )
    return loaded_models[filename]


def unload_model(filename):
    utility = config.get_utility_model_filename()
    if filename in loaded_models and filename != utility:
        del loaded_models[filename]
        gc.collect()


def unload_all():
    loaded_models.clear()
    gc.collect()


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
        embedder = Llama(
            model_path=config.EMBED_MODEL_PATH, embedding=True,
            n_ctx=2048, n_threads=n_threads, verbose=False
        )
    return embedder


def reset_embedder():
    global embedder
    embedder = None
