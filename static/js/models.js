// ---------------- Modellvalg ----------------

async function loadModels() {
  allModels = await window.pywebview.api.list_models();
  modelLabels = {};
  allModels.forEach(m => { modelLabels[m.id] = m.name; });

  pickerEl.innerHTML = "";
  allModels.forEach((m, i) => {
    const btn = document.createElement("button");
    btn.className = "model-btn" + (m.id === currentModel || (!currentModel && i === 0) ? " active" : "");
    btn.textContent = m.name;
    btn.dataset.model = m.id;
    btn.onclick = () => selectModel(m.id);
    pickerEl.appendChild(btn);
  });
  if (!currentModel && allModels.length > 0) currentModel = allModels[0].id;
}

async function selectModel(id) {
  currentModel = id;
  [...pickerEl.children].forEach(btn => btn.classList.toggle("active", btn.dataset.model === id));

  if (conversation.length > 1) {
    try {
      const info = await window.pywebview.api.estimate_context(
        currentChatId, currentModel, JSON.stringify(conversation)
      );
      if (info && typeof info.context_used === "number") {
        updateContextMeter(info.context_used, info.context_max, info.compressed);
      }
    } catch (err) { /* stille */ }
  }
}
