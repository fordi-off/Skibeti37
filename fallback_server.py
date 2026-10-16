"""Fallback launch path for machines where pywebview's/llama-cpp-python's
native DLLs are blocked (e.g. Windows Application Control policies on a
managed/corporate PC - see app.py). Serves the exact same frontend over
plain HTTP to the user's regular browser instead of an embedded webview
window, and exposes Api's methods through a small JSON-RPC-style endpoint.

Nothing in this module loads a GGUF model or touches llama_cpp/numpy -
actual inference, embeddings and RAG ranking run as WebAssembly inside the
browser tab instead (see static/js/wasm-engine.js and static/js/bridge.js).
This module only serves files and persists chats/documents/settings/skills,
all of which are plain Python/JSON with no native dependency.
"""

import inspect
import json
import mimetypes
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import applog
import config
from api import Api

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT_RANGE = range(8787, 8797)

_api = Api()
# Only Api's own declared methods are ever callable through /api/<name> -
# never arbitrary attribute access via getattr, even though this only ever
# listens on 127.0.0.1.
_EXPOSED_METHODS = {
    name for name, _ in inspect.getmembers(Api, predicate=inspect.isfunction)
    if not name.startswith("_")
}


def _find_free_port():
    for port in PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return PORT_RANGE[0]


class Handler(BaseHTTPRequestHandler):
    server_version = "Skibeti37Fallback/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # applog already covers what matters; skip the default stderr spam

    # ---------- shared helpers ----------

    def _send_cors_headers(self):
        # Required for SharedArrayBuffer, which wllama's multi-thread WASM
        # build needs to use more than one CPU core.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".wasm"):
            content_type = "application/wasm"

        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                spec = range_header.split("=", 1)[1].split("-")
                if spec[0]:
                    start = int(spec[0])
                if spec[1]:
                    end = int(spec[1])
                status = 206
            except (ValueError, IndexError):
                start, end, status = 0, size - 1, 200

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._send_cors_headers()
        self.end_headers()

        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionAbortedError):
                    break
                remaining -= len(chunk)

    # ---------- routing ----------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"

        if path.startswith("/models/"):
            fname = os.path.basename(path[len("/models/"):])
            self._send_file(os.path.join(config.MODELS_DIR, fname))
            return

        safe_path = os.path.normpath(path).lstrip("/\\")
        full_path = os.path.join(STATIC_DIR, safe_path)
        if not os.path.abspath(full_path).startswith(os.path.abspath(STATIC_DIR)):
            self.send_error(403)
            return
        self._send_file(full_path)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        name = self.path[len("/api/"):]
        if name not in _EXPOSED_METHODS:
            self._send_json({"error": f"unknown method: {name}"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            args = payload.get("args", [])
            result = getattr(_api, name)(*args)
            self._send_json({"result": result})
        except Exception as exc:
            applog.error(f"fallback api call failed ({name}): {exc}")
            self._send_json({"error": str(exc)})

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception as exc:
        applog.error(f"could not auto-open a browser ({exc}) - open {url} manually")


def run():
    port = _find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    applog.log(f"fallback mode: serving {url} (pywebview/llama.cpp unavailable on this machine)")
    applog.log("inference, embeddings and document search now run as WebAssembly inside your browser tab")
    threading.Timer(0.5, lambda: _open_browser(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
