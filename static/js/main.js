// ==================== Startup ====================

async function startupLoad() {
  await loadModels();
  await refreshChatList();
  await refreshDocList();
  await refreshSkillList(true);
}

window.addEventListener("pywebviewready", async () => {
  const { needs_setup } = await window.pywebview.api.setup_status();
  if (needs_setup) {
    renderSetupPanel();          // shows in the chat area until the base models are downloaded
  } else {
    await startupLoad();
  }
});
