# Skibeti37 — local AI lab

A fully local chat app for running and comparing language models on your
own machine — no internet, no cloud services, no data ever leaves the PC.
Opens as its own window (via `pywebview`), not in a browser, and needs no
server to start manually.

---

## Table of contents

1. [System requirements](#system-requirements)
2. [Folder structure](#folder-structure)
3. [Installation](#installation)
4. [Models you need](#models-you-need)
5. [Running the app](#running-the-app)
6. [Features in detail](#features-in-detail)
7. [The Settings panel](#the-settings-panel)
8. [How document RAG works](#how-document-rag-works)
9. [Technical architecture](#technical-architecture)
10. [Known limitations and troubleshooting](#known-limitations-and-troubleshooting)
11. [Possible future improvements](#possible-future-improvements)

---

## System requirements

- **Python 3.10–3.13** (tested with 3.13)
- **Windows** (instructions below are Windows-specific; the app is pure
  Python and should work on macOS/Linux with the same setup)
- At least **8GB of free RAM** beyond what the system itself uses — 7B
  models in 4-bit quantization use roughly 5-6GB
- **No dedicated GPU required.** Testing showed integrated graphics
  (Vulkan acceleration) was actually **slower** than pure CPU on typical
  laptop hardware (shared memory bandwidth between CPU and iGPU) — CPU
  is the sane default, though a GPU toggle exists per model if you want
  to try it on your own hardware

---

## Folder structure

```
your-folder/
│   api.py                  ← the Api class exposed to JavaScript
│   app.py                  ← entry point - run this
│   config.py                ← settings, model file discovery
│   config.json               ← generated automatically - your saved settings
│   chats.py                  ← chat CRUD, context building, compression
│   chat_store.py             ← raw chat file read/write
│   documents.py              ← document library and RAG search
│   generation.py             ← streaming chat completion
│   model_manager.py          ← loading/unloading GGUF models
│   runtime.py                ← shared window reference
│   skills.py                  ← file-based skills
│   requirements.txt
│   README.md
│
├───chats/                   ← created automatically - one .json file per conversation
│   └───_context_summaries/    ← rolling-summary cache for long conversations
├───documents/                ← created automatically - the shared document library
├───models/                    ← your downloaded .gguf model files (see below)
├───skills/
│       anti-ai-slop.md         ← the built-in writing-style skill
│
└───static/
    │   index.html              ← page structure only
    │   marked.min.js            ← markdown rendering, loaded locally (offline)
    │
    ├───css/
    │       styles.css
    │
    └───js/
            state.js              ← shared state, DOM refs, formatting helpers
            models.js               ← model picker
            chat.js                 ← chat list + message rendering/streaming
            documents.js             ← document panel + library picker
            skills.js                ← right-panel skill switches
            settings.js               ← settings modal (all tabs)
            main.js                   ← startup
```

`chats/`, `documents/`, and `config.json` are created automatically the
first time you run the app. All of it is plain, readable JSON — open it
in a text editor, back it up, or delete it manually if needed.

---

## Installation

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` points to a prebuilt CPU-wheel index for
`llama-cpp-python`, which avoids a common Windows problem: a normal
install tries to build from source, which often fails without admin
rights due to overly long file paths (`vendor/llama.cpp/...`).

If installation still fails, try explicitly:

```bash
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
pip install pywebview numpy
```

### 2. Create the `models` folder

```bash
mkdir models
```

Download the model files (see below) and place them there.

---

## Models you need

All are GGUF files (quantized models optimized for CPU via `llama.cpp`).
**Models are discovered automatically** — the app scans `models/*.gguf`
on startup, so any file you drop in there shows up in the model picker
(and in Settings) the next time you launch. No code editing required.

| Model | Purpose |
|---|---|
| **Qwen2.5-1.5B-Instruct** | Fast, simple chat (best in English); doubles as the background model for document summaries and conversation compression when it's your smallest active model |
| **Qwen2.5-7B-Instruct** | Main model — best at Norwegian |
| **DeepSeek-R1-Distill-Qwen-7B-Uncensored** | Reasoning/math/logic (English recommended — see limitations below) |
| **nomic-embed-text-v1.5** | Required for document search (RAG). Not a chat model, and won't appear in the model picker — the app uses it internally |

Download sources (grab a `Q4_K_M` quant for the Qwens and `Q5_K_M` for
DeepSeek unless you have a reason to pick another):
- Qwen2.5-1.5B: `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF` — single-file quants
- Qwen2.5-7B: `https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF` — **use this, not the official `Qwen/Qwen2.5-7B-Instruct-GGUF` repo**, which only ships 2-shard split files (`…-00001-of-00002.gguf` + `…-00002-of-00002.gguf`). The app scans every `.gguf` separately, so a split model shows up as two broken half-entries in the picker
- DeepSeek-R1 uncensored: `https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-Uncensored-i1-GGUF`
- nomic-embed: `https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF`

The embedding model's filename must stay
`nomic-embed-text-v1.5.Q4_K_M.gguf` (or you'll need to update the path
in `config.py`) — every other `.gguf` file you add is picked up
automatically under whatever name it has. If you do end up with a split
model, merge the shards into one file first with llama.cpp's
`llama-gguf-split --merge`.

---

## Running the app

```bash
python app.py
```

or double-click `start.bat` (runs it windowless via `pythonw`). `app.py`
switches to its own folder on startup, so it also works from a desktop
shortcut or from any other directory — no need to set the shortcut's
"Start in" field.

The window opens already maximized, with normal borders and title bar
(you can resize or un-maximize it like any other window). Models load
only when actually used (lazy loading), so startup is fast.

---

## Features in detail

### Model selection

A dropdown at the top of the window switches models at any time, even
mid-conversation. Which models appear, their display names, and
whether they run on CPU or GPU are all configured in **Settings**.

### Regenerate and edit

- **Regenerate** (↻ under any reply) discards that reply and generates a
  fresh one from the message before it. If there are later messages in
  the conversation, a dialog first spells out exactly how many get
  deleted.
- **Edit** (pencil, on hover over your own message) opens the message
  inline. Saving rewrites it, drops everything after it, and generates a
  new reply from that point — again with an up-front confirmation when
  messages would be lost. `Enter` saves, `Esc` cancels, `Shift+Enter`
  for a newline.

### Conversations (left sidebar, top)

- **"+ Ny"** starts an empty conversation
- Each conversation auto-saves to `chats/` after its first reply
- Click a conversation to reopen it — full history, model, and attached
  documents are all restored
- **Double-click the name** to rename it
- **×** (on hover) deletes the conversation permanently, including its
  document attachments (the documents themselves stay in the library)

### Language

There is no language switch. The system prompt tells the model to reply
in whatever language you write in, so a Norwegian message gets a
Norwegian answer and an English one gets English. Background tasks
(conversation compression, document summaries) follow the same rule —
their instructions are in English for reliability, but the text they
produce matches the source language.

### Speed display

Under each reply: `7B · standard · 12.4s · 5.8 tok/s`. An approximation
based on text chunks received over actual elapsed time — reliable for
comparing models/settings, not a byte-exact token count.

### Context usage meter

A thin bar above the input field shows real token usage (via the
model's own tokenizer), e.g. `3400 / 16384 tokens (21%)`, turning amber
then red as it fills. Updates immediately when you switch models, not
just after a reply.

### Automatic conversation compression

Once a conversation passes 10 messages, older messages get folded into
a running summary (generated by the smallest active model) instead of
being sent in full every time. The last 10 messages always go through
verbatim. Nothing in your saved chat history is ever shortened — only
what gets sent to the model behind the scenes.

### Documents (left sidebar, bottom) — a shared library

See the RAG section below for the mechanism. In short: documents are
indexed **once** into a shared library, and individually **attached**
to whichever conversations need them.

- **"+ Ny fil"** uploads and indexes a new file, auto-attaching it to
  the current conversation
- **"📚 Bibliotek"** lets you attach a document you already indexed in
  a different conversation, without re-processing it
- The checkbox toggles a document on/off in the current conversation
  without detaching it
- **×** **detaches** the document from this conversation only — it
  stays in the library for later use elsewhere. Deleting a document
  everywhere happens in Settings → Dokumenter

After a reply that used attached documents, a collapsible **"N
dokumentutdrag brukt i svaret"** line appears under it, listing the
exact excerpts (filename, similarity score, and the opening words) that
were retrieved and fed to the model for that answer.

### Skills (right sidebar)

Toggle switches for reusable writing-style/behavior instructions,
applied globally across all conversations when active. Skills are
plain `.txt`/`.md` files in `skills/` — see the Settings section below
for creating/deleting them, or just drop a `.txt`/`.md` file into that
folder. The panel re-reads `skills/` every few seconds and when the
window regains focus, so new files show up without a restart; the ↻
button forces an immediate refresh.

### Formatting

Replies are rendered as markdown via `marked.js` (runs entirely
locally): code blocks, bold/italic, tables, lists, headings. A small
repair step also fixes tables where the model generates a malformed
separator row, which would otherwise make the whole table render as
plain text.

### Copy buttons

Icon-only copy buttons: one under each full reply, and one on hover
over every code block and table (tables copy as tab-separated text,
ready to paste into a spreadsheet).

### Stop button

While a reply is streaming, the **Send** button turns red and reads
**Stopp**. Clicking it halts generation after the current token; the
text produced so far is kept and saved.

### Continue button

If a reply gets cut off by the token limit — or you stopped it
yourself — a small "Svaret ble kuttet - fortsett →" / "Stoppet -
fortsett →" button appears under it. Clicking it continues the exact
same message seamlessly, with no repeated content and no new bubble.

---

## The Settings panel

Click the gear icon (top right) to open it. Four tabs:

### Modeller
Every `.gguf` file found in `models/` (except the embedding model),
each with:
- An active/inactive toggle — inactive models don't appear in the main
  picker at all
- An editable display name
- A CPU/GPU dropdown per model (defaults to CPU)

### Dokumenter
The entire document library, regardless of which conversations each
document is attached to. **"Åpne"** previews a document's summary and
reconstructed full text; **"Slett"** removes it everywhere, cleaning up
references in every conversation automatically.

### Skills
Full CRUD here: create a new skill (name + instructions), or delete an
existing one. The right-panel switches still just turn skills on/off —
creation and deletion live here, since skills are meant to be managed
as deliberate, reusable files rather than ad-hoc chat state.

### Ytelse (Performance)
- **Context window slider** — doubles at each step (4096 → 8192 →
  16384 → 32768 → 65536 → 131072), defaulting to 16384. Changing it
  unloads all currently loaded models so the new size takes effect on
  next use.
- **CPU threads slider** — set to roughly your CPU's physical core
  count. Also triggers a reload of all models when changed.

---

## How document RAG works

RAG = Retrieval-Augmented Generation. Instead of squeezing an entire
document into the model's context window (far too small for anything
book-length), the app does this:

### When you add a document

1. **Chunking for search**: split into ~300-word pieces with overlap,
   each turned into an embedding (search vector) via `nomic-embed-text`
2. **Structured summary**: separately, a long (400-700 word),
   heading-organized summary is built via map-reduce — larger chunks
   (1200 words) are each summarized by the background model, then
   merged into one coherent overview. This is for your own reading in
   the sidebar/Settings preview; it is **not** sent to the main model
3. The document is saved once to the shared library and attached to
   whichever conversation you were in

### On every question

1. Your question is embedded
2. The 5 most relevant chunks across all **active, attached** documents
   for that conversation are retrieved by cosine similarity
3. Only those chunks go to the main model as context — precise and
   fast, regardless of document size

### Documents are shared, attachments are per-conversation

The document (its text, chunks, and embeddings) is stored once. Which
conversations can see it is a separate, lightweight link stored in each
conversation's own file. Detaching removes that link; deleting (from
Settings) removes the document and every link to it.

---

## Technical architecture

No HTTP server, no browser tab. Communication flow:

```
static/js/*.js (JavaScript)
        │
        │  window.pywebview.api.send_message(...)
        ▼
   api.py (Api class - thin delegator)
        │
        ▼
   chats.py / documents.py / generation.py / etc. (actual logic)
        │
        │  runs in a background thread, calls llama-cpp-python
        ▼
   window.evaluate_js("onChunk(...)")   ← pushes text chunks back to the page live
```

`pywebview` uses Windows' built-in WebView2 component (same engine as
Edge, without the browser chrome) and exposes a direct Python↔JavaScript
bridge. Streaming works by Python calling `window.evaluate_js()` for
each generated text chunk, triggering `onChunk()` on the page instantly.

### Backend module responsibilities

| Module | Owns |
|---|---|
| `config.py` | Reading/writing `config.json`, scanning `models/` for `.gguf` files |
| `model_manager.py` | Loading/unloading Llama instances, the embedder |
| `chat_store.py` | Raw chat JSON file I/O (used by both `chats.py` and `documents.py`) |
| `chats.py` | Chat CRUD, context building, rolling-summary compression |
| `documents.py` | The document library, chunking/embedding, attach/detach, RAG retrieval |
| `skills.py` | Reading/writing skill files, active-state tracking |
| `generation.py` | The actual streaming generation loop |
| `api.py` | Exposes all of the above to JavaScript under stable method names |
| `runtime.py` | Holds the live `window` reference so other modules can call `evaluate_js` without circular imports |
| `app.py` | Just creates the window and starts the event loop |

### Frontend file responsibilities

`state.js` (shared state/DOM refs/formatting) loads first, followed by
`models.js`, `chat.js`, `documents.js`, `skills.js`, `settings.js`, and
finally `main.js` (which just kicks off the initial data load once
pywebview's bridge is ready). All files share the same global scope
(classic `<script>` tags, not modules), so load order only matters for
top-level code that runs immediately — event handlers and function
calls triggered later work regardless of file order.

All chat, document, and skill data is stored as plain JSON/text files
on disk — no database, no hidden binary formats.

---

## Known limitations and troubleshooting

**GPU is slower than CPU on typical laptop iGPUs.** Vulkan acceleration
tested slower than pure CPU across all three models on integrated
graphics, due to shared memory bandwidth with the CPU. CPU is the
default; the GPU toggle in Settings is there if your hardware differs.

**Thermal throttling.** After several heavy model runs in a row, a thin
laptop CPU can lower its clock speed to avoid overheating. Speed can
vary noticeably depending on how long the machine has been working.

**DeepSeek-R1 and Norwegian are a bad combination.** Its `<think>`
reasoning is trained heavily on English and becomes unreliable in
Norwegian. Use DeepSeek for English reasoning tasks; use Qwen2.5-7B for
Norwegian.

**Repetition penalty and language slips.** An overly aggressive
`frequency_penalty` was found to push Qwen models into code-switching
to Chinese mid-reply once common words became "too expensive" to
repeat. Fixed by keeping `frequency_penalty` low (0.05) and relying more
on `repeat_penalty` (1.1) — see `generation.py`.

**Multiple system messages confuse smaller models.** Document context,
skills, and the compression summary are all merged into a single
system message rather than appended as separate ones — sending several
system-role messages was found to make smaller models hallucinate
nonsensical "policy" responses.

**Prompts to the models are written in English.** The main system
prompt, the utility-model prompts (conversation compression, document
summaries), the "continue where you left off" prompt, and the RAG /
summary framing sentences are all English — these models follow English
instructions more reliably. Language of the *reply* is not pinned
anywhere: every prompt just tells the model to answer in the language
the user is using, and the summarisers to write in the language of their
source text.

**If a model file isn't found**, the app raises a clear error with the
full path — check Settings → Modeller to confirm the file is actually
being discovered, and that its filename matches what's on disk.

**Existing documents from before the document-library rework won't
carry over** if you're upgrading from an older version of this project
— the storage format changed from per-chat folders to a shared library.
Re-add anything you need.

---

## Possible future improvements

- Support for more file formats in document upload (PDF, DOCX)
- Exporting a conversation to Markdown or PDF
- Adjustable `TOP_K_CHUNKS` and chunk size from the Settings UI, instead
  of fixed values in `documents.py`
- A real filesystem watcher for `skills/` instead of the current
  few-second poll
