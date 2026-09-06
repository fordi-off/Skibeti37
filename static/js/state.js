marked.setOptions({ breaks: true, gfm: true });

let allModels = [];          // [{id, name}]
let modelLabels = {};        // id -> name (short display text)
let currentModel = null;
let currentChatId = null;
let currentChatName = null;
let isGenerating = false;

const SYSTEM_PROMPT =
  "You are a helpful assistant. Always reply in the same language the user " +
  "writes in, and match their tone. Think step by step when a question needs it.";

let conversation = [{ role: "system", content: SYSTEM_PROMPT }];

// Reasoning models (DeepSeek-R1 distill) emit a <think> block that the UI
// renders separately from the answer.
function isReasoningModel(id) {
  if (!id) return false;
  return id.toLowerCase().includes("deepseek")
    || (modelLabels[id] || "").toLowerCase().includes("deepseek");
}

const chatEl = document.getElementById("chat");
const modelSelectEl = document.getElementById("model-select");
const statusEl = document.getElementById("status-line");
const formEl = document.getElementById("input-form");
const inputEl = document.getElementById("input-field");
const sendBtn = document.getElementById("send-btn");
const chatListEl = document.getElementById("chat-list");
const docListEl = document.getElementById("doc-list");
const docStatusEl = document.getElementById("doc-status");
const contextMeterEl = document.getElementById("context-meter");
const contextBarFillEl = document.getElementById("context-bar-fill");
const contextMeterTextEl = document.getElementById("context-meter-text");

function updateContextMeter(used, max, compressed) {
  const pct = Math.min(100, (used / max) * 100);
  contextBarFillEl.style.width = pct + "%";
  contextBarFillEl.classList.toggle("warn", pct >= 60 && pct < 85);
  contextBarFillEl.classList.toggle("danger", pct >= 85);
  contextMeterTextEl.textContent =
    `${used} / ${max} tokens (${pct.toFixed(0)}%)` +
    (compressed ? " · eldre meldinger komprimert" : "");
  contextMeterEl.classList.add("visible");
}

function repairMarkdownTables(text) {
  const lines = text.split("\n");
  for (let i = 0; i < lines.length - 1; i++) {
    const headerLine = lines[i].trim();
    const sepLine = lines[i + 1].trim();
    const looksLikeHeader = headerLine.startsWith("|") && headerLine.endsWith("|");
    const looksLikeBrokenSep = /^\|[\s\-:|]*\|$/.test(sepLine) && sepLine.includes("-");
    if (looksLikeHeader && looksLikeBrokenSep) {
      const colCount = headerLine.split("|").filter((_, idx, arr) => idx > 0 && idx < arr.length - 1).length;
      if (colCount > 0) {
        lines[i + 1] = "|" + Array(colCount).fill("---").join("|") + "|";
      }
    }
  }
  return lines.join("\n");
}

function formatInline(text) {
  return marked.parse(repairMarkdownTables(text || ""));
}

// Placeholder shown in the chat area when there's nothing to display. Depends
// on whether any models were found in models/.
function emptyStateHTML() {
  return allModels.length
    ? `<div class="empty-state">Velg en modell over og skriv en melding for å starte.</div>`
    : `<div class="empty-state">Ingen modeller installert.<br><button id="open-setup-btn" class="setup-primary" style="margin-top:14px;">Last ned modeller</button></div>`;
}

// ---------------- Confirm dialog ----------------
// confirmDialog(message) -> Promise<boolean>. Used before anything that
// deletes messages (regenerate / edit further up a conversation).

const confirmOverlayEl = document.getElementById("confirm-overlay");
const confirmTextEl = document.getElementById("confirm-text");
let _confirmResolve = null;

function confirmDialog(message) {
  confirmTextEl.textContent = message;
  confirmOverlayEl.classList.remove("hidden");
  document.getElementById("confirm-ok-btn").focus();
  return new Promise(resolve => { _confirmResolve = resolve; });
}

function _closeConfirm(result) {
  confirmOverlayEl.classList.add("hidden");
  if (_confirmResolve) { _confirmResolve(result); _confirmResolve = null; }
}

document.getElementById("confirm-ok-btn").onclick = () => _closeConfirm(true);
document.getElementById("confirm-cancel-btn").onclick = () => _closeConfirm(false);
confirmOverlayEl.addEventListener("click", (e) => {
  if (e.target === confirmOverlayEl) _closeConfirm(false);
});
document.addEventListener("keydown", (e) => {
  if (!confirmOverlayEl.classList.contains("hidden") && e.key === "Escape") _closeConfirm(false);
});
