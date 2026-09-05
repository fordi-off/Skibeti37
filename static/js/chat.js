// ---------------- Samtaleliste ----------------

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
  setLanguage(data.language || "no");
  if (data.model) selectModel(data.model);

  chatEl.innerHTML = "";
  let hasContent = false;
  for (const msg of conversation) {
    if (msg.role === "user") {
      addUserMessage(msg.content);
      hasContent = true;
    } else if (msg.role === "assistant") {
      const { contentEl } = addAssistantMessage(currentModel);
      contentEl.innerHTML = formatInline(msg.content);
      enhanceContent(contentEl);
      hasContent = true;
    }
  }
  if (!hasContent) {
    chatEl.innerHTML = `<div class="empty-state">Velg en modell over og skriv en melding for å starte.</div>`;
  }

  contextMeterEl.classList.remove("visible");
  refreshChatList();
  refreshDocList();
}

function startNewChat() {
  if (isGenerating) return;
  currentChatId = null;
  currentChatName = null;
  setLanguage("no");
  conversation = [{ role: "system", content: systemPromptFor("no") }];
  chatEl.innerHTML = `<div class="empty-state">Velg en modell over og skriv en melding for å starte.</div>`;
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
    currentChatId, currentChatName, currentModel, JSON.stringify(conversation), currentLanguage
  );
  currentChatId = savedId;
  refreshChatList();
}

async function ensureChatExists() {
  if (!currentChatId) {
    currentChatName = currentChatName || "Ny samtale";
    currentChatId = await window.pywebview.api.save_chat(
      null, currentChatName, currentModel, JSON.stringify(conversation), currentLanguage
    );
    refreshChatList();
  }
  return currentChatId;
}


// ---------------- Chat-visning ----------------

function clearEmptyState() {
  const empty = chatEl.querySelector(".empty-state");
  if (empty) empty.remove();
}

function addUserMessage(text) {
  clearEmptyState();
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="bubble"></div>`;
  div.querySelector(".bubble").textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addAssistantMessage(modelId) {
  clearEmptyState();
  const div = document.createElement("div");
  div.className = "msg assistant";
  div.innerHTML = `
    <div class="content"></div>
    <div class="msg-meta">
      <button class="msg-copy-btn" title="Kopier svar"></button>
      <span class="meta-text">${modelLabels[modelId] || modelId}</span>
    </div>
  `;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;

  const contentEl = div.querySelector(".content");
  const metaTextEl = div.querySelector(".meta-text");
  const copyBtnEl = div.querySelector(".msg-copy-btn");
  copyBtnEl.innerHTML = COPY_ICON;
  copyBtnEl.onclick = () => copyToClipboard(contentEl.innerText, copyBtnEl);

  return { contentEl, metaTextEl, copyBtnEl };
}

const COPY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const CHECK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

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

async function sendMessage(e) {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || isGenerating || !currentModel) return;

  inputEl.value = "";
  addUserMessage(text);
  conversation.push({ role: "user", content: text });

  isGenerating = true;
  sendBtn.disabled = true;
  statusEl.textContent = `genererer med ${modelLabels[currentModel] || currentModel}...`;

  const { contentEl, metaTextEl } = addAssistantMessage(currentModel);
  const isReasoning = (modelLabels[currentModel] || currentModel).toLowerCase().includes("deepseek")
    || currentModel.toLowerCase().includes("deepseek");

  window._streamState = {
    contentEl, isReasoning, metaTextEl,
    rawBuffer: "", answerBuffer: "", thinkingEl: null, inThinking: false,
    tokenCount: 0, startTime: performance.now(), isContinuation: false,
  };

  try {
    await window.pywebview.api.send_message(currentModel, JSON.stringify(conversation), currentChatId);
  } catch (err) {
    contentEl.innerHTML += `<em>Feil: ${err}</em>`;
    isGenerating = false;
    sendBtn.disabled = false;
    statusEl.textContent = "";
  }
}

function showContinueButton(s) {
  removeContinueButton(s);
  const btn = document.createElement("button");
  btn.className = "continue-btn";
  btn.textContent = "Svaret ble kuttet - fortsett →";
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
  isGenerating = true;
  sendBtn.disabled = true;
  statusEl.textContent = `fortsetter...`;

  s.isContinuation = true;
  s.tokenCount = 0;
  s.startTime = performance.now();

  try {
    await window.pywebview.api.continue_message(currentModel, JSON.stringify(conversation), currentChatId);
  } catch (err) {
    s.contentEl.innerHTML += `<em>Feil: ${err}</em>`;
    isGenerating = false;
    sendBtn.disabled = false;
    statusEl.textContent = "";
  }
}

function onChunk(delta) {
  const s = window._streamState;
  s.rawBuffer += delta;
  s.tokenCount += 1;

  if (s.isReasoning) {
    if (s.rawBuffer.includes("<think>") && !s.inThinking && !s.thinkingEl) {
      s.inThinking = true;
      s.thinkingEl = document.createElement("div");
      s.thinkingEl.className = "thinking-block";
      s.contentEl.appendChild(s.thinkingEl);
    }
    if (s.inThinking) {
      if (s.rawBuffer.includes("</think>")) {
        s.inThinking = false;
        s.thinkingEl.textContent += delta.replace("</think>", "");
      } else {
        s.thinkingEl.textContent += delta.replace("<think>", "");
      }
    } else {
      s.answerBuffer += delta.replace("<think>", "").replace("</think>", "");
      let answerEl = s.contentEl.querySelector(".answer-text");
      if (!answerEl) {
        answerEl = document.createElement("div");
        answerEl.className = "answer-text";
        s.contentEl.appendChild(answerEl);
      }
      answerEl.innerHTML = formatInline(s.answerBuffer);
    }
  } else {
    s.answerBuffer += delta;
    let answerEl = s.contentEl.querySelector(".answer-text");
    if (!answerEl) {
      answerEl = document.createElement("div");
      answerEl.className = "answer-text";
      s.contentEl.appendChild(answerEl);
    }
    answerEl.innerHTML = formatInline(s.answerBuffer);
  }

  chatEl.scrollTop = chatEl.scrollHeight;
}

async function onDone(info) {
  const s = window._streamState;
  const truncated = !!(info && info.truncated);

  if (s.isContinuation) {
    conversation[conversation.length - 1].content = s.answerBuffer;
  } else {
    conversation.push({ role: "assistant", content: s.answerBuffer });
  }

  const elapsed = (performance.now() - s.startTime) / 1000;
  const speed = elapsed > 0 ? (s.tokenCount / elapsed) : 0;
  if (s.metaTextEl) {
    s.metaTextEl.textContent += ` · ${elapsed.toFixed(1)}s · ${speed.toFixed(1)} tok/s`;
  }

  if (truncated) { showContinueButton(s); } else { removeContinueButton(s); }

  if (info && typeof info.context_used === "number") {
    updateContextMeter(info.context_used, info.context_max, info.compressed);
  }

  enhanceContent(s.contentEl);

  isGenerating = false;
  sendBtn.disabled = false;
  statusEl.textContent = "";
  await persistChat();
}

function onError(message) {
  window._streamState.contentEl.innerHTML += `<em>Feil: ${message}</em>`;
  isGenerating = false;
  sendBtn.disabled = false;
  statusEl.textContent = "";
}

formEl.addEventListener("submit", sendMessage);
