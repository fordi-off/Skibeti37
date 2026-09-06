// ---------------- Kode page ----------------
// Pick a folder -> describe a task -> model makes a plan (editable) -> model
// writes full files -> diff view -> you apply. No commands are ever run.

let codeProject = null;                 // last read_project() result
let codeState = "idle";                 // idle | planning | plan | generating | diff
let codeSession = { id: null, name: null, folder: null, history: [] };  // task/summary log
let codeTask = "";
let codePlanText = "";
let codeRaw = "";
let codeParsed = null;

const codeBusy = () => codeState === "planning" || codeState === "generating";

const codeViewEl = () => document.getElementById("code-view");
function renderCodeView(html) { codeViewEl().innerHTML = html; }
function codeStatus(t) { document.getElementById("code-status").textContent = t || ""; }
function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function openCode() {
  document.getElementById("code-overlay").classList.remove("hidden");
  refreshCodeSessions();
  const apply = (p) => {
    if (p && p.path) {
      codeProject = p;
      document.getElementById("code-folder").textContent = p.path;
      renderCodeTree();
    }
    codeSetButtons(codeState);
  };
  if (codeSession.folder) {
    window.pywebview.api.code_set_folder(codeSession.folder).then(p => {
      if (p && !p.error) apply(p); else codeSetButtons(codeState);
    });
  } else if (!codeProject || !codeProject.path) {
    window.pywebview.api.code_read_project().then(apply);
  } else {
    apply(codeProject);
  }
}
function closeCode() {
  if (codeBusy()) return;
  document.getElementById("code-overlay").classList.add("hidden");
}

function codeFolderReady(res) {
  codeProject = res;
  codeState = "idle";
  codeRaw = ""; codeParsed = null;
  document.getElementById("code-folder").textContent = res.path || "";
  renderCodeTree();
  renderCodeView(res.too_big
    ? `<div class="code-warn">Prosjektet er for stort for lokale modeller (maks ~20 tekstfiler / ~48&nbsp;kB tekst). Velg en mindre mappe eller undermappe.</div>`
    : `<div class="code-hint">Mappe klar. Skriv en oppgave nedenfor og trykk «Lag plan».</div>`);
  codeSetButtons("idle");
}

async function codePickFolder() {
  if (codeBusy()) return;
  const res = await window.pywebview.api.code_pick_folder();
  if (!res || res.cancelled) return;
  codeSession.folder = res.path;
  codeFolderReady(res);
  if (codeSession.id || codeSession.history.length) persistCodeSession();
}

// ---- work sessions ----

function newCodeSession() {
  if (codeBusy()) return;
  codeSession = { id: null, name: null, folder: null, history: [] };
  codeProject = null;
  codeState = "idle"; codeRaw = ""; codeParsed = null; codeTask = "";
  document.getElementById("code-folder").textContent = "Ingen mappe valgt";
  document.getElementById("code-task").value = "";
  document.getElementById("code-tree").innerHTML = "";
  renderCodeView(`<div class="code-hint">Ny økt. Velg en mappe for å begynne.</div>`);
  refreshCodeSessions();
  codeSetButtons("idle");
}

async function openCodeSession(id) {
  if (codeBusy()) return;
  const s = await window.pywebview.api.code_load_session(id);
  if (!s) return;
  codeSession = { id: s.id, name: s.name, folder: s.folder || null, history: s.history || [] };
  codeState = "idle"; codeRaw = ""; codeParsed = null; codeTask = "";
  document.getElementById("code-task").value = "";
  document.getElementById("code-folder").textContent = codeSession.folder || "Ingen mappe valgt";
  if (codeSession.folder) {
    const p = await window.pywebview.api.code_set_folder(codeSession.folder);
    if (p && p.error) {
      codeProject = null;
      document.getElementById("code-tree").innerHTML = "";
      renderCodeView(`<div class="code-warn">${esc(p.error)} (${esc(codeSession.folder)}) — velg mappen på nytt.</div>`);
    } else {
      codeProject = p;
      renderCodeTree();
      renderCodeView(codeHistoryView());
    }
  } else {
    codeProject = null;
    document.getElementById("code-tree").innerHTML = "";
    renderCodeView(`<div class="code-hint">Denne økta har ingen mappe. Velg en.</div>`);
  }
  refreshCodeSessions();
  codeSetButtons("idle");
}

function codeHistoryView() {
  const h = codeSession.history;
  if (!h.length) return `<div class="code-hint">Økt gjenåpnet. Skriv en oppgave for å fortsette.</div>`;
  let items = "";
  for (let i = 0; i < h.length; i += 2) {
    items += `<div class="code-hist-item"><div class="code-hist-task">${esc((h[i] || {}).content || "")}</div><div class="code-hist-sum">${esc((h[i + 1] || {}).content || "")}</div></div>`;
  }
  return `<div class="code-hist"><h4>Tidligere i denne økta</h4>${items}</div>`;
}

async function persistCodeSession() {
  if (!codeSession.name) {
    const firstTask = (codeSession.history.find(x => x.role === "user") || {}).content || codeTask || "Kodeøkt";
    codeSession.name = firstTask.slice(0, 42);
  }
  const r = await window.pywebview.api.code_save_session(
    codeSession.id, codeSession.name, codeSession.folder, JSON.stringify(codeSession.history));
  if (r && r.id) codeSession.id = r.id;
  refreshCodeSessions();
}

async function refreshCodeSessions() {
  const list = await window.pywebview.api.code_list_sessions();
  const el = document.getElementById("code-sessions");
  el.innerHTML = "";
  if (!list.length) { el.innerHTML = `<div class="code-hint">Ingen økter ennå.</div>`; return; }
  list.forEach(s => {
    const row = document.createElement("div");
    row.className = "code-session-row" + (s.id === codeSession.id ? " active" : "");
    const name = document.createElement("span");
    name.className = "code-session-name";
    name.textContent = s.name;
    name.title = (s.folder || "(ingen mappe)") + "\nDobbeltklikk for å endre navn";
    name.ondblclick = (e) => { e.stopPropagation(); startRenameSession(row, name, s); };
    const del = document.createElement("button");
    del.className = "code-session-del";
    del.textContent = "×";
    del.title = "Slett økt (filene i mappa røres ikke)";
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!(await confirmDialog(`Slette økta «${s.name}»? Filene i mappa røres ikke.`))) return;
      await window.pywebview.api.code_delete_session(s.id);
      if (s.id === codeSession.id) newCodeSession();
      else refreshCodeSessions();
    };
    row.appendChild(name);
    row.appendChild(del);
    row.onclick = () => openCodeSession(s.id);
    el.appendChild(row);
  });
}

function startRenameSession(row, nameEl, s) {
  const input = document.createElement("input");
  input.className = "code-session-name-input";
  input.value = s.name;
  row.replaceChild(input, nameEl);
  input.focus(); input.select();
  const commit = async () => {
    const n = input.value.trim() || s.name;
    await window.pywebview.api.code_rename_session(s.id, n);
    if (s.id === codeSession.id) codeSession.name = n;
    refreshCodeSessions();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") input.blur();
    if (e.key === "Escape") { input.value = s.name; input.blur(); }
  });
  input.addEventListener("blur", commit, { once: true });
}

function renderCodeTree() {
  const files = (codeProject && codeProject.files) || [];
  const tree = document.getElementById("code-tree");
  tree.innerHTML = files.length
    ? files.map(f => `<div class="code-tree-row${f.text ? "" : " bin"}" data-rel="${esc(f.rel)}" title="${esc(f.rel)}">${esc(f.rel)}${(f.text && !f.included) ? ' <span class="tiny">(stor)</span>' : ""}</div>`).join("")
    : `<div class="code-hint">Ingen filer.</div>`;
  tree.querySelectorAll(".code-tree-row").forEach(r => { r.onclick = () => codeShowFile(r.dataset.rel); });
}

function codeShowFile(rel) {
  if (codeState === "planning" || codeState === "generating") return;
  const f = (codeProject.files || []).find(x => x.rel === rel);
  if (!f) return;
  if (!f.text) { renderCodeView(`<div class="code-hint">${esc(rel)} — binærfil, vises ikke.</div>`); return; }
  if (f.content == null) { renderCodeView(`<div class="code-hint">${esc(rel)} — for stor til å vises eller sendes (${Math.round(f.size / 1024)}&nbsp;kB).</div>`); return; }
  renderCodeView(`<div class="code-file-view"><div class="code-file-name">${esc(rel)}</div><pre><code class="language-${f.lang}">${esc(f.content)}</code></pre></div>`);
  if (window.hljs) codeViewEl().querySelectorAll("pre code").forEach(b => { try { hljs.highlightElement(b); } catch (e) { /* */ } });
}

function codeSetButtons(state) {
  const show = (id, on) => document.getElementById(id).classList.toggle("hidden", !on);
  const busy = state === "planning" || state === "generating";
  const haveFolder = !!(codeProject && codeProject.path);
  show("code-plan-btn", (state === "idle" || state === "plan"));
  show("code-gen-btn", state === "plan");
  show("code-apply-btn", state === "diff");
  show("code-cancel-btn", busy);
  document.getElementById("code-plan-btn").disabled = !haveFolder;
  document.getElementById("code-plan-btn").textContent = state === "plan" ? "Lag ny plan" : "Lag plan";
  document.getElementById("code-task").disabled = busy;
  document.getElementById("code-pick-btn").disabled = busy;
}

async function codeRunPlan() {
  const task = document.getElementById("code-task").value.trim();
  if (!task || !currentModel || !(codeProject && codeProject.path)) return;
  codeTask = task;
  codeRaw = "";
  codeState = "planning";
  codeSetButtons("planning");
  codeStatus("lager plan…");
  renderCodeView(`<div class="code-live-md"></div>`);
  try {
    await window.pywebview.api.code_plan(currentModel, task, JSON.stringify(codeSession.history));
  } catch (e) { onCodeError(String(e)); }
}

async function codeRunGenerate(cont) {
  const prevRaw = codeRaw;
  if (!cont) codeRaw = "";
  codeState = "generating";
  codeSetButtons("generating");
  codeStatus("skriver kode…");
  renderCodeView(`<pre class="code-live">${esc(codeRaw)}</pre>`);
  try {
    if (cont) {
      await window.pywebview.api.code_generate_continue(
        currentModel, codeTask, codePlanText, JSON.stringify(codeSession.history), prevRaw);
    } else {
      await window.pywebview.api.code_generate(
        currentModel, codeTask, codePlanText, JSON.stringify(codeSession.history));
    }
  } catch (e) { onCodeError(String(e)); }
}

// ---- streaming callbacks from Python ----

function onCodePhase(phase) {
  if (phase === "loading") codeStatus(`laster ${modelLabels[currentModel] || currentModel}…`);
  else codeStatus(codeState === "planning" ? "lager plan…" : "skriver kode…");
}

function onCodeChunk(delta) {
  codeRaw += delta;
  if (codeState === "planning") {
    renderCodeView(`<div class="code-live-md">${formatInline(codeRaw)}</div>`);
  } else if (codeState === "generating") {
    let pre = codeViewEl().querySelector(".code-live");
    if (!pre) { renderCodeView(`<pre class="code-live"></pre>`); pre = codeViewEl().querySelector(".code-live"); }
    pre.textContent = codeRaw;
  }
  codeViewEl().scrollTop = codeViewEl().scrollHeight;
}

function onCodeDone(info) {
  codeStatus("");
  document.getElementById("code-cancel-btn").classList.add("hidden");

  if (codeState === "planning") {
    codeState = "plan";
    renderCodeView(`<div class="code-plan-wrap"><label>Plan — rediger fritt før du genererer:</label><textarea id="code-plan-edit"></textarea></div>`);
    const ta = document.getElementById("code-plan-edit");
    ta.value = codeRaw.trim();
    autoGrow(ta, 420);
    ta.addEventListener("input", () => autoGrow(ta, 420));
    codeSetButtons("plan");
  } else if (codeState === "generating") {
    codeState = "diff";
    codeParsed = parseCodeResponse(codeRaw);
    codeParsed.truncated = !!(info && (info.truncated || info.stopped));
    renderCodeDiff();
  }
}

function onCodeError(msg) {
  codeStatus("");
  document.getElementById("code-cancel-btn").classList.add("hidden");
  renderCodeView(`<div class="code-warn">Feil: ${esc(msg)}</div>`);
  codeState = "idle";
  codeSetButtons("idle");
}

// ---- parsing the model's file output ----

function parseCodeResponse(text) {
  const files = [], deletions = [], spans = [];
  const FENCE = /```([^\n]*)\n([\s\S]*?)```/g;
  let m;
  while ((m = FENCE.exec(text)) !== null) {
    const info = m[1].trim();
    const body = m[2];
    const nl = body.indexOf("\n");
    const firstLine = (nl === -1 ? body : body.slice(0, nl)).trim();
    const bodyFm = firstLine.match(/^(?:\/\/|#|<!--|;|--)?\s*FILE:\s*(.+?)\s*(?:-->|\*\/)?$/i);
    const infoFm = info.match(/FILE:\s*(.+)$/i);
    let rel = null, content = "";
    if (bodyFm) { rel = bodyFm[1].trim(); content = nl === -1 ? "" : body.slice(nl + 1); }
    else if (infoFm) { rel = infoFm[1].trim(); content = body; }
    if (rel) {
      files.push({ rel, content: content.replace(/\n+$/, "") + "\n" });   // exactly one trailing newline
      spans.push([m.index, FENCE.lastIndex]);
    }
  }

  let truncatedBlock = null;
  if (((text.match(/```/g) || []).length) % 2 === 1) {
    const tail = text.slice(text.lastIndexOf("```")).replace(/^```[^\n]*\n?/, "");
    const nl = tail.indexOf("\n");
    const first = (nl === -1 ? tail : tail.slice(0, nl)).trim();
    const fm = first.match(/^(?:\/\/|#|<!--)?\s*FILE:\s*(.+?)\s*$/i);
    if (fm) truncatedBlock = { rel: fm[1].trim() };
  }

  let outside = text;
  spans.slice().reverse().forEach(([a, b]) => { outside = outside.slice(0, a) + "\n" + outside.slice(b); });
  outside.split("\n").forEach(line => {
    const dm = line.match(/^\s*(?:\/\/|#)?\s*DELETE:\s*(.+?)\s*$/i);
    if (dm) deletions.push(dm[1].trim());
  });

  let summary = "";
  const em = outside.match(/(?:^|\n)\s*#{0,4}\s*Endringer:\s*\n?([\s\S]*)$/i);
  if (em) summary = em[1].trim();
  else if (spans.length) summary = text.slice(spans[spans.length - 1][1]).trim();
  summary = summary.replace(/```[\s\S]*?```/g, "").replace(/^DELETE:.*$/gim, "").trim();

  return { files, deletions, summary, truncatedBlock };
}

function diffLines(aStr, bStr) {
  const a = aStr.replace(/\n$/, "").split("\n"), b = bStr.replace(/\n$/, "").split("\n");
  const n = a.length, mm = b.length;
  if (n * mm > 500000) return [{ t: "info", s: `(for stor for linjediff: ${n} → ${mm} linjer)` }];
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(mm + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = mm - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < mm) {
    if (a[i] === b[j]) { out.push({ t: " ", s: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "-", s: a[i] }); i++; }
    else { out.push({ t: "+", s: b[j] }); j++; }
  }
  while (i < n) out.push({ t: "-", s: a[i++] });
  while (j < mm) out.push({ t: "+", s: b[j++] });
  return out;
}

function renderCodeDiff() {
  const p = codeParsed;
  const cur = {};
  (codeProject.files || []).forEach(f => { cur[f.rel] = f.content; });

  let html = "";
  if (p.summary) html += `<div class="code-summary"><h4>Hva modellen gjorde</h4>${formatInline(p.summary)}</div>`;
  if (p.truncated || p.truncatedBlock) {
    html += `<div class="code-warn">Svaret ble kuttet av lengdegrensen — trykk «Fortsett svaret» for resten før du bruker endringene.</div>`;
  }
  if (!p.files.length && !p.deletions.length) {
    html += `<div class="code-hint">Modellen foreslo ingen filendringer.</div>`;
  }

  const norm = s => (s == null ? "" : s.replace(/\n+$/, "") + "\n");
  p.files.forEach((f, idx) => {
    const old = cur[f.rel] == null ? null : norm(cur[f.rel]);
    const isNew = old === null;
    const changed = isNew || old !== f.content;
    const badge = isNew ? "ny" : changed ? "endret" : "uendret";
    const rows = isNew ? f.content.replace(/\n$/, "").split("\n").map(s => ({ t: "+", s })) : diffLines(old, f.content);
    const diffHtml = rows.map(r => {
      const cls = r.t === "+" ? "dadd" : r.t === "-" ? "ddel" : r.t === "info" ? "dinfo" : "dctx";
      const pfx = r.t === "info" ? "" : (r.t === " " ? "  " : r.t + " ");
      return `<span class="${cls}">${esc(pfx + r.s)}</span>`;
    }).join("\n");
    html += `<div class="code-file">
      <label class="code-file-head">
        <input type="checkbox" data-file-idx="${idx}" ${changed ? "checked" : "disabled"}>
        <span class="code-badge b-${badge}">${badge.toUpperCase()}</span>
        <span class="code-file-name">${esc(f.rel)}</span>
      </label>
      <pre class="code-diff">${diffHtml}</pre>
    </div>`;
  });

  p.deletions.forEach((rel, idx) => {
    html += `<div class="code-file">
      <label class="code-file-head">
        <input type="checkbox" data-del-idx="${idx}" checked>
        <span class="code-badge b-slett">SLETT</span>
        <span class="code-file-name">${esc(rel)}</span>
      </label></div>`;
  });

  if (p.truncated || p.truncatedBlock) {
    html += `<button id="code-continue-btn" class="settings-small-btn">Fortsett svaret</button>`;
  }

  renderCodeView(html);
  const cont = document.getElementById("code-continue-btn");
  if (cont) cont.onclick = () => codeRunGenerate(true);
  codeSetButtons("diff");
}

async function codeApply() {
  const p = codeParsed;
  const changes = [];
  codeViewEl().querySelectorAll("input[data-file-idx]").forEach(cb => {
    if (cb.checked) { const f = p.files[+cb.dataset.fileIdx]; changes.push({ rel: f.rel, content: f.content }); }
  });
  const dels = [];
  codeViewEl().querySelectorAll("input[data-del-idx]").forEach(cb => {
    if (cb.checked) dels.push(p.deletions[+cb.dataset.delIdx]);
  });
  if (!changes.length && !dels.length) return;

  if (dels.length) {
    const ok = await confirmDialog("Slette disse filene fra disken?\n\n" + dels.join("\n"));
    if (!ok) return;
  }

  codeStatus("skriver filer…");
  document.getElementById("code-apply-btn").disabled = true;
  let res;
  try {
    res = await window.pywebview.api.code_apply(JSON.stringify(changes), JSON.stringify(dels));
  } catch (e) { res = { error: String(e) }; }
  document.getElementById("code-apply-btn").disabled = false;
  codeStatus("");

  if (res.project) { codeProject = res.project; renderCodeTree(); }
  const written = (res.results || []).filter(r => r.ok).map(r => r.rel);
  const failed = (res.results || []).filter(r => !r.ok);

  if (!res.error) {
    codeSession.history.push({ role: "user", content: codeTask });
    codeSession.history.push({ role: "assistant", content: "Endret filer: " + (written.join(", ") || "(ingen)") + (p.summary ? ". " + p.summary : "") });
    if (codeSession.history.length > 12) codeSession.history = codeSession.history.slice(-12);
    await persistCodeSession();
  }

  const foot = document.createElement("div");
  foot.className = res.error ? "code-warn" : "code-applied";
  foot.innerHTML = res.error
    ? "Feil ved skriving: " + esc(res.error)
    : `<strong>Brukt.</strong> ${written.length} fil(er) skrevet${failed.length ? `. Feilet: ${failed.map(f => esc(f.rel) + " (" + esc(f.msg) + ")").join(", ")}` : ""}. Skriv en ny oppgave for å fortsette.`;
  codeViewEl().prepend(foot);

  codeState = "idle";
  document.getElementById("code-task").value = "";
  codeSetButtons("idle");
}

document.getElementById("code-btn").onclick = openCode;
document.getElementById("code-close-btn").onclick = closeCode;
document.getElementById("code-new-session").onclick = newCodeSession;
document.getElementById("code-pick-btn").onclick = codePickFolder;
document.getElementById("code-plan-btn").onclick = codeRunPlan;
document.getElementById("code-gen-btn").onclick = () => { codePlanText = (document.getElementById("code-plan-edit") || {}).value || codeRaw; codeRunGenerate(false); };
document.getElementById("code-apply-btn").onclick = codeApply;
document.getElementById("code-cancel-btn").onclick = () => window.pywebview.api.code_cancel();
