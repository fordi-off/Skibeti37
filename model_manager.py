"""Loads and unloads GGUF models via llama-cpp-python. Always keeps the
background model (get_utility_model_filename) in memory, but unloads other
large chat models when switching, to avoid holding several 7B-class models
in RAM at once."""

import gc
import os
from llama_cpp import Llama

import config

loaded_models = {}
embedder = None


def get_model(filename):
    if filename not in loaded_models:
        path = os.path.join(config.MODELS_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
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
