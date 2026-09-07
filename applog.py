"""Plain stdout logging for when the app is run from a terminal
(`python app.py`). Mirrors the load / activity statuses that the
frontend prints to the WebView dev console. When launched windowless
via Skibeti37.pyw there's simply no console to see it - that's fine.

Kept deliberately tiny: one prefixed, timestamped line per event.
"""

import sys
import time

_PREFIX = "[skibeti37"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"{_PREFIX} {ts}] {msg}", flush=True)
    except (OSError, ValueError):
        # stdout closed / detached (e.g. pythonw) - nothing to do.
        pass


def error(msg):
    log(f"ERROR: {msg}")
