"""The Kode page: read a project folder, hand its files + a task to the
model, and write back the files the model proposes - always after the user
confirms each change in a diff view. No command execution. Also stores the
per-folder work sessions (name + task/summary history)."""

import json
import os
import time
import uuid

import webview

import runtime

MAX_TEXT_FILES = 20
MAX_FILE_BYTES = 8000          # bigger text files are listed but their content isn't sent
MAX_TOTAL_BYTES = 48_000      # ~12k tokens of project content

TEXT_EXT = {
    ".html", ".htm", ".css", ".js", ".mjs", ".jsx", ".ts", ".tsx",
    ".py", ".md", ".txt", ".json", ".csv", ".tsv", ".xml", ".svg",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".go", ".rs",
    ".php", ".sql", ".sh", ".bat", ".ps1", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".gitignore",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             "dist", "build", ".idea", ".vscode", ".mypy_cache"}

_LANG = {
    "py": "python", "js": "javascript", "mjs": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript", "html": "html", "htm": "html",
    "css": "css", "json": "json", "md": "markdown", "sh": "bash", "bat": "dos",
    "ps1": "powershell", "yml": "yaml", "yaml": "yaml", "sql": "sql", "xml": "xml",
    "java": "java", "c": "c", "h": "c", "cpp": "cpp", "cs": "csharp", "go": "go",
    "rs": "rust", "rb": "ruby", "php": "php",
}

SESSIONS_DIR = "./code_sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

_project = {"path": None}


# ---------------- work sessions ----------------

def _session_path(sid):
    return os.path.join(SESSIONS_DIR, f"{sid}.json")


def _load_raw(sid):
    try:
        with open(_session_path(sid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def list_sessions():
    out = []
    for fn in os.listdir(SESSIONS_DIR):
        if not fn.endswith(".json"):
            continue
        d = _load_raw(fn[:-5])
        if d and d.get("id"):
            out.append({"id": d["id"], "name": d.get("name") or "Uten navn",
                        "folder": d.get("folder"), "updated_at": d.get("updated_at", 0)})
    out.sort(key=lambda s: s["updated_at"], reverse=True)
    return out


def load_session(sid):
    return _load_raw(sid)


def save_session(sid, name, folder, history):
    sid = sid or str(uuid.uuid4())
    data = {"id": sid, "name": name or "Uten navn", "folder": folder,
            "history": history or [], "updated_at": time.time()}
    with open(_session_path(sid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"id": sid}


def rename_session(sid, name):
    d = _load_raw(sid)
    if not d:
        return False
    d["name"] = name
    with open(_session_path(sid), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return True


def delete_session(sid):
    p = _session_path(sid)
    if os.path.isfile(p):
        os.remove(p)
    return True


def set_folder(path):
    if not path or not os.path.isdir(path):
        return {"error": "Mappen finnes ikke lenger."}
    _project["path"] = path
    return read_project()


def _lang_of(rel):
    return _LANG.get(os.path.splitext(rel)[1].lower().lstrip("."), "text")


def pick_folder():
    res = runtime.window.create_file_dialog(webview.FOLDER_DIALOG)
    if not res:
        return {"cancelled": True}
    _project["path"] = res[0] if isinstance(res, (list, tuple)) else res
    return read_project()


def _iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            yield rel, full


def read_project():
    root = _project["path"]
    if not root or not os.path.isdir(root):
        return {"path": None, "files": [], "total_bytes": 0, "too_big": False}

    files, total, text_count = [], 0, 0
    for rel, full in _iter_files(root):
        is_text = os.path.splitext(rel)[1].lower() in TEXT_EXT
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        entry = {"rel": rel, "size": size, "lang": _lang_of(rel),
                 "text": is_text, "included": False, "content": None}
        if is_text:
            text_count += 1
            if size <= MAX_FILE_BYTES and total + size <= MAX_TOTAL_BYTES:
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        entry["content"] = f.read()
                    entry["included"] = True
                    total += size
                except OSError:
                    pass
        files.append(entry)

    files.sort(key=lambda e: e["rel"].lower())
    too_big = text_count > MAX_TEXT_FILES or total >= MAX_TOTAL_BYTES
    return {"path": root, "files": files, "total_bytes": total, "too_big": too_big}


def _manifest(files):
    parts = []
    for e in files:
        if e["included"] and e["content"] is not None:
            parts.append(f"--- FILE: {e['rel']} ---\n{e['content']}")
        elif e["text"]:
            parts.append(f"--- FILE: {e['rel']} --- (for stor, innhold utelatt - IKKE skriv om denne)")
        else:
            parts.append(f"--- FILE: {e['rel']} --- (binær - ignorer)")
    return "\n\n".join(parts) if parts else "(mappen er tom)"


PLAN_SYS = (
    "You are planning a small coding change for a student, on a weak computer. "
    "You are given the current project files and a task. Produce a SHORT "
    "implementation plan: a bullet list of the files to create, modify or "
    "delete, one line each on what goes in it, plus any key decision. No code. "
    "Do only what the task asks - do not over-engineer. Write the plan in the "
    "same language as the task."
)

CODE_SYS = (
    "Implement the plan for the student's project. Rules:\n"
    "- Output EVERY new or changed file in full, each as its own fenced code "
    "block whose FIRST line inside the block is exactly `FILE: <relative/path>`.\n"
    "- Whole files only. No placeholders, no `...`, no `// unchanged`.\n"
    "- Only include files you actually change. Never rewrite a file marked "
    "'innhold utelatt' or 'binær'.\n"
    "- To delete a file, put a line `DELETE: <relative/path>` on its own, "
    "outside any code block.\n"
    "- After the code blocks, add a section headed `Endringer:` in the task's "
    "language - a few sentences on what you changed and how to try it (which "
    "file to open, or which command to run). No code in that section."
)


def _history(hist):
    return [m for m in hist if isinstance(m, dict) and m.get("role") in ("user", "assistant")]


def plan_messages(task, hist):
    files = read_project().get("files", [])
    return [{"role": "system", "content": PLAN_SYS}] + _history(hist) + [
        {"role": "user", "content": f"Prosjektfiler:\n\n{_manifest(files)}\n\n---\n\nOppgave:\n{task}"}
    ]


def code_messages(task, plan, hist):
    files = read_project().get("files", [])
    return [{"role": "system", "content": CODE_SYS}] + _history(hist) + [
        {"role": "user",
         "content": f"Prosjektfiler:\n\n{_manifest(files)}\n\n---\n\nOppgave:\n{task}\n\n---\n\nPlan:\n{plan}"}
    ]


def _inside(root_abs, target):
    try:
        return os.path.commonpath([root_abs, target]) == root_abs
    except ValueError:
        return False


def apply_changes(changes, deletions):
    root = _project["path"]
    if not root or not os.path.isdir(root):
        return {"error": "Ingen mappe valgt."}
    root_abs = os.path.abspath(root)
    results = []

    for rel in deletions or []:
        target = os.path.abspath(os.path.join(root_abs, rel))
        if not _inside(root_abs, target):
            results.append({"rel": rel, "ok": False, "msg": "utenfor mappen"})
            continue
        try:
            if os.path.isfile(target):
                os.remove(target)
            results.append({"rel": rel, "ok": True, "msg": "slettet"})
        except OSError as e:
            results.append({"rel": rel, "ok": False, "msg": str(e)})

    for ch in changes or []:
        rel, content = ch.get("rel", ""), ch.get("content", "")
        target = os.path.abspath(os.path.join(root_abs, rel))
        if not rel or not _inside(root_abs, target):
            results.append({"rel": rel, "ok": False, "msg": "utenfor mappen"})
            continue
        try:
            os.makedirs(os.path.dirname(target) or root_abs, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            results.append({"rel": rel, "ok": True, "msg": "skrevet"})
        except OSError as e:
            results.append({"rel": rel, "ok": False, "msg": str(e)})

    return {"results": results, "project": read_project()}
