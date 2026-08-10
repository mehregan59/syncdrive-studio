# SyncDrive Studio

A free, open-source Windows desktop app for syncing files between two folders
— built with Python and PyQt6. It supports one-way backup, mirroring, and
two-way sync, with manual, scheduled, real-time, and drive-connect triggers.

---

## What it does

SyncDrive Studio lets you set up **sync tasks** between a source and a target
folder. Each task has:

- **A sync mode:**
  - **One-Way Backup** — copies new/changed files from source → target. Never deletes anything.
  - **One-Way Mirror** — makes the target an exact copy of the source, including deleting files from the target that were removed from the source.
  - **Two-Way Sync** — changes on either side get copied to the other, and deletions on one side get propagated to the other (tracked within the current app session).

- **A trigger:**
  - **Manual** — you click Analyze or Sync Now yourself.
  - **Interval** — runs automatically every N minutes (with quick presets: 5m/15m/30m/1h/6h/24h).
  - **On File Change** — watches the source folder in real time (via [watchdog](https://pypi.org/project/watchdog/)) and syncs shortly after a change settles.
  - **On Drive Connect** — runs when a matching external/USB drive is plugged in.

- **Analyze (Preview)** — shows exactly what a sync *would* do (copies, deletes) without touching any files, so you can check before committing.

Jobs are saved automatically (`jobs.json` in the app's config folder) and
reloaded the next time you open the app. The app also has a system tray icon
so it can keep watching for changes in the background, and only one instance
can run at a time — opening it again just brings the existing window to the
front instead of starting a duplicate.

---

## ⚠️ Disclaimer

**This software is provided "AS IS", without warranty of any kind.** File
sync tools — especially in **Mirror** and **Two-Way Sync** modes — can
**delete or overwrite files** as part of normal operation. That's the
intended behavior, not a bug, but it means a misconfigured job (e.g. wrong
source/target) can cause real data loss.

- **Use Analyze (Preview) before your first live sync on any new job**, so you can see exactly what will happen before it happens.
- **Keep independent backups of anything important.** Do not rely on this tool as your only backup strategy.
- The author(s) and contributors accept **no liability** for any data loss, corruption, or other damage resulting from the use of this software. **You use it entirely at your own risk.**

This mirrors the disclaimer already shown in the app's own Setup Wizard on
first run.

---

## Installing (for end users)

If you were given a pre-built `SyncDriveStudio.exe`, just run it. On first
launch it will:

1. Show a short setup wizard — choose **Portable Mode** (no system changes)
   or **System Install Mode** (copies itself to `Program Files`, adds Start
   Menu/Desktop shortcuts, and registers itself in Windows **Settings → Apps**
   for normal uninstalling).
2. Ask you to accept the disclaimer above.

If it tells you a real-time watching component (`watchdog`) isn't available,
see [BUILD.md](./BUILD.md) — that means the `.exe` wasn't built with the
provided spec file (see below).

**Uninstalling:** use the "Uninstall SyncDrive Studio" shortcut in the Start
Menu, find it in Windows **Settings → Apps**, or right-click the system tray
icon and choose **Uninstall SyncDrive Studio...**.

---

## Building it yourself

You'll need Python 3.10+ on Windows.

```bash
# 1. Clone the repo
git clone https://github.com/mehregan59/syncdrive-studio.git
cd syncdrive-studio

# 2. (Recommended) use a clean virtual environment
python -m venv build_env
build_env\Scripts\activate

# 3. Install dependencies — this includes PyInstaller and watchdog
pip install -r requirements.txt

# 4. Build using the provided spec file (NOT `pyinstaller main.py` directly —
#    the spec file explicitly bundles watchdog's platform-specific backend,
#    which PyInstaller's automatic scanner tends to miss)
pyinstaller syncdrive_studio.spec
```

The finished executable is at `dist/SyncDriveStudio.exe`.

**Running from source instead of building an .exe:**

```bash
pip install -r requirements.txt
python main.py
```

For a deeper explanation of *why* the spec file matters (and how to debug a
build that still reports `watchdog` as missing), see
**[BUILD.md](./BUILD.md)**.

---

## Project structure

| File | Purpose |
|---|---|
| `main.py` | The PyQt6 application: UI, job management, scheduling, real-time watching, single-instance guard, install/uninstall flow |
| `engine.py` | The actual sync logic — scans folders, plans copy/delete actions, tracks state for two-way sync |
| `models.py` | Data models for sync jobs (pydantic) |
| `drive_detector.py` | Detects external/USB drives connecting, for the "On Drive Connect" trigger |
| `uninstall.py` | Thin forwarder to the uninstall logic in `main.py`, for anyone running from source |
| `syncdrive_studio.spec` | PyInstaller build configuration |
| `requirements.txt` | Python dependencies |

---

## License & attribution

This project is licensed under the **[MIT License](./LICENSE)** — you're
free to use, modify, and redistribute it, including commercially, as long as
the original copyright notice is kept (standard MIT terms).

**If you reuse a meaningful part of this code in your own project, please
credit it and link back to this repository:**
👉 https://github.com/mehregan59/syncdrive-studio

It's not a legal requirement beyond what MIT already asks for (keeping the
copyright notice), but it's appreciated and helps others find the original
source.

---

## Issues & contributions

Found a bug or have a feature request? Open an issue on GitHub:
https://github.com/mehregan59/syncdrive-studio/issues
