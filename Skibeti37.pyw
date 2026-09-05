"""Double-click launcher for Skibeti37.

A .pyw file runs through pythonw.exe, so the app starts with no console
window - and unlike a .bat/.cmd it is not blocked by the script-execution
policies common on school and other managed Windows machines.

It works no matter where it is launched from: it switches to its own
folder and starts app.py's main().
"""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
os.chdir(_here)
sys.path.insert(0, _here)

import app

app.main()
