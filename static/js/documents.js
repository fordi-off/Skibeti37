// ---------------- Documents ----------------

async function refreshDocList() {
  if (!currentChatId) {
    docListEl.innerHTML = `<div class="empty-hint">Denne samtalen har ingen dokumenter ennå. Trykk «+ Legg til» for å laste opp en fil eller hente en fra biblioteket (samtalen lagres automatisk).</div>`;
    return;
  }

  const docs = await window.pywebview.api.list_documents(currentChatId);
  docListEl.innerHTML = "";

  if (docs.length === 0) {
    docListEl.innerHTML = `<div class="empty-hint">Ingen dokumenter i denne samtalen. Trykk «+ Legg til». Støtter .txt og .md.</div>`;
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

// Called from Python while a document is being indexed / summarised.
function onDocStatus(text) {
  docStatusEl.textContent = text || "";
  statusEl.textContent = text || "";
}

// ---------------- Add-document dialog ----------------

const docAddOverlayEl = document.getElementById("doc-add-overlay");
const docAddLibraryEl = document.getElementById("doc-add-library");

function openDocAdd() {
  ensureChatExists().then(async () => {
    await renderDocAddLibrary();
    docAddOverlayEl.classList.remove("hidden");
  });
}

function closeDocAdd() {
  docAddOverlayEl.classList.add("hidden");
}

async function renderDocAddLibrary() {
  const docs = await window.pywebview.api.list_available_documents(currentChatId);
  docAddLibraryEl.innerHTML = "";

  if (docs.length === 0) {
    docAddLibraryEl.innerHTML = `<div class="empty-hint">Biblioteket er tomt, eller alt ligger allerede i denne samtalen.</div>`;
    return;
  }

  docs.forEach(doc => {
    const row = document.createElement("button");
    row.className = "doc-add-lib-row";
    row.innerHTML = `<span class="doc-add-lib-name"></span><span class="doc-add-lib-sub"></span>`;
    row.querySelector(".doc-add-lib-name").textContent = doc.filename;
    row.querySelector(".doc-add-lib-sub").textContent = doc.summary || "";
    row.onclick = async () => {
      row.disabled = true;
      await window.pywebview.api.attach_existing_document(currentChatId, doc.id);
      closeDocAdd();
      refreshDocList();
    };
    docAddLibraryEl.appendChild(row);
  });
}

async function uploadNewDocument() {
  const chatId = await ensureChatExists();
  closeDocAdd();

  const addDocBtn = document.getElementById("add-doc-btn");
  addDocBtn.disabled = true;
  inputEl.disabled = true;
  sendBtn.disabled = true;

  try {
    const result = await window.pywebview.api.add_document(chatId);
    if (result && !result.cancelled) {
      refreshDocList();
      if (result.notice) { docStatusEl.textContent = result.notice; logStatus(`document: ${result.notice}`); }
    } else if (result && result.error) {
      docStatusEl.textContent = result.error;
    }
  } finally {
    addDocBtn.disabled = false;
    inputEl.disabled = false;
    sendBtn.disabled = isGenerating;
    statusEl.textContent = "";
  }
}

document.getElementById("add-doc-btn").onclick = openDocAdd;
document.getElementById("doc-add-upload-btn").onclick = uploadNewDocument;
document.getElementById("doc-add-close-btn").onclick = closeDocAdd;
docAddOverlayEl.addEventListener("click", (e) => {
  if (e.target === docAddOverlayEl) closeDocAdd();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !docAddOverlayEl.classList.contains("hidden")) closeDocAdd();
});
