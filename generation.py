"""The text generation itself - runs in a background thread and streams text
chunks to the frontend via window.evaluate_js, so the UI never freezes while
the model works. The same machinery serves the chat and the Kode page; a
`tag` picks which JS callbacks the chunks go to."""

import json
import threading

import chats
import config
import model_manager
import runtime

SAMPLING_PARAMS = {
    "temperature": 0.6,
    "repeat_penalty": 1.1,
    "frequency_penalty": 0.05,
}

# Reasoning models emit a <think> block and need more room before the answer.
REASONING_MAX_TOKENS = 3000
DEFAULT_MAX_TOKENS = 2000
CODE_MAX_TOKENS = 4000

CONTINUATION_PROMPT = (
    "Continue your previous answer exactly where you left off. Do not repeat "
    "anything you have already written, and do not write any introduction - "
    "continue straight on, in the same language."
)

# tag -> (chunk fn, done fn, error fn, phase fn) on the JS side
_JS = {
    "chat": ("onChunk", "onDone", "onError", "onGenPhase"),
    "code": ("onCodeChunk", "onCodeDone", "onCodeError", "onCodePhase"),
}

# Set by stop() to break out of the streaming loop; cleared when a new
# generation starts.
_stop_event = threading.Event()


def _is_reasoning_model(model_name):
    return "deepseek" in model_name.lower()


def stop():
    """Ask the running generation to stop after the current token."""
    _stop_event.set()
    return {"stopping": True}


def send_message(model_name, messages, chat_id=None):
    return _spawn(model_name, messages, chat_id, continuation=False, tag="chat")


def continue_message(model_name, messages, chat_id=None):
    return _spawn(model_name, messages, chat_id, continuation=True, tag="chat")


def code_stream(model_name, messages, continuation=False):
    return _spawn(model_name, messages, None, continuation=continuation, tag="code")


def _spawn(model_name, messages, chat_id, continuation, tag):
    _stop_event.clear()
    thread = threading.Thread(
        target=_generate, args=(model_name, messages, chat_id, continuation, tag), daemon=True
    )
    thread.start()
    return {"started": True}


def _stream_and_report(llm, final_messages, meta, model_name, max_tokens, on_chunk, on_done):
    context_used = chats.count_tokens(llm, final_messages)
    context_max = config.load_config().get("context_window", config.DEFAULT_CONTEXT)

    finish_reason = None
    stopped = _stop_event.is_set()

    if not stopped:
        stream = llm.create_chat_completion(
            messages=final_messages, max_tokens=max_tokens, stream=True, **SAMPLING_PARAMS
        )
        for chunk in stream:
            if _stop_event.is_set():
                stopped = True
                break
            choice = chunk["choices"][0]
            delta = choice["delta"].get("content", "")
            if delta:
                runtime.window.evaluate_js(f"{on_chunk}({json.dumps(delta)})")
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    info = {
        "truncated": finish_reason == "length",
        "stopped": stopped,
        "compressed": meta.get("compressed", False),
        "doc_sources": meta.get("doc_sources", []),
        "context_used": context_used,
        "context_max": context_max,
    }
    runtime.window.evaluate_js(f"{on_done}({json.dumps(info)})")


def _generate(model_name, messages, chat_id=None, continuation=False, tag="chat"):
    on_chunk, on_done, on_error, on_phase = _JS[tag]
    try:
        msgs = list(messages)
        if continuation:
            msgs.append({"role": "user", "content": CONTINUATION_PROMPT})
        # Loading a cold GGUF blocks for many seconds with nothing to show -
        # tell the UI so it doesn't look frozen.
        phase = "generating" if model_manager.is_loaded(model_name) else "loading"
        runtime.window.evaluate_js(f"{on_phase}({json.dumps(phase)})")
        llm = model_manager.ensure_only_model_loaded(model_name)
        if phase == "loading":
            runtime.window.evaluate_js(f'{on_phase}("generating")')

        if tag == "code":
            final_messages, meta = msgs, {"compressed": False, "doc_sources": []}
            max_tokens = CODE_MAX_TOKENS
        else:
            final_messages, meta = chats.build_context(chat_id, model_name, msgs)
            max_tokens = REASONING_MAX_TOKENS if _is_reasoning_model(model_name) else DEFAULT_MAX_TOKENS

        _stream_and_report(llm, final_messages, meta, model_name, max_tokens, on_chunk, on_done)
    except Exception as e:
        runtime.window.evaluate_js(f"{on_error}({json.dumps(str(e))})")
