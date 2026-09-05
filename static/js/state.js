marked.setOptions({ breaks: true, gfm: true });

let allModels = [];          // [{id, name}]
let modelLabels = {};        // id -> name (kort visningstekst)
let currentModel = null;
let currentChatId = null;
let currentChatName = null;
let currentLanguage = "no";
let conversation = [{ role: "system", content: systemPromptFor("no") }];
let isGenerating = false;

function systemPromptFor(lang) {
  if (lang === "en") {
    return "You are a helpful assistant. Always answer in English, regardless of what language the question is asked in. Think step by step when needed.";
  }
  return "Du er en hjelpsom assistent. Svar alltid på norsk, uansett hvilket språk spørsmålet er stilt på. Tenk steg for steg når det trengs.";
}

function setLanguage(lang) {
  currentLanguage = lang;
  conversation[0] = { role: "system", content: systemPromptFor(lang) };
  document.querySelectorAll(".lang-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.lang === lang);
  });
}

document.querySelectorAll(".lang-btn").forEach(btn => {
  btn.onclick = async () => {
    setLanguage(btn.dataset.lang);
    if (currentChatId) await persistChat();
  };
});

const chatEl = document.getElementById("chat");
const pickerEl = document.getElementById("model-picker");
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
