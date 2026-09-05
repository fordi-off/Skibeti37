// ==================== Oppstart ====================

window.addEventListener("pywebviewready", async () => {
  await loadModels();
  await refreshChatList();
  await refreshDocList();
  await refreshSkillList();
});
