// Runs before every other app script. If this page is open inside the real
// pywebview webview, window.pywebview.api already exists and this file does
// nothing. Otherwise it's running in the browser+WASM fallback mode that
// app.py switches to when pywebview's/llama-cpp-python's native DLLs are
// blocked (see fallback_server.py) - this builds a drop-in window.pywebview.api
// with the exact same method names and shapes, so chat.js/documents.js/
// settings.js/skills.js/setup.js/models.js/main.js need zero changes to work
// in either mode.
(function () {
  if (window.pywebview && window.pywebview.api) return;

  async function call(name, args) {
    const res = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ args }),
    });
    const data = await res.json();
    if (data && data.error) throw new Error(data.error);
    return data.result;
  }

  // Everything that's just storage/settings/skills/downloads goes straight
  // through to Python over HTTP - none of it touches llama_cpp or numpy.
  const PASSTHROUGH_METHODS = [
    "model_catalog", "start_model_downloads", "cancel_model_downloads", "download_state",
    "list_models", "list_all_models_settings", "update_model_settings", "delete_model",
    "get_last_model", "set_last_model", "get_settings_overview", "set_context_window",
    "set_thread_count", "reset_settings", "list_chats", "load_chat", "save_chat",
    "rename_chat", "delete_chat", "list_documents", "list_available_documents",
    "list_all_documents_settings", "attach_existing_document", "detach_document",
    "toggle_document", "delete_document_entirely", "preview_document", "list_commands",
    "list_skills", "add_skill", "delete_skill", "command_bodies", "doc_chunks_for_query",
    "save_document_from_data",
  ];

  const api = {};
  PASSTHROUGH_METHODS.forEach((name) => { api[name] = (...args) => call(name, args); });

  // Inference, embeddings and document indexing run client-side via WASM
  // (static/js/wasm-engine.js), loaded lazily so a normal pywebview install
  // never has to fetch wllama's multi-megabyte runtime at all.
  let enginePromise = null;
  function engine() {
    if (!enginePromise) enginePromise = import("./wasm-engine.js");
    return enginePromise;
  }

  api.send_message = async (modelName, messagesJson, chatId) => {
    (await engine()).generate(modelName, JSON.parse(messagesJson), chatId, { continuation: false });
    return { started: true };
  };
  api.continue_message = async (modelName, messagesJson, chatId) => {
    (await engine()).generate(modelName, JSON.parse(messagesJson), chatId, { continuation: true });
    return { started: true };
  };
  api.stop_generation = async () => {
    (await engine()).stop();
    return { stopping: true };
  };
  api.estimate_context = async (chatId, modelName, messagesJson) =>
    (await engine()).estimateContext(chatId, modelName, JSON.parse(messagesJson));
  api.add_document = async (chatId) => (await engine()).addDocument(chatId);

  window.pywebview = { api };

  // The real pywebview pushes download progress into onDownloadState() via
  // window.evaluate_js; there's no such push channel to a plain browser tab,
  // so poll instead while a download is actually running. setup.js itself
  // needs no changes - onDownloadState is already a plain global function.
  setInterval(async () => {
    try {
      const state = await api.download_state();
      if (state && state.phase === "running" && typeof window.onDownloadState === "function") {
        window.onDownloadState(state);
      }
    } catch (err) { /* ignore - next tick tries again */ }
  }, 700);

  window.addEventListener("DOMContentLoaded", () => {
    try { logStatus("running in browser-compatibility mode (pywebview/llama.cpp unavailable on this machine)"); }
    catch (err) { console.log("Skibeti37: running in browser-compatibility mode"); }
    window.dispatchEvent(new Event("pywebviewready"));
  });
})();
