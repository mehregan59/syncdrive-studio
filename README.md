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

You don't need any programming experience for this — just follow the steps
**exactly as written**, including which commands do and don't start with
`python`. It only works on **Windows**.

**1. Install Python** (skip if you already have it)
Go to [python.org/downloads](https://www.python.org/downloads/), download
the latest version, and run the installer.
⚠️ **On the first install screen, check the box "Add python.exe to PATH"**
before clicking Install — this is the step people usually miss.

**2. Download this project**
Click the green **Code** button at the top of this page → **Download ZIP** →
unzip it somewhere easy to find, like your Desktop.
*(Or, if you have Git: `git clone https://github.com/mehregan59/syncdrive-studio.git`)*

**3. Open a terminal in that folder**
In the unzipped folder, click the address bar at the top of File Explorer,
type `cmd`, and press Enter. A black terminal window will open already
pointed at the right folder.

**4. Install the required packages**
Copy this whole line, paste it into the terminal, and press Enter:
```bash
pip install -r requirements.txt
```
This starts with `pip`, not `python` — type it exactly like that. It'll
print a bunch of text while it downloads things; that's normal. Wait for it
to finish and give you a new blank line before continuing.

**5. Build the app**
Copy this whole line, paste it into the terminal, and press Enter:
```bash
python -m PyInstaller syncdrive_studio.spec
```
This one *does* start with `python -m` — don't leave that part out, and
don't add an extra `python` in front of the whole thing either (a command
like `python pyinstaller syncdrive_studio.spec` will fail with
`can't open file 'pyinstaller'`, because `pyinstaller` isn't a script for
Python to open — it's the name of the tool itself).

This takes a minute or two and prints a lot of text — that's normal. When it
finishes, your app is at:
```
dist\SyncDriveStudio.exe
```
That `.exe` is the finished program — copy it wherever you like and run it.

> ⚠️ Don't build with `python -m PyInstaller main.py` (pointing at `main.py`
> instead of `syncdrive_studio.spec`) — it skips a setting the `.spec` file
> adds, and real-time file watching silently won't work in the result. See
> **[BUILD.md](./BUILD.md)** for why, and how to tell if this happened to you.

**Prefer to just run it without building an .exe?**
```bash
pip install -r requirements.txt
python main.py
```

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

This project is licensed under the **[Apache License 2.0](./LICENSE)**.
You're free to use, modify, and redistribute it — including commercially —
under these conditions:

- **Keep the copyright and license notices** in the source.
- **Note any changes you made** to the files you redistribute.
- **Carry forward the [`NOTICE`](./NOTICE) file** in any distribution of this
  software or a derivative of it (Apache 2.0 §4(d)). This is what makes
  crediting the original project a real requirement rather than just a
  courtesy — the `NOTICE` file points back here:
  👉 https://github.com/mehregan59/syncdrive-studio

Apache 2.0 also includes an explicit patent grant, protecting anyone who
uses this code from patent claims by its contributors.

---

## Issues & contributions

Found a bug or have a feature request? Open an issue on GitHub:
https://github.com/mehregan59/syncdrive-studio/issues
