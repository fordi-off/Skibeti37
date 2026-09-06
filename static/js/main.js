// ==================== Startup ====================

async function startupLoad() {
  await loadModels();
  await refreshChatList();
  await refreshDocList();
  await refreshSkillList(true);
}

window.addEventListener("pywebviewready", async () => {
  const status = await window.pywebview.api.setup_status();
  if (status.missing_slots.length) {
    showSetup({ firstRun: true, status });   // blocks the app until models are in place
  } else {
    await startupLoad();
  }
});
