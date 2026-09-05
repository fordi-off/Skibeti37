"""Shared reference to the pywebview window, set by app.py at startup.
Other modules import this to call window.evaluate_js(...) and
window.create_file_dialog(...) without circular imports."""

window = None
