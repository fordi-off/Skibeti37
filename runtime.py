"""Delt referanse til pywebview-vinduet, satt av app.py ved oppstart.
Andre moduler importerer denne for å kalle window.evaluate_js(...) og
window.create_file_dialog(...) uten sirkulære imports."""

window = None
