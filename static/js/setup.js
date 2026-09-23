// ---------------- First-run model setup (inline in the chat area) ----------------
// The embedder + Qwen 1.5B always download. The user picks a size for the
// main model as a list of cards, or skips and adds .gguf files themselves.
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

// Builds one radio-per-row "card" list for a catalog role, plus a trailing
// "Ingen" card. Selecting a row is a whole-row click, not just the tiny radio.
function modelChoiceListHTML(role) {
  const opts = setupCatalog.filter(e => e.role === role);
  const rows = opts.map(e => ({
    value: e.id,
    checked: !!e.default,
    disabled: !!e.installed,
    title: `${e.display_name} <span class="model-choice-size">${e.size_label}</span>`,
    desc: `${e.note}${e.installed ? " · installert" : " · " + fmtSize(e.size_bytes)}`,
  }));
  rows.push({
    value: "", checked: !opts.some(e => e.default), disabled: false,
    title: "Ingen", desc: "Jeg legger til en .gguf-fil selv i models/",
  });

  return rows.map(r => `
    <label class="model-choice-item${r.checked ? " selected" : ""}${r.disabled ? " disabled" : ""}">
      <input type="radio" name="setup-main" value="${r.value}" ${r.checked ? "checked" : ""} ${r.disabled ? "disabled" : ""}>
      <div class="model-choice-body">
        <div class="model-choice-title">${r.title}</div>
        <div class="model-choice-desc">${r.desc}</div>
      </div>
    </label>`).join("");
}

async function renderSetupPanel() {
  if (setupBusy) return;
  setupCatalog = await window.pywebview.api.model_catalog();

  chatEl.innerHTML = `
    <div class="setup-panel">
      <h2>Kom i gang</h2>
      <p>Skibeti37 laster ned dokumentmodellen og en liten chatmodell (Qwen 1.5B) uansett.
         Velg størrelse på hovedmodellen, eller hopp over og legg til egne
         <code>.gguf</code>-filer i <code>models/</code>.</p>

      <label>Hovedmodell (vanlig chat)</label>
      <div class="model-choice-list" id="setup-main-list">${modelChoiceListHTML("main")}</div>

      <div class="setup-panel-total" id="setup-total"></div>
      <div class="setup-panel-btns">
        <button id="setup-skip">Hopp over</button>
        <button id="setup-go" class="setup-primary">Last ned</button>
      </div>
    </div>`;

  const listEl = document.getElementById("setup-main-list");
  const totalEl = document.getElementById("setup-total");
  const chosen = () => {
    const checked = listEl.querySelector("input:checked");
    return checked && checked.value ? [checked.value] : [];
  };

  const recalcTotal = () => {
    const ids = ["embed", "utility", ...chosen()];
    const bytes = ids.reduce((s, id) => {
      const e = setupCatalog.find(x => x.id === id);
      return s + (e && !e.installed ? (e.size_bytes || 0) : 0);
    }, 0);
    totalEl.textContent = `Å laste ned: ${fmtSize(bytes) === "0 MB" ? "ingenting nytt" : fmtSize(bytes)}`;
  };
  listEl.addEventListener("change", () => {
    listEl.querySelectorAll(".model-choice-item").forEach(item => {
      item.classList.toggle("selected", item.querySelector("input").checked);
    });
    recalcTotal();
  });
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
  logStatus("setup finished - reloading");
  await loadModels();
  logStatus(`models loaded (${allModels.length})`);
  await refreshChatList();
  await refreshDocList();
  await loadCommands(true);
  logStatus(`commands loaded (${allCommands.length})`);
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
