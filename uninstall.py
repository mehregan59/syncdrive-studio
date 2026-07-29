"""
Legacy entry point, kept for anyone running from source instead of the built
.exe. The real, complete uninstall logic (removes shortcuts, the Windows
"Add or Remove Programs" entry, saved job data, and — for a System Install —
the installed program folder) now lives in main.py so there's only one
implementation to keep correct. This just forwards to it.

The .exe itself is launched with `--uninstall` from the Start Menu
"Uninstall SyncDrive Studio" shortcut and from the registered uninstaller
entry in Windows Settings > Apps — most people should never need to run this
file directly.
"""
import sys
import subprocess
import pathlib

if __name__ == "__main__":
    main_py = pathlib.Path(__file__).parent / "main.py"
    subprocess.run([sys.executable, str(main_py), "--uninstall"])
