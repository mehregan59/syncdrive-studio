# SyncDrive Studio

A free, open-source Windows app that **backs up one folder (Main) to another (Backup)** —
built with Python and PyQt6. Simple on purpose: two folders, one direction, nothing erased.

---

## How it works

1. Pick your **Main** folder (the original files) and your **Backup** folder.
2. Press **Analyze** — nothing is changed. You see a list of what would happen.
3. Review the list and press **Start Backup**. A progress bar and a log show what is happening.

**Files only go Main ➜ Backup.** Main is only read.

| Situation | What happens |
|---|---|
| File is new in Main | Copied to Backup |
| File changed in Main (Main is newer) | New version copied to Backup; the **old Backup version is kept** in `Backup/.backup_versions/<date>/` |
| File exists only in Backup | **You choose** per file (or all at once): leave it, move it to `Backup/.backup_trash/<date>/`, or copy it to Main |
| File differs and the Backup copy is **newer or the same date** (a conflict) | **You choose**: keep Main's version, or keep Backup's version. The list shows which side is NEWER / older |
| File is identical | Nothing |

**How files are compared:** different size = changed. Same size and same date = identical.
Same size but different date = the content (SHA-256) is compared, so a file that was only
"touched" is not copied again. Every copy can also be verified after writing (on by default).

**Nothing is erased.** Old versions and trash live inside the Backup folder. Use the
**Old versions / Trash** buttons to open them and restore anything. Only the **Empty…**
buttons erase, and only after you confirm (default answer: No).

Extra safety: a backup is refused if a folder can't be fully read, if Main is empty while Backup
isn't, or if one folder is inside the other. Copies are written to a temp file, verified, then
moved into place, so a failed copy never damages the existing file.

Settings (your two folders) and a `backup.log` are kept in the app's config folder. Only one
copy of the app can run at a time.

---

## ⚠️ Disclaimer

**This software is provided "AS IS", without warranty of any kind.** The author(s) and
contributors accept **no liability** for any data loss, corruption, or other damage. **You use it
entirely at your own risk.** Always keep an independent copy of important data, and use
**Analyze** before every backup.

---

## Installing (for end users)

If you were given a pre-built `SyncDriveStudio.exe`, just run it. On first
launch it will:

1. Show a short setup wizard — choose **Portable Mode** (no system changes)
   or **System Install Mode** (copies itself to `Program Files`, adds Start
   Menu/Desktop shortcuts, and registers itself in Windows **Settings → Apps**
   for normal uninstalling).
2. Ask you to accept the disclaimer above.

**Uninstalling:** use the "Uninstall SyncDrive Studio" shortcut in the Start
Menu, or find it in Windows **Settings → Apps**. Uninstalling never touches your Main or Backup folders.

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

**Prefer to just run it without building an .exe?**
```bash
pip install -r requirements.txt
python main.py
```

> ⚠️ **Rebuilding after already running the app once?** If you see
> `PermissionError: Access is denied` on `dist\SyncDriveStudio.exe`, the old build is still
> running — close it (or end `SyncDriveStudio.exe` in Task Manager) and rebuild.

---

## Project structure

| File | Purpose |
|---|---|
| `main.py` | The PyQt6 window, setup wizard, single-instance guard, install/uninstall flow |
| `engine.py` | Scanning, comparing (size/date/hash), and the safe copy / versions / trash operations |
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
