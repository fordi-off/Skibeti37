"""Create a double-clickable Skibeti37 shortcut, once per machine.

Run it from the project folder:

    python make-shortcut.py

It drops "Skibeti37.lnk" in the folder that contains this project and on
the Desktop. The shortcut launches the app with no console window and can
then be moved anywhere - it points back to this folder by absolute path.

Windows only. Uses only the standard library (it shells out to the
built-in PowerShell to write the .lnk); if that is blocked it prints
instructions for making the shortcut by hand.
"""

import os
import subprocess
import sys

APP_NAME = "Skibeti37"
HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, f"{APP_NAME}.pyw")

_pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
PYTHONW = _pyw if os.path.isfile(_pyw) else sys.executable


def _q(value):
    """Quote a string as a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def _shortcut_block(lnk_path):
    return "; ".join([
        f"$s = $W.CreateShortcut({_q(lnk_path)})",
        f"$s.TargetPath = {_q(PYTHONW)}",
        f'$s.Arguments = {_q(chr(34) + LAUNCHER + chr(34))}',
        f"$s.WorkingDirectory = {_q(HERE)}",
        f"$s.IconLocation = {_q(PYTHONW + ',0')}",
        "$s.Description = 'Skibeti37 - lokal modell-lab'",
        "$s.WindowStyle = 1",
        "$s.Save()",
    ])


def _manual_instructions():
    print(
        "\nMake the shortcut by hand instead (about 15 seconds):\n"
        f"  1. Open the folder that contains this project.\n"
        f"  2. Right-click {APP_NAME}.pyw  ->  Send to  ->  Desktop (create shortcut).\n"
        "  3. Move that shortcut wherever you want it."
    )


def main():
    if os.name != "nt":
        print("This helper only works on Windows.")
        return
    if not os.path.isfile(LAUNCHER):
        print(f"Can't find {APP_NAME}.pyw next to this script - run it from the project folder.")
        return

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    parent = os.path.dirname(HERE)
    places = [p for p in (parent, desktop) if os.path.isdir(p)]
    targets = list(dict.fromkeys(os.path.join(p, f"{APP_NAME}.lnk") for p in places))
    if not targets:
        print("Found nowhere to put the shortcut (no parent folder, no Desktop).")
        _manual_instructions()
        return

    script = "$W = New-Object -ComObject WScript.Shell; " + "; ".join(
        _shortcut_block(t) for t in targets
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc)).strip()
        print("Couldn't create the shortcut automatically.")
        if detail:
            print("  " + detail.replace("\n", "\n  "))
        _manual_instructions()
        return

    print("Created:")
    for target in targets:
        print("  " + target)


if __name__ == "__main__":
    main()
