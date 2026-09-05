// ---------------- Documents ----------------

async function refreshDocList() {
  if (!currentChatId) {
    docListEl.innerHTML = `<div class="empty-hint">Denne samtalen har ingen dokumenter ennå. Last opp en fil eller velg fra biblioteket (samtalen lagres automatisk).</div>`;
    return;
  }

  const docs = await window.pywebview.api.list_documents(currentChatId);
  docListEl.innerHTML = "";

  if (docs.length === 0) {
    docListEl.innerHTML = `<div class="empty-hint">Ingen dokumenter i denne samtalen. Støtter .txt og .md.</div>`;
    return;
  }

  docs.forEach(doc => {
    const item = document.createElement("div");
    item.className = "doc-item";

    const row = document.createElement("div");
    row.className = "doc-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = doc.active;
    checkbox.title = "Aktiv i samtalen";
    checkbox.onchange = async () => { await window.pywebview.api.toggle_document(currentChatId, doc.id); };

    const nameSpan = document.createElement("span");
    nameSpan.className = "doc-name";
    nameSpan.textContent = doc.filename;
    nameSpan.title = doc.filename;

    const delBtn = document.createElement("button");
    delBtn.className = "doc-del";
    delBtn.textContent = "×";
    delBtn.title = "Fjern fra denne samtalen (slettes ikke fra biblioteket)";
    delBtn.onclick = async () => {
      await window.pywebview.api.detach_document(currentChatId, doc.id);
      refreshDocList();
    };

    row.appendChild(checkbox);
    row.appendChild(nameSpan);
    row.appendChild(delBtn);

    const summary = document.createElement("div");
    summary.className = "doc-summary";
    summary.textContent = doc.summary;
    summary.title = doc.summary;

    item.appendChild(row);
    item.appendChild(summary);
    docListEl.appendChild(item);
  });
}

document.getElementById("add-doc-btn").onclick = async () => {
  const chatId = await ensureChatExists();
  const addDocBtn = document.getElementById("add-doc-btn");
  addDocBtn.disabled = true;
  inputEl.disabled = true;
  sendBtn.disabled = true;

  try {
    const result = await window.pywebview.api.add_document(chatId);
    if (result && !result.cancelled) {
      refreshDocList();
    } else if (result && result.error) {
      docStatusEl.textContent = result.error;
    }
  } finally {
    addDocBtn.disabled = false;
    inputEl.disabled = false;
    sendBtn.disabled = isGenerating;
    statusEl.textContent = "";
  }
};

// Called from Python while the document is being summarised
function onDocStatus(text) {
  docStatusEl.textContent = text || "";
  statusEl.textContent = text || "";
}

// --- Library picker ---

const libraryPanelEl = document.getElementById("doc-library-panel");
const libraryListEl = document.getElementById("doc-library-list");

document.getElementById("browse-doc-btn").onclick = async () => {
  await ensureChatExists();
  const docs = await window.pywebview.api.list_available_documents(currentChatId);
  libraryListEl.innerHTML = "";

  if (docs.length === 0) {
    libraryListEl.innerHTML = `<div class="empty-hint">Ingen andre dokumenter i biblioteket.</div>`;
  } else {
    docs.forEach(doc => {
      const item = document.createElement("div");
      item.className = "lib-item";
      const nameSpan = document.createElement("span");
      nameSpan.className = "lib-name";
      nameSpan.textContent = doc.filename;
      nameSpan.title = doc.filename;
      const addBtn = document.createElement("button");
      addBtn.textContent = "Legg til";
      addBtn.onclick = async () => {
        await window.pywebview.api.attach_existing_document(currentChatId, doc.id);
        libraryPanelEl.classList.add("hidden");
        refreshDocList();
      };
      item.appendChild(nameSpan);
      item.appendChild(addBtn);
      libraryListEl.appendChild(item);
    });
  }

  libraryPanelEl.classList.remove("hidden");
};

document.getElementById("close-library-btn").onclick = () => {
  libraryPanelEl.classList.add("hidden");
};
