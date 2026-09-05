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

  if (!currentModel && allModels.length > 0) currentModel = allModels[0].id;
  if (currentModel) modelSelectEl.value = currentModel;
}

async function selectModel(id) {
  if (!id) return;
  currentModel = id;
  modelSelectEl.value = id;

  if (conversation.length > 1) {
    try {
      const info = await window.pywebview.api.estimate_context(
        currentChatId, currentModel, JSON.stringify(conversation)
      );
      if (info && typeof info.context_used === "number") {
        updateContextMeter(info.context_used, info.context_max, info.compressed);
      }
    } catch (err) { /* silent */ }
  }
}

modelSelectEl.addEventListener("change", (e) => selectModel(e.target.value));
