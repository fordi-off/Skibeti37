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
  await startupLoad();   // no models yet -> loadModels() shows the empty state with a download link
});
