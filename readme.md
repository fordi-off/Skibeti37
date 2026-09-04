# Skibeti37 — local AI lab

A fully local chat app for running and comparing language models on your
own machine — no internet, no cloud services, and no data ever leaves the
PC. Built for a laptop with integrated graphics (AMD Ryzen 5 7530U, 15GB
RAM) — but works on most modern laptops/desktops.

The app opens as its own window (via `pywebview`), not in a browser, and
requires no visible server to start manually.

---

## Table of contents

1. [System requirements](#system-requirements)
2. [Folder structure](#folder-structure)
3. [Installation](#installation)
4. [Models you need](#models-you-need)
5. [Running the app](#running-the-app)
6. [Features in detail](#features-in-detail)
7. [How document RAG works](#how-document-rag-works)
8. [Technical architecture](#technical-architecture)
9. [Known limitations and troubleshooting](#known-limitations-and-troubleshooting)
10. [Other scripts in the project](#other-scripts-in-the-project)
11. [Possible future improvements](#possible-future-improvements)

---

## System requirements

- **Python 3.10–3.13** (tested with 3.13)
- **Windows** (the instructions below are Windows-specific, but the app is
  pure Python and should work on macOS/Linux with the same setup)
- At least **8GB of free RAM** beyond what the system itself uses — 7B
  models in 4-bit quantization use about 5-6GB
- **No dedicated GPU required.** Testing showed that integrated graphics
  (Vulkan acceleration) was actually **slower** than pure CPU on this type
  of machine (shared memory bandwidth between CPU and iGPU) — the app
  therefore runs everything on CPU by default

---

## Folder structure

```
your-folder/
├── app.py                  ← main program, run this
├── requirements.txt
├── README.md                ← this file
├── static/
│   ├── index.html            ← the entire interface (HTML/CSS/JS)
│   └── marked.min.js         ← markdown rendering, loaded locally (offline)
├── models/                  ← your downloaded .gguf model files (see below)
├── chats/                   ← created automatically - one .json file per conversation
└── documents/                ← created automatically - documents, sorted per chat ID
```

`chats/` and `documents/` are created automatically the first time you run
the app. Both are plain, readable JSON — you can open them in a text
editor, back them up, or delete them manually if needed.

---

## Installation

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` points to a prebuilt CPU-wheel index for
`llama-cpp-python`, which avoids a common Windows problem: a normal
installation tries to build from source, which often fails without admin
rights due to overly long file paths in Windows (`vendor/llama.cpp/...`).
This method avoids that problem entirely.

If installation still fails, try explicitly:

```bash
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
pip install pywebview numpy
```

### 2. Create the `models` folder

```bash
mkdir models
```

Download the model files (see the next section) and place them there.

---

## Models you need

All are GGUF files (quantized models optimized for CPU via `llama.cpp`).
Download directly from the Hugging Face website (recommended if
`huggingface-cli` gives you trouble) or via the command line.

| Model | Filename expected by the app | Use case |
|---|---|---|
| **Qwen2.5-1.5B-Instruct** | `qwen2.5-1.5b-instruct-q4_k_m.gguf` | Fast, simple chat (best in English) |
| **Qwen2.5-7B-Instruct** | `qwen2.5-7b-instruct-q4_k_m.gguf` | Default model — best at Norwegian |
| **DeepSeek-R1-Distill-Qwen-7B-Uncensored** | `DeepSeek-R1-Distill-Qwen-7B-Uncensored.i1-Q5_K_M.gguf` | Reasoning/math/logic (English recommended) |
| **nomic-embed-text-v1.5** | `nomic-embed-text-v1.5.Q4_K_M.gguf` | Only for document search (RAG), not a chat model |

Download sources:
- Qwen2.5: `https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF` (and `-1.5B-Instruct-GGUF`)
- DeepSeek-R1 uncensored: `https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-Uncensored-i1-GGUF`
- nomic-embed: `https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF`

The filenames in the table **must match exactly** what's in the `MODELS`
dict at the top of `app.py` — update the filename in the code if you
download a different quantization variant (e.g. Q5 instead of Q4).

---

## Running the app

```bash
python app.py
```

A dedicated window opens immediately — no browser, no `localhost` address
to remember. Models are loaded only when actually used (lazy loading), so
startup is fast.

---

## Features in detail

### Model selection

Three buttons at the top let you switch models at any time, even mid-
conversation:

- **1.5B · fast** — for simple, quick English questions
- **7B · standard** — the main model, clearly best at Norwegian
- **R1 · reasoning** — for math/logic/planning, shows its thinking
  process in a separate field (see below)

### Conversations (left sidebar, top)

- **"+ New"** starts an empty conversation
- Each conversation is automatically saved as its own file in `chats/`
  once the first reply finishes generating
- Click a conversation in the list to reopen it — full history and
  settings (model, language) are restored
- **Double-click the name** to rename the conversation
- The **×** button (shown on hover) permanently deletes the conversation,
  including its associated documents

### Language switch

Two buttons, **Norwegian** / **English**, right below the app title. This
is a **per-conversation** setting: choosing "Norwegian" rewrites the
system prompt to explicitly instruct the model to always answer in
Norwegian, regardless of what language the question is asked in. Solves
the problem where models sometimes answer in English even when the
question was in Norwegian.

The setting is saved with the rest of the conversation and restored when
reopened later. New conversations always start in Norwegian.

### Speed display

Below each reply you'll see something like `7B · standard · 12.4s · 5.8
tok/s`. This is an approximation based on the number of text chunks
received divided by actual elapsed time — reliable enough to compare
models and settings against each other, but not a 100% exact token count.

### Documents and RAG (left sidebar, bottom)

See the dedicated section below — this is the most complex feature in
the app.

### Formatting

Replies from the models are parsed as markdown via `marked.js` (runs
entirely locally, no internet dependency):

- **Code blocks** (\`\`\`) with monospace styling
- **Bold/italic text**
- **Tables**
- **Lists** (bulleted and numbered)
- **Headings**

---

## How document RAG works

RAG = Retrieval-Augmented Generation. Instead of trying to squeeze an
entire book into the model's context window (which is too small anyway —
8192 tokens ≈ 6000 words, while a textbook is easily 20,000+ words), the
following happens:

### When uploading a document (`.txt` or `.md`)

1. **Splitting for search**: the document is split into ~300-word chunks
   with some overlap, and each chunk is turned into an "embedding" (a
   number vector representing the chunk's meaning) via `nomic-embed-text`
2. **Structured summary**: in parallel, a long (400-700 word),
   heading-organized summary is created via a map-reduce process: larger
   chunks (1200 words) are each summarized by Qwen2.5-1.5B, and the
   partial summaries are then merged into one coherent overview. This
   summary is shown **only in the sidebar** for your own reference — it
   is not automatically sent to the main model
3. Status is shown continuously ("Summarizing part 3/8...") and the chat
   is locked (input field and send button disabled) until the process
   finishes

### On every question in the chat

1. Your question is turned into an embedding
2. The **5 most relevant chunks** from all active documents in the
   conversation are retrieved based on similarity to the question
   (cosine similarity)
3. Only these chunks are sent to the main model as context — precise and
   fast, regardless of how large the document is

### Documents are per conversation

Each conversation has its own, separate set of documents (stored in
`documents/<chat-id>/`). Adding a document in one conversation won't
make it appear in another. Deleting a conversation automatically deletes
its associated documents too.

### Per-document checkbox

Lets you toggle a document on/off without deleting it — useful if you
have several documents in the same conversation but only want one of
them used right now.

---

## Technical architecture

No HTTP server, no browser. Communication works like this:

```
static/index.html (JavaScript)
        │
        │  window.pywebview.api.send_message(...)
        ▼
   app.py (Python, the Api class)
        │
        │  runs in its own background thread, calls llama-cpp-python
        ▼
   window.evaluate_js("onChunk(...)")   ← pushes text chunks back to the page live
```

`pywebview` uses Windows' built-in WebView2 component (the same engine as
Edge, but without the browser window around it) and exposes a direct
Python↔JavaScript bridge. Streaming of replies works by Python calling
`window.evaluate_js()` for each text chunk the model generates, which
triggers the `onChunk()` function on the page in real time.

All chat and document data is stored as JSON files on disk — no
database, no hidden binary formats.

---

## Known limitations and troubleshooting

**GPU is slower than CPU on this machine.** Thoroughly tested with
Vulkan acceleration — integrated graphics shares memory bandwidth with
the CPU, so `n_gpu_layers=-1` gave 14-25% *worse* performance than pure
CPU for all three models. The app therefore hardcodes `n_gpu_layers=0`.

**Thermal throttling.** After several heavy model runs in a row, a thin
laptop CPU (like the Ryzen 5 7530U) can automatically lower its clock
speed to avoid overheating. Speed can therefore vary significantly
depending on how long the machine has been working continuously.

**DeepSeek-R1 and Norwegian are a bad combination.** Testing showed that
DeepSeek's `<think>` reasoning often becomes unreliable or outright wrong
when input/output is Norwegian (it's heavily trained on English
reasoning). Recommendation: use DeepSeek only for English reasoning
tasks, and Qwen2.5-7B for everything in Norwegian.

**Repetition and language slips.** An overly aggressive
`frequency_penalty` turned out to push models (especially Qwen, which is
developed by Alibaba) into suddenly code-switching to Chinese mid-reply,
once common Norwegian words became "too expensive" to repeat. Fixed by
lowering `frequency_penalty` to 0.05 and `repeat_penalty` to 1.1 in
`SAMPLING_PARAMS` in `app.py`.

**Multiple system messages confuse smaller models.** Sending document
context as a separate, second system message (instead of merging it with
the first) caused the 1.5B model in particular to hallucinate nonsensical
"privacy/policy" responses. The fix was to always merge everything into
a single system message.

**If a model file isn't found**, the app shows a clear error in the chat
with the full file path — double-check that the filename in the `MODELS`
dict in `app.py` matches exactly what you have in the `models/` folder.

---

## Other scripts in the project

These were built along the way as experiments and benchmarks. They're
not required to run the main app (`app.py`), but are useful references:

| File | What it does |
|---|---|
| `chat_qwen.py` | Simple terminal chat with Qwen2.5-1.5B, no streaming |
| `chat_reasoning.py` | Terminal chat with DeepSeek-R1, shows the thinking block separately |
| `benchmark_qwen.py` | CPU vs GPU speed test for a single model |
| `benchmark_all_models.py` | Compares all three models on 4 test tasks |
| `benchmark_cpu_vs_gpu.py` | Same as above, but in both CPU and GPU mode |
| `benchmark_with_outputs.py` | As above, but saves full response text to a report file |
| `benchmark_norsk.py` | Same benchmark, but with Norwegian test questions |
| `router_agent.py` | Terminal agent that routes between 1.5B and DeepSeek based on complexity |
| `language_router_agent.py` | As above, but locks the model based on detected language |
| `build_book_index.py` / `chat_with_book.py` | Early, standalone RAG exploration (before this was built into the app) |
| `gui_chat.py` | Early Tkinter-based GUI (replaced by `app.py`) |
| `server.py` + old `static/` | Early Flask-based browser version (replaced by the `pywebview` version) |
| `start.bat` | Shortcut made for the Flask version (not needed with `app.py`, which uses no server) |

---

## Possible future improvements

Things worth considering going forward, but not yet built:

- Support for more file formats in document upload (PDF, DOCX)
- Ability to edit/regenerate a single reply in a conversation
- Exporting a conversation to e.g. Markdown or PDF
- Adjustable `TOP_K_CHUNKS` and chunk size from the interface, instead of
  fixed values in the code
- Showing which document excerpts were actually used in a given reply
  (transparency about what the RAG search actually found)