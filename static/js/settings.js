// ==================== Settings modal ====================

const settingsOverlayEl = document.getElementById("settings-overlay");

document.getElementById("settings-btn").onclick = () => {
  settingsOverlayEl.classList.remove("hidden");
  refreshSettingsModelList();
  refreshSettingsDocList();
  refreshSettingsSkillList(true);
  refreshSettingsPerformance();
};
document.getElementById("settings-close-btn").onclick = () => {
  settingsOverlayEl.classList.add("hidden");
};
settingsOverlayEl.addEventListener("click", (e) => {
  if (e.target === settingsOverlayEl) settingsOverlayEl.classList.add("hidden");
});

document.querySelectorAll(".settings-tab").forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll(".settings-tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".settings-pane").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("pane-" + tab.dataset.tab).classList.add("active");
  };
});

// --- Models tab ---

async function refreshSettingsModelList() {
  const models = await window.pywebview.api.list_all_models_settings();
  const container = document.getElementById("settings-model-list");
  container.innerHTML = "";

  if (models.length === 0) {
    container.innerHTML = `<div class="empty-hint">Ingen .gguf-filer funnet i models/-mappen.</div>`;
    return;
  }

  models.forEach(model => {
    const row = document.createElement("div");
    row.className = "settings-row";

    const activeToggle = document.createElement("label");
    activeToggle.className = "skill-switch";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = model.active;
    const track = document.createElement("span");
    track.className = "skill-switch-track";
    activeToggle.appendChild(checkbox);
    activeToggle.appendChild(track);

    const nameWrap = document.createElement("div");
    nameWrap.style.flex = "1";
    nameWrap.style.minWidth = "0";
    const nameInput = document.createElement("input");
    nameInput.className = "row-name-input";
    nameInput.value = model.display_name;
    const filenameLabel = document.createElement("span");
    filenameLabel.className = "row-filename";
    filenameLabel.textContent = model.filename;
    nameWrap.appendChild(nameInput);
    nameWrap.appendChild(filenameLabel);

    const deviceSelect = document.createElement("select");
    ["cpu", "gpu"].forEach(opt => {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt.toUpperCase();
      if (opt === model.device) o.selected = true;
      deviceSelect.appendChild(o);
    });

    const save = async () => {
      await window.pywebview.api.update_model_settings(
        model.filename, nameInput.value.trim() || model.filename, checkbox.checked, deviceSelect.value
      );
      await loadModels();
    };

    checkbox.onchange = save;
    deviceSelect.onchange = save;
    nameInput.onblur = save;
    nameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") nameInput.blur(); });

    row.appendChild(activeToggle);
    row.appendChild(nameWrap);
    row.appendChild(deviceSelect);
    container.appendChild(row);
  });
}

// --- Documents tab ---

const docPreviewOverlayEl = document.getElementById("doc-preview-overlay");

async function refreshSettingsDocList() {
  const docs = await window.pywebview.api.list_all_documents_settings();
  const container = document.getElementById("settings-doc-list");
  container.innerHTML = "";

  if (docs.length === 0) {
    container.innerHTML = `<div class="empty-hint">Ingen dokumenter i biblioteket ennå.</div>`;
    return;
  }

  docs.forEach(doc => {
    const row = document.createElement("div");
    row.className = "settings-row";

    const nameSpan = document.createElement("span");
    nameSpan.style.flex = "1";
    nameSpan.style.fontSize = "13.5px";
    nameSpan.style.overflow = "hidden";
    nameSpan.style.textOverflow = "ellipsis";
    nameSpan.style.whiteSpace = "nowrap";
    nameSpan.textContent = doc.filename;
    nameSpan.title = doc.filename;

    const openBtn = document.createElement("button");
    openBtn.className = "settings-small-btn";
    openBtn.textContent = "Åpne";
    openBtn.onclick = async () => {
      const preview = await window.pywebview.api.preview_document(doc.id);
      if (!preview) return;
      document.getElementById("doc-preview-title").textContent = preview.filename;
      document.getElementById("doc-preview-summary").textContent = preview.summary;
      document.getElementById("doc-preview-fulltext").textContent = preview.full_text;
      docPreviewOverlayEl.classList.remove("hidden");
    };

    const delBtn = document.createElement("button");
    delBtn.className = "settings-small-btn danger";
    delBtn.textContent = "Slett";
    delBtn.onclick = async () => {
      await window.pywebview.api.delete_document_entirely(doc.id);
      refreshSettingsDocList();
      refreshDocList();
    };

    row.appendChild(nameSpan);
    row.appendChild(openBtn);
    row.appendChild(delBtn);
    container.appendChild(row);
  });
}

document.getElementById("doc-preview-close-btn").onclick = () => {
  docPreviewOverlayEl.classList.add("hidden");
};
docPreviewOverlayEl.addEventListener("click", (e) => {
  if (e.target === docPreviewOverlayEl) docPreviewOverlayEl.classList.add("hidden");
});

// --- Skills tab ---

let _lastSettingsSkillsJson = null;

async function refreshSettingsSkillList(force) {
  const skills = await window.pywebview.api.list_skills();
  const json = JSON.stringify(skills);
  if (!force && json === _lastSettingsSkillsJson) return;
  _lastSettingsSkillsJson = json;

  const container = document.getElementById("settings-skill-list");
  container.innerHTML = "";

  if (skills.length === 0) {
    container.innerHTML = `<div class="empty-hint">Ingen skills ennå.</div>`;
    return;
  }

  skills.forEach(skill => {
    const row = document.createElement("div");
    row.className = "settings-row";

    const nameSpan = document.createElement("span");
    nameSpan.style.flex = "1";
    nameSpan.style.fontSize = "13.5px";
    nameSpan.textContent = skill.name;

    const delBtn = document.createElement("button");
    delBtn.className = "settings-small-btn danger";
    delBtn.textContent = "Slett";
    delBtn.onclick = async () => {
      await window.pywebview.api.delete_skill(skill.id);
      refreshSettingsSkillList(true);
      refreshSkillList(true);
    };

    row.appendChild(nameSpan);
    row.appendChild(delBtn);
    container.appendChild(row);
  });
}

document.getElementById("new-skill-save-btn").onclick = async () => {
  const name = document.getElementById("new-skill-name").value.trim();
  const content = document.getElementById("new-skill-content").value.trim();
  if (!name || !content) return;
  await window.pywebview.api.add_skill(name, content);
  document.getElementById("new-skill-name").value = "";
  document.getElementById("new-skill-content").value = "";
  refreshSettingsSkillList(true);
  refreshSkillList(true);
};

// --- Performance tab (context window + threads) ---

let contextSteps = [4096, 8192, 16384, 32768, 65536, 131072];

async function refreshSettingsPerformance() {
  const overview = await window.pywebview.api.get_settings_overview();
  contextSteps = overview.context_steps;

  const contextSlider = document.getElementById("context-slider");
  contextSlider.max = contextSteps.length - 1;
  const currentIndex = contextSteps.indexOf(overview.context_window);
  contextSlider.value = currentIndex >= 0 ? currentIndex : 2;
  document.getElementById("context-slider-value").textContent = overview.context_window.toLocaleString() + " tokens";

  const threadsSlider = document.getElementById("threads-slider");
  threadsSlider.value = overview.n_threads;
  document.getElementById("threads-slider-value").textContent = overview.n_threads + " tråder";
}

document.getElementById("context-slider").addEventListener("input", (e) => {
  const value = contextSteps[parseInt(e.target.value)];
  document.getElementById("context-slider-value").textContent = value.toLocaleString() + " tokens";
});
document.getElementById("context-slider").addEventListener("change", async (e) => {
  const value = contextSteps[parseInt(e.target.value)];
  await window.pywebview.api.set_context_window(value);
});

document.getElementById("threads-slider").addEventListener("input", (e) => {
  document.getElementById("threads-slider-value").textContent = e.target.value + " tråder";
});
document.getElementById("threads-slider").addEventListener("change", async (e) => {
  await window.pywebview.api.set_thread_count(parseInt(e.target.value));
});
