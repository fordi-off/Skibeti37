// ==================== Startup ====================

logStatus("frontend booted - waiting for python bridge");

async function startupLoad() {
  const t0 = performance.now();

  await loadModels();
  logStatus(`models loaded (${allModels.length})`);

  await refreshChatList();
  logStatus(`chats loaded (${chatListEl.querySelectorAll(".chat-item").length})`);

  await refreshDocList();
  logStatus(`documents loaded (${docListEl.querySelectorAll(".doc-item").length})`);

  await loadCommands(true);
  logStatus(`commands loaded (${allCommands.length})`);

  logStatus(`ready (${Math.round(performance.now() - t0)} ms)`);
}

window.addEventListener("pywebviewready", async () => {
  logStatus("bridge ready");
  const { needs_setup } = await window.pywebview.api.setup_status();
  if (needs_setup) {
    logStatus("base models missing - showing setup");
    renderSetupPanel();          // shows in the chat area until the base models are downloaded
  } else {
    await startupLoad();
  }
});
