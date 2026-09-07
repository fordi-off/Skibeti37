// ---------------- Chat list ----------------

async function refreshChatList() {
  const chats = await window.pywebview.api.list_chats();
  chatListEl.innerHTML = "";

  if (chats.length === 0) {
    chatListEl.innerHTML = `<div class="empty-hint">Ingen samtaler ennå.</div>`;
    return;
  }

  chats.forEach(chat => {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.id === currentChatId ? " active" : "");

    const nameSpan = document.createElement("span");
    nameSpan.className = "chat-name";
    nameSpan.textContent = chat.name;
    nameSpan.title = "Dobbeltklikk for å endre navn";
    nameSpan.ondblclick = (e) => { e.stopPropagation(); startRename(item, nameSpan, chat); };

    const delBtn = document.createElement("button");
    delBtn.className = "chat-del";
    delBtn.textContent = "×";
    delBtn.title = "Slett samtale";
    delBtn.onclick = async (e) => {
      e.stopPropagation();
      await window.pywebview.api.delete_chat(chat.id);
      if (chat.id === currentChatId) startNewChat();
      refreshChatList();
    };

    item.appendChild(nameSpan);
    item.appendChild(delBtn);
    item.onclick = () => openChat(chat.id);
    chatListEl.appendChild(item);
  });
}

function startRename(item, nameSpan, chat) {
  const input = document.createElement("input");
  input.className = "chat-name-input";
  input.value = chat.name;
  item.replaceChild(input, nameSpan);
  input.focus();
  input.select();

  const commit = async () => {
    const newName = input.value.trim() || chat.name;
    await window.pywebview.api.rename_chat(chat.id, newName);
    if (chat.id === currentChatId) currentChatName = newName;
    refreshChatList();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") input.blur();
    if (e.key === "Escape") { input.value = chat.name; input.blur(); }
  });
  input.addEventListener("blur", commit, { once: true });
}

async function openChat(chatId) {
  if (isGenerating) return;
  const data = await window.pywebview.api.load_chat(chatId);
  if (!data) return;

  currentChatId = data.id;
  currentChatName = data.name;
  conversation = data.messages;
  if (data.model) selectModel(data.model);

  const turns = conversation.filter(m => m.role !== "system").length;
  logStatus(`chat opened: "${data.name}" (${turns} messages)`);

  renderConversation();
  contextMeterEl.classList.remove("visible");
  refreshChatList();
  refreshDocList();
}

function startNewChat() {
  if (isGenerating) return;
  currentChatId = null;
  currentChatName = null;
  conversation = [{ role: "system", content: SYSTEM_PROMPT }];
  chatEl.innerHTML = emptyStateHTML();
  contextMeterEl.classList.remove("visible");
  refreshChatList();
  refreshDocList();
}

document.getElementById("new-chat-btn").onclick = startNewChat;

async function persistChat() {
  if (!currentChatName) {
    const firstUser = conversation.find(m => m.role === "user");
    currentChatName = firstUser ? firstUser.content.slice(0, 45) : "Ny samtale";
  }
  const savedId = await window.pywebview.api.save_chat(
    currentChatId, currentChatName, currentModel, JSON.stringify(conversation)
  );
  currentChatId = savedId;
  refreshChatList();
}

async function ensureChatExists() {
  if (!currentChatId) {
    currentChatName = currentChatName || "Ny samtale";
    currentChatId = await window.pywebview.api.save_chat(
      null, currentChatName, currentModel, JSON.stringify(conversation)
    );
    refreshChatList();
  }
  return currentChatId;
}


// ---------------- Chat view ----------------

const COPY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const CHECK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
const EDIT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`;
const REGEN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`;

function clearEmptyState() {
  const empty = chatEl.querySelector(".empty-state");
  if (empty) empty.remove();
}

// Drop-cap the opening reply only, and only if it has enough text to carry one.
function markLeadReply() {
  const replies = chatEl.querySelectorAll(".msg.assistant");
  replies.forEach((m, i) => {
    const lead = i === 0 && (m.innerText || "").trim().length > 180;
    m.classList.toggle("lead", lead);
  });
}

// Rebuilds the whole chat view from `conversation`. Every rendered .msg node
// carries data-ci = its index in `conversation`, so regenerate/edit know
// exactly what to cut.
function renderConversation() {
  chatEl.innerHTML = "";
  let hasContent = false;
  conversation.forEach((msg, ci) => {
    if (msg.role === "user") {
      addUserMessage(msg.content, ci, msg.commands);
      hasContent = true;
    } else if (msg.role === "assistant") {
      const { contentEl, div } = addAssistantMessage(currentModel, ci);
      contentEl.innerHTML = formatInline(msg.content);
      enhanceContent(contentEl);
      renderDocSources(div, msg.sources);
      hasContent = true;
    }
  });
  if (!hasContent) {
    chatEl.innerHTML = emptyStateHTML();
  }
  markLeadReply();
}

function addUserMessage(text, ci, commands) {
  clearEmptyState();
  const div = document.createElement("div");
  div.className = "msg user";
  if (ci != null) div.dataset.ci = ci;
  div.innerHTML = `
    <div class="msg-actions"><button class="msg-edit-btn" title="Rediger melding og generer på nytt herfra"></button></div>
    <div class="bubble"></div>
  `;
  div.querySelector(".bubble").textContent = text;
  if (commands && commands.length) {
    const chips = document.createElement("div");
    chips.className = "msg-cmds";
    commands.forEach(c => {
      const chip = document.createElement("span");
      chip.className = "msg-cmd-chip";
      chip.textContent = "/" + c;
      chips.appendChild(chip);
    });
    div.appendChild(chips);
  }
  const editBtn = div.querySelector(".msg-edit-btn");
  editBtn.innerHTML = EDIT_ICON;
  editBtn.onclick = () => startEditMessage(div);
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return { div };
}

function addAssistantMessage(modelId, ci) {
  clearEmptyState();
  const div = document.createElement("div");
  div.className = "msg assistant";
  if (ci != null) div.dataset.ci = ci;
  div.innerHTML = `
    <div class="content"></div>
    <div class="msg-meta">
      <button class="msg-copy-btn" title="Kopier svar"></button>
      <button class="msg-regen-btn" title="Regenerer dette svaret"></button>
      <span class="meta-text">${modelLabels[modelId] || modelId || ""}</span>
    </div>
  `;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;

  const contentEl = div.querySelector(".content");
  const metaTextEl = div.querySelector(".meta-text");
  const copyBtnEl = div.querySelector(".msg-copy-btn");
  copyBtnEl.innerHTML = COPY_ICON;
  copyBtnEl.onclick = () => copyToClipboard(contentEl.innerText, copyBtnEl);
  const regenBtnEl = div.querySelector(".msg-regen-btn");
  regenBtnEl.innerHTML = REGEN_ICON;
  regenBtnEl.onclick = () => regenerateMessage(div);

  return { contentEl, metaTextEl, copyBtnEl, div };
}

function renderDocSources(msgEl, sources) {
  const existing = msgEl.querySelector(".doc-sources");
  if (existing) existing.remove();
  if (!sources || !sources.length) return;

  const details = document.createElement("details");
  details.className = "doc-sources";
  const summary = document.createElement("summary");
  summary.textContent = `Kilder · ${sources.length} utdrag`;
  details.appendChild(summary);

  sources.forEach((src, i) => {
    const item = document.createElement("div");
    item.className = "doc-source-item";
    const name = document.createElement("div");
    name.className = "doc-source-name";
    name.textContent = src.score != null
      ? `[${i + 1}] ${src.filename} · ${src.score}`
      : `[${i + 1}] ${src.filename}`;
    const snip = document.createElement("div");
    snip.className = "doc-source-snippet";
    snip.textContent = src.snippet || "";
    item.appendChild(name);
    item.appendChild(snip);
    details.appendChild(item);
  });

  msgEl.appendChild(details);
}

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    btn.innerHTML = CHECK_ICON;
    btn.classList.add("copied");
    setTimeout(() => { btn.innerHTML = COPY_ICON; btn.classList.remove("copied"); }, 1500);
  } catch (err) {
    btn.title = "Kunne ikke kopiere";
  }
}

function tableToText(table) {
  return [...table.querySelectorAll("tr")]
    .map(row => [...row.children].map(cell => cell.innerText.trim()).join("\t"))
    .join("\n");
}

function enhanceContent(contentEl) {
  contentEl.querySelectorAll("pre").forEach(pre => {
    if (pre.parentElement.classList.contains("code-block-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "code-block-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const btn = document.createElement("button");
    btn.className = "block-copy-btn";
    btn.title = "Kopier kode";
    btn.innerHTML = COPY_ICON;
    btn.onclick = () => copyToClipboard(pre.innerText, btn);
    wrap.appendChild(btn);
  });

  if (window.hljs) {
    contentEl.querySelectorAll("pre code").forEach(block => {
      if (block.dataset.highlighted) return;
      try { hljs.highlightElement(block); } catch (err) { /* unknown language, leave plain */ }
      block.dataset.highlighted = "1";
    });
  }

  contentEl.querySelectorAll("table").forEach(table => {
    if (table.parentElement.classList.contains("table-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
    const btn = document.createElement("button");
    btn.className = "block-copy-btn";
    btn.title = "Kopier tabell";
    btn.innerHTML = COPY_ICON;
    btn.onclick = () => copyToClipboard(tableToText(table), btn);
    wrap.appendChild(btn);
  });
}

function autoGrow(ta, maxPx = 320) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, maxPx) + "px";
}


// ---------------- Sending / stopping / regenerating / editing ----------------

// While a reply is streaming, the Send button becomes a Stop button.
function enterGeneratingUI(statusText) {
  isGenerating = true;
  sendBtn.disabled = false;
  sendBtn.textContent = "Stopp";
  sendBtn.classList.add("stop");
  statusEl.textContent = statusText;
}

function exitGeneratingUI() {
  isGenerating = false;
  sendBtn.disabled = false;
  sendBtn.textContent = "Send";
  sendBtn.classList.remove("stop");
  statusEl.textContent = "";
}

async function stopGeneration() {
  if (!isGenerating) return;
  sendBtn.disabled = true;            // re-enabled by onDone once the stream actually stops
  statusEl.textContent = "stopper...";
  try {
    await window.pywebview.api.stop_generation();
  } catch (err) { /* onDone still fires */ }
}

// Kicks off a model reply for the current `conversation` (which must already
// end with a user message). Shared by first send, regenerate and edit.
async function runGeneration() {
  if (!currentModel || isGenerating) return;

  enterGeneratingUI(`genererer med ${modelLabels[currentModel] || currentModel}...`);

  const { contentEl, metaTextEl } = addAssistantMessage(currentModel, conversation.length);
  const isReasoning = isReasoningModel(currentModel);

  window._streamState = {
    contentEl, isReasoning, metaTextEl,
    metaBase: metaTextEl ? metaTextEl.textContent : "",
    rawBuffer: "", answerBuffer: "", thinkingEl: null, inThinking: false,
    tokenCount: 0, startTime: performance.now(), isContinuation: false,
  };

  try {
    await window.pywebview.api.send_message(currentModel, JSON.stringify(conversation), currentChatId);
  } catch (err) {
    contentEl.innerHTML += `<em>Feil: ${err}</em>`;
    exitGeneratingUI();
  }
}

async function sendMessage(e) {
  e.preventDefault();
  if (isGenerating) { stopGeneration(); return; }

  const raw = inputEl.value.trim();
  if (!raw || !currentModel) return;

  // Pull any leading "/command" tokens off the message. They don't go to the
  // model as text - the command's instruction is added server-side instead.
  const { text, commands } = extractCommands(raw);
  if (!text) { statusEl.textContent = "Skriv en melding etter kommandoen."; return; }

  inputEl.value = "";
  hideCmdMenu();
  autoGrow(inputEl, 160);
  const msg = { role: "user", content: text };
  if (commands.length) msg.commands = commands;
  conversation.push(msg);
  addUserMessage(text, conversation.length - 1, commands);
  await runGeneration();
}

// Textarea input: Enter sends, Shift+Enter inserts a newline; grow with content.
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});
inputEl.addEventListener("input", () => autoGrow(inputEl, 160));

async function regenerateMessage(msgEl) {
  if (isGenerating || !currentModel) return;
  const ci = parseInt(msgEl.dataset.ci, 10);
  if (isNaN(ci) || conversation[ci]?.role !== "assistant") return;
  if (conversation[ci - 1]?.role !== "user") return;

  const dropped = conversation.length - ci;          // this reply + everything after it
  const laterMsgs = dropped - 1;
  const question = laterMsgs > 0
    ? `Regenerer dette svaret? Det sletter svaret og de ${laterMsgs} meldingene under det, og genererer på nytt fra forrige melding.`
    : `Regenerer dette svaret? Det forrige svaret slettes.`;
  if (!(await confirmDialog(question))) return;

  conversation.length = ci;   // cut the old reply and anything after
  renderConversation();
  await runGeneration();
}

async function startEditMessage(msgEl) {
  if (isGenerating) return;
  const ci = parseInt(msgEl.dataset.ci, 10);
  if (isNaN(ci) || conversation[ci]?.role !== "user") return;

  const original = conversation[ci].content;
  const bubble = msgEl.querySelector(".bubble");
  const actions = msgEl.querySelector(".msg-actions");

  const editor = document.createElement("div");
  editor.className = "msg-editor";
  const ta = document.createElement("textarea");
  ta.value = original;
  const btnRow = document.createElement("div");
  btnRow.className = "msg-editor-actions";
  const cancelBtn = document.createElement("button");
  cancelBtn.className = "settings-small-btn";
  cancelBtn.textContent = "Avbryt";
  const saveBtn = document.createElement("button");
  saveBtn.className = "confirm-danger-btn";
  saveBtn.textContent = "Lagre og generer på nytt";
  btnRow.appendChild(cancelBtn);
  btnRow.appendChild(saveBtn);
  editor.appendChild(ta);
  editor.appendChild(btnRow);

  bubble.style.display = "none";
  if (actions) actions.style.display = "none";
  msgEl.appendChild(editor);
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
  autoGrow(ta);
  ta.addEventListener("input", () => autoGrow(ta));

  const cleanup = () => {
    editor.remove();
    bubble.style.display = "";
    if (actions) actions.style.display = "";
  };

  const commit = async () => {
    const newText = ta.value.trim();
    if (!newText || newText === original) { cleanup(); return; }

    const laterMsgs = conversation.length - ci - 1;
    if (laterMsgs > 0) {
      const ok = await confirmDialog(
        `Lagre endringen? Alt etter denne meldingen (${laterMsgs} melding${laterMsgs === 1 ? "" : "er"}) ` +
        `slettes, og et nytt svar genereres.`
      );
      if (!ok) return;
    }

    const edited = { role: "user", content: newText };
    if (conversation[ci].commands) edited.commands = conversation[ci].commands;
    conversation[ci] = edited;
    conversation.length = ci + 1;
    renderConversation();
    await runGeneration();
  };

  cancelBtn.onclick = cleanup;
  saveBtn.onclick = commit;
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
    if (e.key === "Escape") { e.preventDefault(); cleanup(); }
  });
}

function showContinueButton(s, stopped) {
  removeContinueButton(s);
  const btn = document.createElement("button");
  btn.className = "continue-btn";
  btn.textContent = stopped ? "Stoppet - fortsett →" : "Svaret ble kuttet - fortsett →";
  btn.onclick = continueResponse;
  s.contentEl.appendChild(btn);
}
function removeContinueButton(s) {
  const existing = s.contentEl.querySelector(".continue-btn");
  if (existing) existing.remove();
}

async function continueResponse() {
  if (isGenerating) return;
  const s = window._streamState;
  if (!s) return;

  removeContinueButton(s);
  enterGeneratingUI("fortsetter...");

  s.isContinuation = true;
  s.tokenCount = 0;
  s.startTime = performance.now();

  try {
    await window.pywebview.api.continue_message(currentModel, JSON.stringify(conversation), currentChatId);
  } catch (err) {
    s.contentEl.innerHTML += `<em>Feil: ${err}</em>`;
    exitGeneratingUI();
  }
}

function renderAnswer(s, text) {
  s.answerBuffer += text;
  let answerEl = s.contentEl.querySelector(".answer-text");
  if (!answerEl) {
    answerEl = document.createElement("div");
    answerEl.className = "answer-text";
    s.contentEl.appendChild(answerEl);
  }
  answerEl.innerHTML = formatInline(s.answerBuffer);
}

function onChunk(delta) {
  const s = window._streamState;
  s.rawBuffer += delta;
  s.tokenCount += 1;

  // Safety net: a model we didn't flag as reasoning still opened a <think>
  // block (e.g. a hybrid Qwen that ignored /no_think). Render it properly.
  if (!s.isReasoning && s.rawBuffer.trimStart().startsWith("<think>")) {
    s.isReasoning = true;
  }

  if (s.isReasoning) {
    // Open the thinking block up front: Qwen3-Thinking often omits the opening
    // <think> tag and emits only the closing one, so we can't wait to see it.
    if (!s.thinkingEl) {
      const details = document.createElement("details");
      details.className = "thinking-block";
      details.open = true;   // visible while it streams, collapsed on done
      const summary = document.createElement("summary");
      summary.textContent = "Tankegang";
      s.thinkingEl = document.createElement("div");
      s.thinkingEl.className = "thinking-body";
      details.appendChild(summary);
      details.appendChild(s.thinkingEl);
      s.thinkingDetails = details;
      s.contentEl.appendChild(details);
    }
    // Rebuild both panes from the raw buffer each chunk - the split point is
    // wherever </think> lands (there may be no opening tag at all).
    const raw = s.rawBuffer.replace(/^\s*<think>/, "");
    const end = raw.indexOf("</think>");
    if (end === -1) {
      s.thinkingEl.textContent = raw;
    } else {
      s.thinkingEl.textContent = raw.slice(0, end);
      s.answerBuffer = raw.slice(end + 8).replace(/^\s+/, "");
      let answerEl = s.contentEl.querySelector(".answer-text");
      if (!answerEl) {
        answerEl = document.createElement("div");
        answerEl.className = "answer-text";
        s.contentEl.appendChild(answerEl);
      }
      answerEl.innerHTML = formatInline(s.answerBuffer);
    }
  } else {
    renderAnswer(s, delta);
  }

  chatEl.scrollTop = chatEl.scrollHeight;
}

// Mirrors _looks_looped in generation.py: if a long span repeats, keep only
// the text up to the end of its first occurrence.
function trimRepeatedTail(text, window = 180) {
  if (text.length < window * 3) return text;
  const tail = text.slice(-window);
  const first = text.indexOf(tail);
  if (first !== -1 && first < text.length - window) {
    return text.slice(0, first + window).replace(/\s+$/, "");
  }
  return text;
}

async function onDone(info) {
  const s = window._streamState;
  const truncated = !!(info && info.truncated);
  const stopped = !!(info && info.stopped);
  const looped = !!(info && info.looped);

  // Stopped before any text arrived: drop the empty assistant bubble entirely.
  if (stopped && !s.isContinuation && s.answerBuffer.trim() === "") {
    const msgEl = s.contentEl.closest(".msg");
    if (msgEl) msgEl.remove();
    exitGeneratingUI();
    return;
  }

  // A degenerate loop was cut off mid-repeat - drop the repeated tail so the
  // saved message keeps only the first, non-repeating pass.
  if (looped) {
    s.answerBuffer = trimRepeatedTail(s.answerBuffer);
    const answerEl = s.contentEl.querySelector(".answer-text");
    if (answerEl) answerEl.innerHTML = formatInline(s.answerBuffer);
  }

  // Reasoning model that never closed its <think> - treat the whole thing as
  // the answer rather than hiding it all in a collapsed block.
  if (s.isReasoning && !stopped && s.answerBuffer.trim() === ""
      && s.thinkingEl && s.thinkingEl.textContent.trim() !== "") {
    s.answerBuffer = s.thinkingEl.textContent.trim();
    if (s.thinkingDetails) s.thinkingDetails.remove();
    s.thinkingDetails = null;
    let answerEl = s.contentEl.querySelector(".answer-text");
    if (!answerEl) {
      answerEl = document.createElement("div");
      answerEl.className = "answer-text";
      s.contentEl.appendChild(answerEl);
    }
    answerEl.innerHTML = formatInline(s.answerBuffer);
  }

  if (s.isContinuation) {
    conversation[conversation.length - 1].content = s.answerBuffer;
  } else {
    const msg = { role: "assistant", content: s.answerBuffer };
    if (info && info.doc_sources && info.doc_sources.length) msg.sources = info.doc_sources;
    conversation.push(msg);
  }

  const elapsed = (performance.now() - s.startTime) / 1000;
  const speed = elapsed > 0 ? (s.tokenCount / elapsed) : 0;
  if (s.metaTextEl) {
    s.metaTextEl.textContent = `${s.metaBase} · ${elapsed.toFixed(1)}s · ${speed.toFixed(1)} tok/s`;
  }

  if (looped) {
    removeContinueButton(s);
    if (!s.contentEl.querySelector(".gen-note")) {
      const note = document.createElement("div");
      note.className = "gen-note";
      note.textContent = "Svaret begynte å gjenta seg selv, så det ble stoppet. Prøv å regenerere eller still spørsmålet på nytt.";
      s.contentEl.appendChild(note);
    }
  } else if (truncated || stopped) {
    showContinueButton(s, stopped);
  } else {
    removeContinueButton(s);
  }

  if (info && info.trimmed && !s.contentEl.querySelector(".gen-note")) {
    const note = document.createElement("div");
    note.className = "gen-note";
    note.textContent = "Meldingen var for lang for kontekstvinduet — eldre meldinger eller deler av teksten ble utelatt. Øk kontekstvinduet i Innstillinger for mer plass.";
    s.contentEl.appendChild(note);
    logStatus("prompt trimmed to fit context window");
  }

  if (info && typeof info.context_used === "number") {
    updateContextMeter(info.context_used, info.context_max, info.compressed);
  }

  if (!s.isContinuation) {
    const msgEl = s.contentEl.closest(".msg");
    if (msgEl) renderDocSources(msgEl, info && info.doc_sources);
  }

  enhanceContent(s.contentEl);
  if (s.thinkingDetails) s.thinkingDetails.open = false;   // tuck the reasoning away
  markLeadReply();

  exitGeneratingUI();
  await persistChat();
}

function onError(message) {
  window._streamState.contentEl.innerHTML += `<em>Feil: ${message}</em>`;
  exitGeneratingUI();
}

// Backend signal: "loading" while a cold model file is being read into RAM,
// "generating" once tokens are about to flow.
function onGenPhase(phase) {
  if (!isGenerating) return;
  const label = modelLabels[currentModel] || currentModel;
  logStatus(phase === "loading" ? `loading model into RAM: ${label}` : `generating: ${label}`);
  statusEl.textContent = phase === "loading"
    ? `laster ${label}... (første gang tar det litt tid)`
    : `genererer med ${label}...`;
}

formEl.addEventListener("submit", sendMessage);
