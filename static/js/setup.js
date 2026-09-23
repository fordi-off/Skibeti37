// ---------------- Model downloads (Settings -> Modeller) ----------------
// The embedder + small utility model are always included automatically
// (downloader.AUTO_IDS) whenever anything is downloaded, so they aren't
// shown as choices here. This panel lets the user tick any number of
// "main" models to fetch and shows progress inline inside the Settings
// modal - it no longer takes over the whole chat area, and a download can
// keep running in the background if the modal is closed (onDownloadState
// just no-ops until the panel is reopened, which resyncs from
// download_state()).

let dlCatalog = [];
let dlPlannedIds = [];
let dlBusy = false;

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

function modelCheckListHTML() {
  const opts = dlCatalog.filter(e => e.role === "main" && !e.installed);
  if (opts.length === 0) {
    return `<div class="empty-hint">Alle hovedmodellene i katalogen er allerede installert.</div>`;
  }
  return opts.map(e => `
    <label class="model-choice-item">
      <input type="checkbox" name="dl-main" value="${e.id}">
      <div class="model-choice-body">
        <div class="model-choice-title">${e.display_name} <span class="model-choice-size">${e.size_label}</span></div>
        <div class="model-choice-desc">${e.note} · ${fmtSize(e.size_bytes)}</div>
      </div>
    </label>`).join("");
}

// Shows the checklist, or - if a download is already running (e.g. the
// modal was closed and reopened mid-download) - resyncs onto its progress.
async function renderDownloadArea() {
  const area = document.getElementById("settings-download-area");
  if (!area) return;
  dlCatalog = await window.pywebview.api.model_catalog();

  const state = await window.pywebview.api.download_state();
  if (state && state.phase === "running") {
    dlBusy = true;
    dlPlannedIds = [...state.queue, ...state.completed, ...state.failed.map(f => f.id)];
    renderDownloadProgress(state);
    return;
  }
  dlBusy = false;

  area.innerHTML = `
    <div class="settings-note">Dokumentmodellen og en liten bakgrunnsmodell (Qwen3.5 2b) lastes ned
       automatisk sammen med det du velger under, hvis de ikke finnes fra før.</div>
    <div class="model-choice-list" id="dl-check-list">${modelCheckListHTML()}</div>
    <div class="setup-panel-total" id="dl-total"></div>
    <div class="setup-panel-btns">
      <button id="dl-go" class="setup-primary">Last ned valgte</button>
    </div>`;

  const listEl = document.getElementById("dl-check-list");
  const totalEl = document.getElementById("dl-total");
  const goBtn = document.getElementById("dl-go");
  const checked = () => [...listEl.querySelectorAll("input:checked")].map(i => i.value);

  const recalcTotal = () => {
    const ids = ["embed", "utility", ...checked()];
    const bytes = ids.reduce((s, id) => {
      const e = dlCatalog.find(x => x.id === id);
      return s + (e && !e.installed ? (e.size_bytes || 0) : 0);
    }, 0);
    totalEl.textContent = `Å laste ned: ${fmtSize(bytes) === "0 MB" ? "ingenting nytt" : fmtSize(bytes)}`;
    goBtn.disabled = checked().length === 0;
  };
  listEl.addEventListener("change", (e) => {
    const item = e.target.closest(".model-choice-item");
    if (item) item.classList.toggle("selected", e.target.checked);
    recalcTotal();
  });
  recalcTotal();

  goBtn.onclick = () => startDownload(checked());
}

async function startDownload(chosenIds) {
  dlPlannedIds = ["embed", "utility", ...chosenIds]
    .filter((id, i, a) => a.indexOf(id) === i)
    .filter(id => {
      const e = dlCatalog.find(x => x.id === id);
      return e && !e.installed;
    });

  dlBusy = true;
  if (!dlPlannedIds.length) { await afterDownload(); return; }

  renderDownloadProgress({ phase: "running", queue: dlPlannedIds.slice(), current: null, completed: [], failed: [] });
  await window.pywebview.api.start_model_downloads(JSON.stringify(chosenIds));
}

// Called from Python as the queue advances. No-ops quietly if the Modeller
// pane (or Settings itself) isn't open right now - the download keeps
// running server-side either way, and reopening resyncs via download_state().
function onDownloadState(state) {
  if (!dlBusy) return;
  renderDownloadProgress(state);
}

function renderDownloadProgress(state) {
  const area = document.getElementById("settings-download-area");
  if (!area) return;

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
    const e = dlCatalog.find(x => x.id === id) || { display_name: id };
    const failed = state.failed.find(f => f.id === id);
    let m = "·", cls = "queued";
    if (state.completed.includes(id)) { m = "✓"; cls = "ok"; }
    else if (failed) { m = "✗"; cls = "fail"; }
    else if (cur && cur.id === id) { m = "▶"; cls = "cur"; }
    return `<div class="setup-list-row ${cls}"><span class="m">${m}</span><span>${e.display_name}</span>${failed ? `<span class="setup-list-err">${failed.error}</span>` : ""}</div>`;
  }).join("");

  area.innerHTML = `
    <div class="setup-progress">
      <div class="setup-line">${terminal ? (state.phase === "done" ? "Ferdig ✓" : state.phase === "cancelled" ? "Avbrutt" : "Noe gikk galt") : "Laster ned…"}
        — ${finished} / ${total} filer${terminal ? " — " + phaseLabel(state.phase) : ""}</div>
      <div class="setup-bar"><div class="setup-bar-fill" style="width:${(frac * 100).toFixed(1)}%"></div></div>
      ${cur ? `
        <div class="setup-current-name">${cur.name}</div>
        <div class="setup-bar"><div class="setup-bar-fill" style="width:${cur.total ? (cur.downloaded / cur.total * 100).toFixed(1) : 0}%"></div></div>
        <div class="setup-line">${fmtSize(cur.downloaded)} / ${fmtSize(cur.total)}${cur.speed ? " · " + fmtSpeed(cur.speed) : ""}${(cur.speed && cur.total) ? " · " + fmtEta((cur.total - cur.downloaded) / cur.speed) : ""}</div>` : ""}
      <div class="setup-list">${listHTML}</div>
      <div class="setup-panel-btns">
        ${terminal
          ? `<button id="dl-back" class="setup-primary">Tilbake</button>`
          : `<button id="dl-cancel" class="confirm-danger-btn">Avbryt nedlasting</button>`}
      </div>
    </div>`;

  if (terminal) {
    document.getElementById("dl-back").onclick = afterDownload;
  } else {
    const c = document.getElementById("dl-cancel");
    c.onclick = () => { c.disabled = true; window.pywebview.api.cancel_model_downloads(); };
  }
}

async function afterDownload() {
  dlBusy = false;
  await loadModels();
  await refreshSettingsModelList();
  await refreshChatList();
  await refreshDocList();
  await loadCommands(true);
  await renderDownloadArea();
}

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "open-setup-btn") openModelDownloads();
});
