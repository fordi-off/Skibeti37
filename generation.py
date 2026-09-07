"""The text generation itself - runs in a background thread and streams text
chunks to the frontend via window.evaluate_js, so the UI never freezes while
the model works."""

import json
import threading

import chats
import config
import model_manager
import runtime

SAMPLING_PARAMS = {
    "temperature": 0.6,
    "top_p": 0.95,
    # repeat_penalty acts over the last last_n_tokens_size tokens (320, set in
    # model_manager). presence_penalty is a flat one-off nudge that helps break
    # loops without escalating per token the way a high frequency_penalty does -
    # frequency_penalty is kept low on purpose (Qwen code-switches to Chinese
    # when common words get too "expensive" to repeat).
    "repeat_penalty": 1.18,
    "frequency_penalty": 0.1,
    "presence_penalty": 0.3,
}

# If the same long span of text keeps coming back, the model has degenerated
# into a loop - stop the stream instead of filling the whole token budget with
# repeats.
_LOOP_WINDOW = 180
_LOOP_THRESHOLD = 3


def _looks_looped(text):
    if len(text) < _LOOP_WINDOW * _LOOP_THRESHOLD:
        return False
    tail = text[-_LOOP_WINDOW:]
    return text.count(tail) >= _LOOP_THRESHOLD

# Reasoning models emit a <think> block and need more room before the answer.
REASONING_MAX_TOKENS = 3000
DEFAULT_MAX_TOKENS = 2000

CONTINUATION_PROMPT = (
    "Continue your previous answer exactly where you left off. Do not repeat "
    "anything you have already written, and do not write any introduction - "
    "continue straight on, in the very same language as the rest of your answer."
)

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
    return _spawn(model_name, messages, chat_id, continuation=False)


def continue_message(model_name, messages, chat_id=None):
    return _spawn(model_name, messages, chat_id, continuation=True)


def _spawn(model_name, messages, chat_id, continuation):
    _stop_event.clear()
    thread = threading.Thread(
        target=_generate, args=(model_name, messages, chat_id, continuation), daemon=True
    )
    thread.start()
    return {"started": True}


def _stream_and_report(llm, final_messages, meta, model_name):
    context_used = chats.count_tokens(llm, final_messages)
    context_max = config.load_config().get("context_window", config.DEFAULT_CONTEXT)
    max_tokens = REASONING_MAX_TOKENS if _is_reasoning_model(model_name) else DEFAULT_MAX_TOKENS

    finish_reason = None
    stopped = _stop_event.is_set()
    looped = False

    if not stopped:
        stream = llm.create_chat_completion(
            messages=final_messages, max_tokens=max_tokens, stream=True, **SAMPLING_PARAMS
        )
        answer = ""
        checked_at = 0
        for chunk in stream:
            if _stop_event.is_set():
                stopped = True
                break
            choice = chunk["choices"][0]
            delta = choice["delta"].get("content", "")
            if delta:
                answer += delta
                runtime.window.evaluate_js(f"onChunk({json.dumps(delta)})")
                if len(answer) - checked_at >= 120:
                    checked_at = len(answer)
                    if _looks_looped(answer):
                        looped = True
                        break
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    info = {
        "truncated": finish_reason == "length",
        "stopped": stopped,
        "looped": looped,
        "compressed": meta.get("compressed", False),
        "doc_sources": meta.get("doc_sources", []),
        "context_used": context_used,
        "context_max": context_max,
    }
    runtime.window.evaluate_js(f"onDone({json.dumps(info)})")


def _generate(model_name, messages, chat_id=None, continuation=False):
    try:
        msgs = list(messages)
        if continuation:
            msgs.append({"role": "user", "content": CONTINUATION_PROMPT})
        # Loading a cold GGUF blocks for many seconds with nothing to show -
        # tell the UI so it doesn't look frozen.
        phase = "generating" if model_manager.is_loaded(model_name) else "loading"
        runtime.window.evaluate_js(f"onGenPhase({json.dumps(phase)})")
        llm = model_manager.ensure_only_model_loaded(model_name)
        if phase == "loading":
            runtime.window.evaluate_js('onGenPhase("generating")')
        final_messages, meta = chats.build_context(chat_id, model_name, msgs)
        _stream_and_report(llm, final_messages, meta, model_name)
    except Exception as e:
        runtime.window.evaluate_js(f"onError({json.dumps(str(e))})")
