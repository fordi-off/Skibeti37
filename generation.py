"""The text generation itself - runs in a background thread and streams text
chunks to the frontend via window.evaluate_js, so the UI never freezes while
the model works."""

import json
import threading
import time

import applog
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


def _fit_to_context(llm, messages, context_max, response_reserve):
    """Make sure the prompt leaves room for the reply. Without this a long
    pasted article or a big document context can exceed n_ctx - llama.cpp
    then either errors or spends minutes prefilling with nothing on screen,
    which reads as a freeze. Returns (messages, trimmed?)."""
    budget = max(512, context_max - response_reserve - 64)
    if chats.count_tokens(llm, messages) <= budget:
        return messages, False

    system, rest = messages[0], list(messages[1:])
    # Drop whole turns from the oldest end, but always keep the final message.
    while len(rest) > 1 and chats.count_tokens(llm, [system] + rest) > budget:
        rest.pop(0)
    msgs = [system] + rest

    _CUT = "\n\n[...forkortet for a passe kontekstvinduet...]"

    # Still over: the system block (persona + skills + document excerpts) is
    # itself too big. Keep the head, cut the tail (the excerpts sit last).
    if chats.count_tokens(llm, msgs) > budget:
        over = chats.count_tokens(llm, msgs) - budget
        keep = max(400, len(system["content"]) - over * 4 - len(_CUT) - 400)
        msgs[0] = {"role": "system", "content": system["content"][:keep].rstrip() + _CUT}

    # Last resort: a single giant message. Trim it by characters, head kept.
    if chats.count_tokens(llm, msgs) > budget and len(msgs) > 1:
        head_tokens = chats.count_tokens(llm, msgs[:-1])
        room_chars = max(400, (budget - head_tokens) * 4 - len(_CUT) - 400)
        last = msgs[-1]
        msgs[-1] = {**last, "content": last["content"][:room_chars].rstrip() + _CUT}

    return msgs, True

# Reasoning models emit a <think> block and need more room before the answer.
# Qwen3-Thinking in particular can be long-winded inside <think>.
REASONING_MAX_TOKENS = 4000
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
    """A model whose replies contain a <think> block: the DeepSeek-R1 distills
    and Qwen3's dedicated *-Thinking* variants."""
    low = model_name.lower()
    return "deepseek" in low or "-r1-" in low or "thinking" in low


def _wants_no_think(model_name):
    """Plain Qwen3 models are hybrid - think or answer directly - and belong
    in the chat slot with thinking off. The single-mode 2507 variants, the
    DeepSeek distill and non-Qwen3 models are excluded: they either can't
    think at all or are reasoning models that should."""
    return "qwen3" in model_name.lower() and not _is_reasoning_model(model_name)


def _apply_thinking_tag(final_messages, model_name):
    """Force the reasoning slot's hybrid Qwen3 models into thinking mode via
    the standard /think tag. The chat slot's opposite case (/no_think) isn't
    applied here - llama.cpp currently ignores Qwen3.5's enable_thinking=false
    (ggml-org/llama.cpp #20182, #20409), so the model thinks anyway and, since
    it isn't primed to wrap that in <think>, the raw chain-of-thought leaks
    straight into the visible reply instead of being caught by the UI's
    <think>-block safety net. _stream_and_report primes an empty, already-
    closed <think></think> in the raw prompt instead, which sidesteps the
    template bug entirely rather than depending on the broken flag."""
    if "qwen3" not in model_name.lower() or not _is_reasoning_model(model_name):
        return
    tag = "/think"
    for m in reversed(final_messages):
        if m["role"] == "user":
            if not m["content"].rstrip().endswith(tag):
                m["content"] = m["content"].rstrip() + " " + tag
            return


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
    context_max = config.load_config().get("context_window", config.DEFAULT_CONTEXT)
    max_tokens = REASONING_MAX_TOKENS if _is_reasoning_model(model_name) else DEFAULT_MAX_TOKENS

    final_messages, trimmed = _fit_to_context(llm, final_messages, context_max, max_tokens)
    context_used = chats.count_tokens(llm, final_messages)
    applog.log(f"generating: {model_name} | {context_used}/{context_max} ctx tokens"
               + (" | prompt trimmed to fit" if trimmed else "")
               + (" | history compressed" if meta.get("compressed") else "")
               + (f" | {len(meta.get('doc_sources', []))} doc excerpts" if meta.get("doc_sources") else ""))

    finish_reason = None
    stopped = _stop_event.is_set()
    looped = False
    t0 = time.time()
    n_tokens = 0

    if not stopped:
        if _wants_no_think(model_name):
            # Bypass create_chat_completion's template entirely for this case -
            # see _apply_thinking_tag for why the soft /no_think signal can't
            # be trusted to actually turn thinking off.
            prompt = model_manager.render_forced_no_think_prompt(final_messages)
            stream = llm.create_completion(
                prompt=prompt, max_tokens=max_tokens, stream=True,
                stop=["<|im_end|>", "<|im_start|>"], **SAMPLING_PARAMS
            )
        else:
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
            delta = choice["delta"].get("content", "") if "delta" in choice else choice.get("text", "")
            if delta:
                n_tokens += 1
                answer += delta
                runtime.window.evaluate_js(f"onChunk({json.dumps(delta)})")
                if len(answer) - checked_at >= 120:
                    checked_at = len(answer)
                    if _looks_looped(answer):
                        looped = True
                        break
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    dt = max(time.time() - t0, 1e-6)
    outcome = ("looped" if looped else "stopped" if stopped
               else "cut (length)" if finish_reason == "length" else "ok")
    applog.log(f"done: {n_tokens} tokens in {dt:.1f}s ({n_tokens / dt:.1f} tok/s) - {outcome}")

    info = {
        "truncated": finish_reason == "length",
        "stopped": stopped,
        "looped": looped,
        "trimmed": trimmed,
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
        _apply_thinking_tag(final_messages, model_name)
        _stream_and_report(llm, final_messages, meta, model_name)
    except Exception as e:
        applog.error(f"generation failed: {e}")
        runtime.window.evaluate_js(f"onError({json.dumps(str(e))})")
