// ---------------- Model selection ----------------

async function loadModels() {
  allModels = await window.pywebview.api.list_models();
  modelLabels = {};
  allModels.forEach(m => { modelLabels[m.id] = m.name; });

  modelSelectEl.innerHTML = "";
  allModels.forEach(m => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.name;
    modelSelectEl.appendChild(opt);
  });

  const hasModels = allModels.length > 0;
  modelSelectEl.disabled = !hasModels;
  inputEl.disabled = !hasModels;
  sendBtn.disabled = !hasModels;

  if (!hasModels) {
    modelSelectEl.innerHTML = `<option>Ingen modeller</option>`;
    currentModel = null;
    chatEl.innerHTML = emptyStateHTML();
    return;
  }

  if (!currentModel || !allModels.some(m => m.id === currentModel)) {
    let last = null;
    try { last = await window.pywebview.api.get_last_model(); } catch (err) { /* silent */ }
    currentModel = allModels.some(m => m.id === last) ? last : allModels[0].id;
  }
  modelSelectEl.value = currentModel;
}

async function selectModel(id) {
  if (!id) return;
  currentModel = id;
  modelSelectEl.value = id;
  window.pywebview.api.set_last_model(id);   // fire and forget

  if (conversation.length > 1) {
    // estimate_context loads the model if it's cold, which blocks for a while.
    if (!isGenerating) statusEl.textContent = `laster ${modelLabels[id] || id}...`;
    try {
      const info = await window.pywebview.api.estimate_context(
        currentChatId, currentModel, JSON.stringify(conversation)
      );
      if (info && typeof info.context_used === "number") {
        updateContextMeter(info.context_used, info.context_max, info.compressed);
      }
    } catch (err) { /* silent */ }
    if (!isGenerating) statusEl.textContent = "";
  }
}

modelSelectEl.addEventListener("change", (e) => selectModel(e.target.value));
