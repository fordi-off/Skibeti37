"""Selve tekstgenereringen - kjører i bakgrunnstråd og strømmer tekstbiter
til frontend via window.evaluate_js, slik at UI-et aldri fryser mens
modellen jobber."""

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


def send_message(model_name, messages, chat_id=None):
    thread = threading.Thread(target=_generate, args=(model_name, messages, chat_id), daemon=True)
    thread.start()
    return {"started": True}


def continue_message(model_name, messages, chat_id=None):
    thread = threading.Thread(
        target=_generate_continuation, args=(model_name, messages, chat_id), daemon=True
    )
    thread.start()
    return {"started": True}


def _stream_and_report(llm, final_messages, compressed, model_name):
    context_used = chats.count_tokens(llm, final_messages)
    context_max = config.load_config().get("context_window", config.DEFAULT_CONTEXT)
    max_tokens = 3000 if "DeepSeek" in model_name else 2000

    stream = llm.create_chat_completion(
        messages=final_messages, max_tokens=max_tokens, stream=True, **SAMPLING_PARAMS
    )

    finish_reason = None
    for chunk in stream:
        choice = chunk["choices"][0]
        delta = choice["delta"].get("content", "")
        if delta:
            runtime.window.evaluate_js(f"onChunk({json.dumps(delta)})")
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]

    info = {
        "truncated": finish_reason == "length",
        "compressed": compressed,
        "context_used": context_used,
        "context_max": context_max,
    }
    runtime.window.evaluate_js(f"onDone({json.dumps(info)})")


def _generate(model_name, messages, chat_id=None):
    try:
        llm = model_manager.ensure_only_model_loaded(model_name)
        final_messages, compressed = chats.build_context(chat_id, model_name, messages)
        _stream_and_report(llm, final_messages, compressed, model_name)
    except Exception as e:
        runtime.window.evaluate_js(f"onError({json.dumps(str(e))})")


def _generate_continuation(model_name, messages, chat_id=None):
    messages = list(messages)
    messages.append({
        "role": "user",
        "content": (
            "Fortsett svaret ditt nøyaktig der du slapp. Ikke gjenta det du allerede "
            "har skrevet, og ikke skriv noen innledning - fortsett rett på."
        )
    })
    try:
        llm = model_manager.ensure_only_model_loaded(model_name)
        final_messages, compressed = chats.build_context(chat_id, model_name, messages)
        _stream_and_report(llm, final_messages, compressed, model_name)
    except Exception as e:
        runtime.window.evaluate_js(f"onError({json.dumps(str(e))})")
