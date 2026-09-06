// ---------------- First-run model setup (inline in the chat area) ----------------
// The embedder + Qwen 1.5B always download. The user picks a size for the
// main and reasoning models, or skips and adds .gguf files themselves.
// Everything renders inside #chat; while a download runs the composer is
// disabled (there's no model yet anyway).

let setupCatalog = [];
let dlPlannedIds = [];
let setupBusy = false;

function fmtSize(bytes) {
  if (!bytes) return "?";
  return bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + " GB" : Math.round(bytes / 1e6) + " MB";
}
function fmtSpeed(bps) {
  if (!bps || bps < 500) return "";
  return bps >= 1e6 ? (bps / 1e6).toFixed(1) + " MB/s" : Math.round(bps / 1e3) + " kB/s";
}
function fmtEta(sec) {
  if (!sec || !isFinite(sec) || sec < 0) return "";
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m ? `${m} min igjen` : `${s} s igjen`;
}
function phaseLabel(p) {
  return { done: "ferdig", error: "med feil", cancelled: "avbrutt" }[p] || "";
}

async function renderSetupPanel() {
  if (setupBusy) return;
  setupCatalog = await window.pywebview.api.model_catalog();

  const opts = (role) => setupCatalog
    .filter(e => e.role === role)
    .map(e => `<option value="${e.id}" ${e.default ? "selected" : ""}${e.installed ? " disabled" : ""}>${e.size_label} — ${e.note}${e.installed ? " (installert)" : " · " + fmtSize(e.size_bytes)}</option>`)
    .join("");

  chatEl.innerHTML = `
    <div class="setup-panel">
      <h2>Kom i gang</h2>
      <p>Skibeti37 laster ned dokumentmodellen og en liten chatmodell (Qwen 1.5B) uansett.
         Velg hvor store de to hovedmodellene skal være, eller hopp over og legg til egne
         <code>.gguf</code>-filer i <code>models/</code>.</p>

      <label>Hovedmodell (vanlig chat)
        <select id="setup-main">${opts("main")}<option value="">Ingen — jeg legger til selv</option></select>
      </label>
      <label>Resonneringsmodell (matte / logikk)
        <select id="setup-reason">${opts("reasoning")}<option value="">Ingen — jeg legger til selv</option></select>
      </label>

      <div class="setup-panel-total" id="setup-total"></div>
      <div class="setup-panel-btns">
        <button id="setup-skip">Hopp over</button>
        <button id="setup-go" class="setup-primary">Last ned</button>
      </div>
    </div>`;

  const mainSel = document.getElementById("setup-main");
  const reasonSel = document.getElementById("setup-reason");
  const totalEl = document.getElementById("setup-total");
  const chosen = () => [mainSel.value, reasonSel.value].filter(Boolean);

  const recalcTotal = () => {
    const ids = ["embed", "utility", ...chosen()];
    const bytes = ids.reduce((s, id) => {
      const e = setupCatalog.find(x => x.id === id);
      return s + (e && !e.installed ? (e.size_bytes || 0) : 0);
    }, 0);
    totalEl.textContent = `Å laste ned: ${fmtSize(bytes) === "0 MB" ? "ingenting nytt" : fmtSize(bytes)}`;
  };
  [mainSel, reasonSel].forEach(s => s.addEventListener("change", recalcTotal));
  recalcTotal();

  document.getElementById("setup-go").onclick = () => startSetupDownload(chosen());
  document.getElementById("setup-skip").onclick = () => startSetupDownload([]);
}

async function startSetupDownload(chosenIds) {
  dlPlannedIds = ["embed", "utility", ...chosenIds]
    .filter((id, i, a) => a.indexOf(id) === i)
    .filter(id => {
      const e = setupCatalog.find(x => x.id === id);
      return e && !e.installed;
    });

  setupBusy = true;
  setSetupUiLocked(true);

  if (!dlPlannedIds.length) { await finishSetup(); return; }

  renderProgress({ phase: "running", queue: dlPlannedIds.slice(), current: null, completed: [], failed: [] });
  await window.pywebview.api.start_model_downloads(JSON.stringify(chosenIds));
}

// Called from Python as the queue advances.
function onDownloadState(state) {
  renderProgress(state);
}

function renderProgress(state) {
  const total = dlPlannedIds.length || 1;
  const finished = state.completed.length + state.failed.length;
  let frac = finished / total;
  if (state.current && state.current.total) {
    frac += (state.current.downloaded / state.current.total) / total;
  }
  frac = Math.max(0, Math.min(1, frac));

  const cur = state.current;
  const terminal = ["done", "error", "cancelled"].includes(state.phase);

  const listHTML = dlPlannedIds.map(id => {
    const e = setupCatalog.find(x => x.id === id) || { display_name: id };
    const failed = state.failed.find(f => f.id === id);
    let m = "·", cls = "queued";
    if (state.completed.includes(id)) { m = "✓"; cls = "ok"; }
    else if (failed) { m = "✗"; cls = "fail"; }
    else if (cur && cur.id === id) { m = "▶"; cls = "cur"; }
    return `<div class="setup-list-row ${cls}"><span class="m">${m}</span><span>${e.display_name}</span>${failed ? `<span class="setup-list-err">${failed.error}</span>` : ""}</div>`;
  }).join("");

  chatEl.innerHTML = `
    <div class="setup-panel">
      <h2>${terminal ? (state.phase === "done" ? "Ferdig ✓" : state.phase === "cancelled" ? "Avbrutt" : "Noe gikk galt") : "Laster ned…"}</h2>
      <div class="setup-bar"><div class="setup-bar-fill" style="width:${(frac * 100).toFixed(1)}%"></div></div>
      <div class="setup-line">${finished} / ${total} filer${terminal ? " — " + phaseLabel(state.phase) : ""}</div>
      ${cur ? `
        <div class="setup-current-name">${cur.name}</div>
        <div class="setup-bar"><div class="setup-bar-fill" style="width:${cur.total ? (cur.downloaded / cur.total * 100).toFixed(1) : 0}%"></div></div>
        <div class="setup-line">${fmtSize(cur.downloaded)} / ${fmtSize(cur.total)}${cur.speed ? " · " + fmtSpeed(cur.speed) : ""}${(cur.speed && cur.total) ? " · " + fmtEta((cur.total - cur.downloaded) / cur.speed) : ""}</div>` : ""}
      <div class="setup-list">${listHTML}</div>
      <div class="setup-panel-btns">
        ${terminal
          ? `<button id="setup-again">Tilbake til valg</button><button id="setup-continue" class="setup-primary">Fortsett til appen</button>`
          : `<button id="setup-cancel" class="confirm-danger-btn">Avbryt nedlasting</button>`}
      </div>
    </div>`;

  if (terminal) {
    document.getElementById("setup-continue").onclick = finishSetup;
    document.getElementById("setup-again").onclick = () => { setupBusy = false; renderSetupPanel(); };
  } else {
    const c = document.getElementById("setup-cancel");
    c.onclick = () => { c.disabled = true; window.pywebview.api.cancel_model_downloads(); };
  }
}

async function finishSetup() {
  setupBusy = false;
  setSetupUiLocked(false);
  await loadModels();
  await refreshChatList();
  await refreshDocList();
  await refreshSkillList(true);
  if (conversation.length > 1) renderConversation();
  else chatEl.innerHTML = emptyStateHTML();
}

function setSetupUiLocked(locked) {
  document.getElementById("settings-btn").style.pointerEvents = locked ? "none" : "";
  document.getElementById("settings-btn").style.opacity = locked ? "0.4" : "";
  modelSelectEl.disabled = locked || allModels.length === 0;
}

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "open-setup-btn") renderSetupPanel();
});
