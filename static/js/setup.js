// ---------------- Model downloader ----------------
// First-run screen + "download more models" dialog. While it's shown the
// rest of the app is covered and unusable; during an active download there's
// no way out until it finishes, is cancelled, or errors.

const setupOverlayEl = document.getElementById("setup-overlay");
const setupChooseEl = document.getElementById("setup-choose");
const setupProgressEl = document.getElementById("setup-progress");
const setupGroupsEl = document.getElementById("setup-groups");
const setupIntroEl = document.getElementById("setup-intro");
const setupTotalEl = document.getElementById("setup-total");
const setupTitleEl = document.getElementById("setup-title");
const setupDownloadBtn = document.getElementById("setup-download-btn");
const setupCancelBtn = document.getElementById("setup-cancel-btn");
const setupProceedBtn = document.getElementById("setup-proceed-btn");
const setupCloseBtn = document.getElementById("setup-close-btn");

let setupCatalog = [];
let setupFirstRun = false;
let setupCanProceed = false;
let dlPlannedIds = [];

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
  return m ? `${m} min ${s} s` : `${s} s`;
}
function phaseLabel(p) {
  return { done: "ferdig", error: "med feil", cancelled: "avbrutt", running: "laster" }[p] || p;
}

async function showSetup(opts) {
  opts = opts || {};
  setupFirstRun = !!opts.firstRun;
  setupCatalog = await window.pywebview.api.model_catalog();
  const status = opts.status || await window.pywebview.api.setup_status();
  setupCanProceed = !!status.can_use_app;

  setupChooseEl.classList.remove("hidden");
  setupProgressEl.classList.add("hidden");
  setupCancelBtn.classList.add("hidden");
  setupDownloadBtn.classList.remove("hidden");
  setupDownloadBtn.disabled = false;
  setupDownloadBtn.onclick = startDownloads;
  setupCloseBtn.classList.toggle("hidden", setupFirstRun);
  setupProceedBtn.classList.toggle("hidden", !(setupFirstRun && setupCanProceed));
  setupProceedBtn.textContent = "Fortsett til appen";

  setupTitleEl.textContent = setupFirstRun ? "Velkommen — last ned modeller" : "Last ned modeller";
  setupIntroEl.textContent = setupFirstRun
    ? "Skibeti37 trenger noen modellfiler for å virke. De to øverste er nødvendige. For de to store modellene kan du velge kvalitet. Alt hentes fra Hugging Face."
    : "Legg til flere modeller. Allerede installerte er merket.";

  renderGroups();
  setupOverlayEl.classList.remove("hidden");
}

function rowHTML(entry, controlHTML) {
  const inst = entry.installed;
  return `<label class="setup-row${inst ? " installed" : ""}">
    <span class="setup-row-ctrl">${inst ? "✓" : controlHTML}</span>
    <span class="setup-row-main">
      <span class="setup-row-name">${entry.name}</span>
      ${entry.note ? `<span class="setup-row-note">${entry.note}</span>` : ""}
    </span>
    <span class="setup-row-size">${inst ? "Installert" : fmtSize(entry.size_bytes)}</span>
  </label>`;
}

function renderGroups() {
  const byRole = (r) => setupCatalog.filter(e => e.role === r);
  let html = "";

  const required = [...byRole("embed"), ...byRole("utility")];
  html += `<div class="setup-group"><h3>Nødvendige</h3>` + required.map(e =>
    rowHTML(e, `<input type="checkbox" data-model-id="${e.id}" checked disabled>`)
  ).join("") + `</div>`;

  for (const [role, label] of [
    ["main", "Hovedmodell — velg kvalitet"],
    ["reasoning", "Resonneringsmodell — velg kvalitet"],
  ]) {
    const group = byRole(role);
    const haveOne = group.find(e => e.installed);
    html += `<div class="setup-group"><h3>${label}</h3>`;
    if (haveOne) {
      html += `<div class="setup-installed-note">✓ Installert: ${haveOne.display_name || haveOne.name}. Velg en annen kvalitet for å legge til.</div>`;
    }
    html += group.map(e => e.installed
      ? rowHTML(e, "")
      : rowHTML(e, `<input type="radio" name="setup-${role}" data-model-id="${e.id}" ${(!haveOne && e.default) ? "checked" : ""}>`)
    ).join("") + `</div>`;
  }

  const extra = byRole("extra");
  html += `<div class="setup-group"><h3>Flere modeller (valgfritt)</h3>` + extra.map(e =>
    rowHTML(e, `<input type="checkbox" data-model-id="${e.id}" ${e.installed ? "checked disabled" : ""}>`)
  ).join("") + `</div>`;

  setupGroupsEl.innerHTML = html;
  setupGroupsEl.querySelectorAll("input[data-model-id]").forEach(i => i.addEventListener("change", updateTotal));
  updateTotal();
}

function collectSelected() {
  const ids = [];
  setupGroupsEl.querySelectorAll("input[data-model-id]").forEach(i => {
    if (!i.checked) return;
    const e = setupCatalog.find(x => x.id === i.dataset.modelId);
    if (e && !e.installed) ids.push(e.id);
  });
  return ids;
}

function updateTotal() {
  const ids = collectSelected();
  dlPlannedIds = ids;
  const bytes = ids.reduce((s, id) => {
    const e = setupCatalog.find(x => x.id === id);
    return s + (e ? (e.size_bytes || 0) : 0);
  }, 0);
  setupTotalEl.textContent = ids.length ? `Totalt: ${fmtSize(bytes)}` : "Ingenting valgt";
  setupDownloadBtn.disabled = ids.length === 0;
  setupDownloadBtn.textContent = ids.length ? `Last ned ${fmtSize(bytes)}` : "Last ned";
}

async function startDownloads() {
  const ids = collectSelected();
  if (!ids.length) return;
  dlPlannedIds = ids;

  setupChooseEl.classList.add("hidden");
  setupProgressEl.classList.remove("hidden");
  setupDownloadBtn.classList.add("hidden");
  setupProceedBtn.classList.add("hidden");
  setupCloseBtn.classList.add("hidden");
  setupCancelBtn.classList.remove("hidden");
  setupTotalEl.textContent = "";
  setupTitleEl.textContent = "Laster ned…";

  renderProgress({ phase: "running", queue: ids.slice(), current: null, completed: [], failed: [] });
  await window.pywebview.api.start_model_downloads(JSON.stringify(ids));
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

  document.getElementById("setup-overall").innerHTML =
    `<div class="setup-bar"><div class="setup-bar-fill" style="width:${(frac * 100).toFixed(1)}%"></div></div>
     <div class="setup-line">${finished} / ${total} filer${state.phase === "running" ? "" : " — " + phaseLabel(state.phase)}</div>`;

  const cur = state.current;
  document.getElementById("setup-current").innerHTML = cur
    ? `<div class="setup-current-name">${cur.name}</div>
       <div class="setup-bar"><div class="setup-bar-fill" style="width:${cur.total ? (cur.downloaded / cur.total * 100).toFixed(1) : 0}%"></div></div>
       <div class="setup-line">${fmtSize(cur.downloaded)} / ${fmtSize(cur.total)}${cur.speed ? " · " + fmtSpeed(cur.speed) : ""}${(cur.speed && cur.total) ? " · " + fmtEta((cur.total - cur.downloaded) / cur.speed) + " igjen" : ""}</div>`
    : "";

  document.getElementById("setup-list").innerHTML = dlPlannedIds.map(id => {
    const e = setupCatalog.find(x => x.id === id) || { name: id };
    const failed = state.failed.find(f => f.id === id);
    let mark = "·", cls = "queued";
    if (state.completed.includes(id)) { mark = "✓"; cls = "ok"; }
    else if (failed) { mark = "✗"; cls = "fail"; }
    else if (cur && cur.id === id) { mark = "▶"; cls = "cur"; }
    return `<div class="setup-list-row ${cls}"><span class="m">${mark}</span><span class="n">${e.name}</span>${failed ? `<span class="setup-list-err">${failed.error}</span>` : ""}</div>`;
  }).join("");

  if (["done", "error", "cancelled"].includes(state.phase)) terminalUi(state);
}

async function terminalUi(state) {
  setupCancelBtn.classList.add("hidden");
  const s = await window.pywebview.api.setup_status();
  const complete = state.phase === "done" && s.missing_slots.length === 0;

  setupTitleEl.textContent = complete ? "Ferdig ✓"
    : state.phase === "cancelled" ? "Avbrutt" : "Noe gikk galt";

  setupProceedBtn.classList.toggle("hidden", !(complete || s.can_use_app));
  setupProceedBtn.textContent = complete ? "Åpne appen" : "Fortsett likevel";

  const hideDownload = complete && setupFirstRun;
  setupDownloadBtn.classList.toggle("hidden", hideDownload);
  setupDownloadBtn.disabled = false;
  setupDownloadBtn.textContent = complete ? "Last ned flere" : "Tilbake — prøv igjen";
  setupDownloadBtn.onclick = () => showSetup({ firstRun: setupFirstRun });

  setupCloseBtn.classList.toggle("hidden", setupFirstRun && !complete);
}

async function finishSetup() {
  setupOverlayEl.classList.add("hidden");
  await startupLoad();
}

setupCancelBtn.onclick = () => {
  setupCancelBtn.disabled = true;
  window.pywebview.api.cancel_model_downloads();
};
setupProceedBtn.onclick = finishSetup;
setupCloseBtn.onclick = () => setupOverlayEl.classList.add("hidden");

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "open-setup-btn") showSetup({ firstRun: false });
});
