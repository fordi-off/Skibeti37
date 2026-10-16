// Fallback inference engine: runs GGUF models as WebAssembly directly in
// this browser tab via wllama (https://github.com/ngxson/wllama), vendored
// at static/wllama/. Loaded lazily by bridge.js, only when this page is NOT
// running inside the real pywebview (i.e. app.py's fallback_server mode, for
// a machine where llama-cpp-python's native DLL is blocked). Mirrors
// generation.py/chats.py/documents.py closely enough that it calls the exact
// same global callbacks chat.js already defines (onChunk, onDone, onError,
// onGenPhase, onDocStatus) - those files need no changes at all.
import { Wllama, LoggerWithoutDebug } from "../wllama/wllama.min.js";

// wllama resolves this against document.baseURI (the page's own URL), not
// against this module's location - so it must be site-root-relative, not
// "../wllama/..." relative to static/js/wasm-engine.js.
const CONFIG_PATHS = { default: "/wllama/wllama.wasm" };

const DEFAULT_MAX_TOKENS = 2000;
const RECENT_KEEP_MESSAGES = 10;
const TOP_K_CHUNKS = 5;
const CONTINUATION_PROMPT =
  "Continue your previous answer exactly where you left off. Do not repeat " +
  "anything you have already written, and do not write any introduction - " +
  "continue straight on, in the very same language as the rest of your answer.";
const RAG_PREFIX =
  "The following are the most relevant excerpts from the user's documents, retrieved " +
  "for this question. Use them to answer precisely, and reply in the language of the " +
  "user's latest message even when the excerpts are in another language. If the answer " +
  "is not in the excerpts, say so instead of guessing:\n\n";
const SUMMARY_PREFIX =
  "Summary of earlier parts of this conversation (older messages are compressed to " +
  "save space in browser-compatibility mode, but the user still has the full history " +
  "saved).";
const SAMPLING_PARAMS = {
  temperature: 0.6,
  top_p: 0.95,
  penalty_last_n: 320,
  penalty_repeat: 1.18,
  penalty_freq: 0.1,
  penalty_present: 0.3,
};

const RETRIEVAL_CHUNK_WORDS = 300;
const RETRIEVAL_CHUNK_OVERLAP = 50;
const MAX_RETRIEVAL_CHUNKS = 800;
const SUMMARY_CHUNK_WORDS = 2400;
const MAX_SUMMARY_CHUNKS = 8;

const api = window.pywebview.api;

let chatEngine = null;
let chatEngineFilename = null;
let embedEngine = null;
let utilityEngine = null;
let utilityEngineFilename = null;
let currentAbort = null;
let stopRequested = false;

function wantsNoThink(modelName) {
  return (modelName || "").toLowerCase().includes("qwen3");
}

function renderForcedNoThinkPrompt(messages) {
  const rendered = messages
    .map((m) => `<|im_start|>${m.role}\n${m.content}<|im_end|>\n`)
    .join("");
  return rendered + "<|im_start|>assistant\n<think>\n\n</think>\n\n";
}

// ---------------- Model loading ----------------

async function newEngine() {
  return new Wllama(CONFIG_PATHS, { logger: LoggerWithoutDebug });
}

// WASM's linear memory is far more constrained than real RAM - a model
// that loads and runs fine natively can still crash the WASM runtime with
// std::bad_alloc mid-generation (seen in testing: a 4B model at the
// app's normal 16384-token default context). So the fallback engine asks
// for a lot less than the native path would, regardless of what's
// configured in Settings: a much smaller context window, always-on
// quantized KV cache (not just when a model's kv_cache setting says so -
// that choice was tuned for native RAM budgets, not WASM's), and smaller
// batch sizes, which also bound peak compute-buffer memory.
const WASM_MAX_CTX = 4096;
const WASM_N_BATCH = 512;
const WASM_N_UBATCH = 256;

async function loadForFilename(filename, extra) {
  const settings = await api.get_settings_overview();
  const params = {
    n_ctx: Math.min(settings.context_window || WASM_MAX_CTX, WASM_MAX_CTX),
    n_batch: WASM_N_BATCH,
    n_ubatch: WASM_N_UBATCH,
    n_threads: Math.max(1, settings.n_threads || navigator.hardwareConcurrency || 4),
    n_gpu_layers: 0,
    cache_type_k: "q8_0",
    cache_type_v: "q8_0",
    flash_attn: true,
    ...extra,
  };
  const engine = await newEngine();
  await engine.loadModelFromUrl("/models/" + encodeURIComponent(filename), params);
  try {
    console.log(
      `[skibeti37 wasm] ${filename}: requested n_threads=${params.n_threads}, ` +
      `isMultithread=${engine.isMultithread()}, getNumThreads=${engine.getNumThreads()}, ` +
      `crossOriginIsolated=${window.crossOriginIsolated}`
    );
  } catch (err) { /* diagnostic only */ }
  return engine;
}

async function ensureChatModel(filename) {
  if (chatEngineFilename === filename && chatEngine) return chatEngine;
  if (chatEngine) {
    try { await chatEngine.exit(); } catch (err) { /* ignore */ }
    chatEngine = null;
    chatEngineFilename = null;
  }
  chatEngine = await loadForFilename(filename, {});
  chatEngineFilename = filename;
  return chatEngine;
}

async function ensureEmbedder() {
  if (embedEngine) return embedEngine;
  embedEngine = await loadForFilename("nomic-embed-text-v1.5.Q4_K_M.gguf", {
    n_ctx: 2048,
    embeddings: true,
    pooling_type: "mean",
  });
  return embedEngine;
}

async function getUtilityModel() {
  const settings = await api.get_settings_overview();
  const filename = settings.utility_model;
  if (!filename) throw new Error("Ingen modeller funnet i models/-mappen");
  if (utilityEngineFilename === filename && utilityEngine) return { engine: utilityEngine, filename };
  if (utilityEngine) {
    try { await utilityEngine.exit(); } catch (err) { /* ignore */ }
    utilityEngine = null;
  }
  utilityEngine = await loadForFilename(filename, {});
  utilityEngineFilename = filename;
  return { engine: utilityEngine, filename };
}

async function unloadUtilityModel() {
  if (utilityEngine) {
    try { await utilityEngine.exit(); } catch (err) { /* ignore */ }
    utilityEngine = null;
    utilityEngineFilename = null;
  }
}

// Non-streaming completion that forces a hybrid Qwen3 model out of thinking
// mode - mirrors model_manager.complete_no_think exactly.
async function completeNoThink(engine, filename, messages, maxTokens, sampling) {
  if (wantsNoThink(filename)) {
    const prompt = renderForcedNoThinkPrompt(messages);
    const resp = await engine.createCompletion({
      prompt, max_tokens: maxTokens, stream: false,
      stop: ["<|im_end|>", "<|im_start|>"], ...sampling,
    });
    return resp.choices[0].text.trim();
  }
  const resp = await engine.createChatCompletion({
    messages, max_tokens: maxTokens, stream: false, ...sampling,
  });
  return resp.choices[0].message.content.trim();
}

// ---------------- Language directive (mirrors chats.py verbatim) ----------------

const NO_WORDS = new Set([
  "og", "ikke", "ikkje", "jeg", "det", "er", "som", "på", "en", "et", "ein",
  "ei", "å", "har", "kan", "vil", "hva", "kva", "hvorfor", "hvordan", "med",
  "til", "de", "vi", "du", "meg", "deg", "være", "blir", "gjøre", "hvis",
  "eller", "men", "så", "noen", "noe", "mye", "mer", "mest", "veldig", "bare",
  "hele", "takk", "hei", "kanskje", "fordi", "denne", "dette", "disse", "slik",
  "her", "der", "når", "skal", "må", "om", "av", "at", "den", "ja", "nei",
  "mellom",
]);
const EN_WORDS = new Set([
  "the", "and", "is", "are", "you", "what", "why", "how", "this", "that",
  "of", "to", "in", "it", "for", "with", "can", "could", "would", "should",
  "please", "thanks", "hey", "hello", "make", "want", "need", "because",
  "there", "their", "about", "which", "when", "where", "does", "do",
  "explain", "write", "tell", "give", "list", "show", "describe", "compare",
  "summarize", "summarise", "into", "terms", "between", "difference",
  "example", "simple", "help",
]);

function detectLanguage(text) {
  if (!text) return null;
  const low = text.toLowerCase();
  const words = low.match(/[a-zà-ÿæøå]+/g) || [];
  if (words.length < 2) return null;
  const noHits = words.filter((w) => NO_WORDS.has(w)).length;
  const enHits = words.filter((w) => EN_WORDS.has(w)).length;
  const hasNoChars = /[æøå]/.test(low);
  if (hasNoChars && enHits === 0) return "Norwegian";
  if (noHits > enHits && (noHits >= 2 || hasNoChars)) return "Norwegian";
  if (enHits > noHits && enHits >= 2) return "English";
  if (hasNoChars && noHits >= enHits) return "Norwegian";
  return null;
}

function languageDirective(lastUserText) {
  const lang = detectLanguage(lastUserText);
  if (lang) {
    return `LANGUAGE: The user's latest message is written in ${lang}. Write your ` +
      `entire reply in ${lang} (from the first word to the last). Do not ` +
      `switch or mix languages partway through, and do not translate the ` +
      `user's own words back to them. Keep code, direct quotes and proper ` +
      `names in their original form.`;
  }
  return "LANGUAGE: Reply in the exact same language as the user's latest message " +
    "(from the first word to the last). Do not switch or mix languages " +
    "partway through. Keep code, direct quotes and proper names in their " +
    "original form.";
}

// ---------------- RAG retrieval (mirrors documents.py's _top_matches_py) ----------------

function cosineSim(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / ((Math.sqrt(na) || 1e-10) * (Math.sqrt(nb) || 1e-10));
}

function snippet(text, words = 40) {
  const parts = text.split(/\s+/);
  return parts.slice(0, words).join(" ") + (parts.length > words ? "..." : "");
}

async function documentContextForQuery(chatId, queryText) {
  const chunks = await api.doc_chunks_for_query(chatId);
  if (!chunks || !chunks.length) return { context: null, sources: [] };

  const embedder = await ensureEmbedder();
  const resp = await embedder.createEmbedding({ input: queryText });
  const queryVec = resp.data[0].embedding;

  const scored = chunks.map((c, i) => ({ i, score: cosineSim(queryVec, c.embedding) }));
  scored.sort((a, b) => b.score - a.score);
  const top = scored.slice(0, TOP_K_CHUNKS);

  const excerpts = [];
  const sources = [];
  for (const { i, score } of top) {
    const c = chunks[i];
    excerpts.push(`[From ${c.filename}]\n${c.text}`);
    sources.push({ filename: c.filename, snippet: snippet(c.text), score: Math.round(score * 1000) / 1000 });
  }
  return { context: RAG_PREFIX + excerpts.join("\n\n---\n\n"), sources };
}

// ---------------- Context building (simplified chats.build_context) ----------------
// NOTE: unlike the native path, long conversations are NOT folded into a
// running summary here (that needs the utility model's full llama.cpp
// prompt-caching behaviour, which isn't worth re-implementing for the
// fallback path) - older messages past RECENT_KEEP_MESSAGES are simply
// dropped. Everything else (skills, RAG, language directive) matches.
async function buildContext(chatId, messages) {
  let systemContent = messages[0].content;
  const history = messages.slice(1);
  const lastUser = [...history].reverse().find((m) => m.role === "user");
  const lastUserMsg = lastUser ? lastUser.content : "";

  if (lastUser && lastUser.commands && lastUser.commands.length) {
    const commandsText = await api.command_bodies(JSON.stringify(lastUser.commands));
    if (commandsText) systemContent += "\n\n" + commandsText;
  }

  const { context: docContext, sources: docSources } = await documentContextForQuery(chatId, lastUserMsg);
  if (docContext) systemContent += "\n\n" + docContext;

  let recent = history;
  if (history.length > RECENT_KEEP_MESSAGES) {
    recent = history.slice(history.length - RECENT_KEEP_MESSAGES);
    systemContent += "\n\n" + SUMMARY_PREFIX;
  }

  systemContent += "\n\n" + languageDirective(lastUserMsg);

  const finalMessages = [{ role: "system", content: systemContent }, ...recent];
  return { finalMessages, meta: { compressed: false, doc_sources: docSources } };
}

// Rough token estimate for the context meter only (wllama doesn't expose a
// public tokenizer) - about 1.3 tokens per whitespace-separated word, close
// enough for a progress bar.
function estimateTokens(messages) {
  let words = 0;
  for (const m of messages) words += (m.content || "").split(/\s+/).filter(Boolean).length;
  return Math.round(words * 1.3);
}

function fitToContextApprox(messages, contextMax, responseReserve) {
  const budget = Math.max(512, contextMax - responseReserve - 64);
  if (estimateTokens(messages) <= budget) return { messages, trimmed: false };
  const system = messages[0];
  let rest = messages.slice(1);
  while (rest.length > 1 && estimateTokens([system, ...rest]) > budget) rest.shift();
  return { messages: [system, ...rest], trimmed: true };
}

// ---------------- Streaming generation ----------------

function looksLooped(text, windowSize = 180, threshold = 3) {
  if (text.length < windowSize * threshold) return false;
  const tail = text.slice(-windowSize);
  let count = 0, idx = 0;
  while ((idx = text.indexOf(tail, idx)) !== -1) { count++; idx += 1; }
  return count >= threshold;
}

export function stop() {
  stopRequested = true;
  if (currentAbort) currentAbort.abort();
}

export async function generate(modelName, messages, chatId, { continuation }) {
  stopRequested = false;
  try {
    const msgs = messages.slice();
    if (continuation) msgs.push({ role: "user", content: CONTINUATION_PROMPT });

    const wasLoaded = chatEngineFilename === modelName;
    onGenPhase(wasLoaded ? "generating" : "loading");
    const engine = await ensureChatModel(modelName);
    if (!wasLoaded) onGenPhase("generating");

    const { finalMessages: built, meta } = await buildContext(chatId, msgs);
    const settings = await api.get_settings_overview();
    const contextMax = Math.min(settings.context_window || WASM_MAX_CTX, WASM_MAX_CTX);
    const { messages: finalMessages, trimmed } = fitToContextApprox(built, contextMax, DEFAULT_MAX_TOKENS);
    const contextUsed = estimateTokens(finalMessages);

    currentAbort = new AbortController();
    let answer = "", nTokens = 0, checkedAt = 0;
    let stopped = stopRequested, looped = false, finishReason = null;

    if (!stopped) {
      const noThink = wantsNoThink(modelName);
      const onDelta = (delta) => {
        if (!delta) return;
        nTokens += 1;
        answer += delta;
        onChunk(delta);
        if (answer.length - checkedAt >= 120) {
          checkedAt = answer.length;
          if (looksLooped(answer)) { looped = true; currentAbort.abort(); }
        }
      };

      try {
        if (noThink) {
          const prompt = renderForcedNoThinkPrompt(finalMessages);
          await engine.createCompletion({
            prompt, max_tokens: DEFAULT_MAX_TOKENS, stream: true,
            stop: ["<|im_end|>", "<|im_start|>"], abortSignal: currentAbort.signal,
            ...SAMPLING_PARAMS,
            onData: (chunk) => {
              const choice = chunk.choices[0];
              onDelta(choice.text || "");
              if (choice.finish_reason) finishReason = choice.finish_reason;
            },
          });
        } else {
          await engine.createChatCompletion({
            messages: finalMessages, max_tokens: DEFAULT_MAX_TOKENS, stream: true,
            abortSignal: currentAbort.signal, ...SAMPLING_PARAMS,
            onData: (chunk) => {
              const choice = chunk.choices[0];
              onDelta((choice.delta && choice.delta.content) || "");
              if (choice.finish_reason) finishReason = choice.finish_reason;
            },
          });
        }
      } catch (err) {
        if (!(stopRequested || looped)) throw err;
      }
      stopped = stopped || stopRequested;
    }

    onDone({
      truncated: finishReason === "length",
      stopped, looped, trimmed,
      compressed: meta.compressed,
      doc_sources: meta.doc_sources,
      context_used: contextUsed,
      context_max: contextMax,
    });
  } catch (err) {
    console.error(err);
    onError(String((err && err.message) || err));
  } finally {
    currentAbort = null;
  }
}

export async function estimateContext(chatId, modelName, messages) {
  const { finalMessages, meta } = await buildContext(chatId, messages);
  const settings = await api.get_settings_overview();
  return {
    context_used: estimateTokens(finalMessages),
    context_max: Math.min(settings.context_window || WASM_MAX_CTX, WASM_MAX_CTX),
    compressed: meta.compressed,
  };
}

// ---------------- Document indexing (mirrors documents.add_document) ----------------

function chunkText(text, chunkSize, overlap) {
  const words = text.split(/\s+/).filter(Boolean);
  const chunks = [];
  let start = 0;
  while (start < words.length) {
    chunks.push(words.slice(start, start + chunkSize).join(" "));
    start += chunkSize - overlap;
  }
  return chunks;
}

function pickFile() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".txt,.md";
    input.style.display = "none";
    input.addEventListener("change", () => resolve(input.files[0] || null), { once: true });
    document.body.appendChild(input);
    input.click();
    setTimeout(() => input.remove(), 60000);
  });
}

export async function addDocument(chatId) {
  if (!chatId) return { cancelled: true, error: "Ingen samtale å knytte dokumentet til" };

  const file = await pickFile();
  if (!file) return { cancelled: true };

  const filename = file.name;
  const content = await file.text();
  const status = (text) => onDocStatus(text);

  status(`Deler opp ${filename} for søk...`);
  let retrievalChunks = chunkText(content, RETRIEVAL_CHUNK_WORDS, RETRIEVAL_CHUNK_OVERLAP);
  const truncatedIndex = retrievalChunks.length > MAX_RETRIEVAL_CHUNKS;
  if (truncatedIndex) retrievalChunks = retrievalChunks.slice(0, MAX_RETRIEVAL_CHUNKS);

  const embedder = await ensureEmbedder();
  const chunkData = [];
  for (let i = 0; i < retrievalChunks.length; i++) {
    status(`Lager søkeindeks for ${filename}: bit ${i + 1}/${retrievalChunks.length}`);
    const resp = await embedder.createEmbedding({ input: retrievalChunks[i] });
    chunkData.push({ text: retrievalChunks[i], embedding: resp.data[0].embedding });
  }

  const summaryChunks = chunkText(content, SUMMARY_CHUNK_WORDS, 0).slice(0, MAX_SUMMARY_CHUNKS);
  let utility;
  try {
    utility = await getUtilityModel();
  } catch (err) {
    return { cancelled: true, error: String(err.message || err) };
  }
  const partialSummaries = [];
  for (let i = 0; i < summaryChunks.length; i++) {
    status(`Oppsummerer ${filename}: del ${i + 1}/${summaryChunks.length}`);
    const prompt = [
      { role: "system", content: "You summarise parts of a document. Capture concrete facts, names, numbers and the structure of the text. Be precise, not generic. Write the summary in the same language as the document." },
      { role: "user", content: `Summarise this part:\n\n${summaryChunks[i]}` },
    ];
    partialSummaries.push(await completeNoThink(utility.engine, utility.filename, prompt, 350, { temperature: 0.3 }));
  }

  status(`Setter sammen sluttsammendrag for ${filename}...`);
  let finalSummary;
  if (partialSummaries.length > 1) {
    const prompt = [
      { role: "system", content: "You are given several partial summaries of the same document, in order. Merge them into one thorough, structured summary with headings (markdown ##) for the different parts/themes. Keep concrete details and facts - do not generalise away important content. Aim for 400-700 words. Write the summary in the same language as the partial summaries." },
      { role: "user", content: partialSummaries.map((s, i) => `Part ${i + 1}:\n${s}`).join("\n\n---\n\n") },
    ];
    finalSummary = await completeNoThink(utility.engine, utility.filename, prompt, 1200, { temperature: 0.3 });
  } else {
    finalSummary = partialSummaries[0] || "(tomt dokument)";
  }
  await unloadUtilityModel();

  status("");
  const result = await api.save_document_from_data(chatId, filename, finalSummary, JSON.stringify(chunkData));
  if (truncatedIndex && result && !result.error) {
    result.notice = `«${filename}» er stort - bare de første delene ble indeksert for søk.`;
  }
  return result;
}
