# Building SyncDrive Studio

## Why your last build showed "watchdog is not installed/bundled"

`main.py` does this at startup:

```python
try:
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
```

If that import fails inside the compiled `.exe`, real-time (on-file-change)
sync silently can't work — even if `watchdog` is installed in your normal
Python environment and `python main.py` runs fine. This happens because:

1. The build environment used to run `pyinstaller` didn't have `watchdog`
   installed (most common), **or**
2. `watchdog` was installed, but PyInstaller's static analyzer missed its
   platform-specific observer backend (it's chosen at runtime, not via a
   plain top-level import), so it wasn't bundled into the `.exe`.

## Correct build steps

```bash
# 1. Use a clean virtual environment
python -m venv build_env
build_env\Scripts\activate        # Windows
# source build_env/bin/activate   # macOS/Linux

# 2. Install exact dependencies (includes watchdog + pyinstaller)
pip install -r requirements.txt

# 3. Build using the provided spec file (NOT `pyinstaller main.py` directly —
#    the spec forces every watchdog backend submodule to be bundled)
pyinstaller syncdrive_studio.spec

# Output: dist/SyncDriveStudio.exe
```

## Verifying it worked

Run the built `.exe` and check the "Auto-Sync" status in the left panel with
an `on_file_change` job configured against a folder that exists:

- **"👁️ Auto-Sync Active (N Task[s])"** — watchdog bundled correctly.
- **"⚠️ Auto-Sync: N issue(s) — see log"** — check the log panel; it will
  now name the exact problem (missing module vs. missing source folder vs.
  watcher start failure) instead of failing silently.

If you still see the "watchdog is not installed/bundled" warning after
building with the spec file, run once with `console=True` in
`syncdrive_studio.spec` and re-run the `.exe` from a terminal — the console
will show the real ImportError/traceback, which is the fastest way to see
exactly what's missing.
