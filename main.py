"""
SyncDrive Studio — simple one-way backup:  Main  ➜  Backup.

Main is the original. Backup receives new and changed files from Main, never
the other way around (except when YOU explicitly choose it for a single file).
Nothing is ever erased: old versions and "deleted" files go to folders inside
the Backup that you can open, restore from, and empty yourself.

Licensed under the Apache License 2.0 — see LICENSE / NOTICE.
https://github.com/mehregan59/syncdrive-studio
"""
import sys
import os
import time
import json
import shutil
import subprocess
import importlib.util
import multiprocessing
import pathlib
from datetime import datetime
from enum import Enum
from typing import List

# MUST call freeze_support at script load time for Windows PyInstaller single-file builds
if __name__ == "__main__":
    multiprocessing.freeze_support()

REQUIRED_PACKAGES = {"PyQt6": "PyQt6"}


def auto_install_dependencies():
    missing = [pkg for pkg, imp in REQUIRED_PACKAGES.items() if importlib.util.find_spec(imp) is None]
    for pkg in missing:
        print(f"Installing {pkg} ...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        except Exception as e:
            print(f"Could not install {pkg}: {e}\nRun:  python -m pip install {pkg}")
            sys.exit(1)


if not getattr(sys, "frozen", False):
    auto_install_dependencies()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QPlainTextEdit, QCheckBox, QComboBox, QDialog, QLineEdit, QMessageBox,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QFrame, QHeaderView, QSplitter,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QIcon, QColor, QDesktopServices
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

import engine as eng


GOODSYNC_STUDIO_STYLESHEET = """
QMainWindow, QDialog, QMessageBox {
    background-color: #000000;
}

QWidget {
    color: #E6E8F5;
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 12px;
}

/* Top Toolbar Ribbon */
#ToolbarFrame {
    background-color: #0A0A0C;
    border-bottom: 1px solid #262838;
    padding: 8px 14px;
}

QPushButton#RibbonBtn {
    background-color: #23253590;
    color: #E6E8F5;
    border: 1px solid #33354A;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton#RibbonBtn:hover {
    background-color: #6C5CE7;
    border-color: #8778F0;
    color: #FFFFFF;
}

QPushButton#RibbonBtn:disabled {
    color: #565875;
    border-color: #262838;
}

QPushButton#RibbonBtnPrimary {
    background-color: #6C5CE7;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 700;
    font-size: 12px;
}

QPushButton#RibbonBtnPrimary:hover {
    background-color: #7D6EEB;
}

QPushButton#RibbonBtnPrimary:disabled {
    background-color: #2C2D3D;
    color: #5C5E78;
}

QPushButton#PresetBtn {
    background-color: #1E2030;
    color: #B8BAD6;
    border: 1px solid #2E3046;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 11px;
}

QPushButton#PresetBtn:checked, QPushButton#PresetBtn:hover {
    background-color: #6C5CE7;
    color: #FFFFFF;
    border-color: #8778F0;
}

QPushButton#StopBtn {
    background-color: #E74C3C;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 700;
    font-size: 12px;
}

QPushButton#StopBtn:hover {
    background-color: #FF5252;
}

QPushButton#StopBtn:disabled {
    background-color: #23253A;
    color: #565875;
}

/* Compact Connection Header Bar */
#ConnectionHeader {
    background-color: #0B0B0D;
    border-bottom: 1px solid #262838;
    padding: 8px 14px;
}

#PathCard {
    background-color: #131316;
    border: 1px solid #2A2C40;
    border-radius: 8px;
    padding: 5px 12px;
}

/* Stat / Dashboard Cards */
#StatCard {
    background-color: #0E0E11;
    border: 1px solid #262838;
    border-radius: 10px;
    padding: 8px 14px;
}

#StatValueLbl {
    font-size: 18px;
    font-weight: 800;
    color: #FFFFFF;
}

#StatCaptionLbl {
    font-size: 10px;
    color: #8A8CAD;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}

/* Trees & Tables */
QTreeWidget, QTableWidget, QPlainTextEdit, QListWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background-color: #0B0B0D;
    border: 1px solid #262838;
    border-radius: 8px;
    padding: 5px;
    color: #FFFFFF;
    selection-background-color: #6C5CE7;
}

QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
    border: none;
    width: 18px;
}

QHeaderView::section {
    background-color: #131316;
    color: #8A8CAD;
    padding: 7px;
    border: none;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}

QTableWidget::item, QTreeWidget::item {
    padding: 6px 4px;
    border-bottom: 1px solid #1A1C29;
}

QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #6C5CE7;
    color: #FFFFFF;
}

QGroupBox {
    border: 1px solid #262838;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 12px;
    font-weight: 700;
    color: #B8BAD6;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid #3A3C56;
    background-color: #0B0B0D;
}

QCheckBox::indicator:checked {
    background-color: #00B894;
    border-color: #00B894;
}

/* Progress Bar */
QProgressBar {
    border: none;
    border-radius: 8px;
    background-color: #0B0B0D;
    text-align: center;
    color: white;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #00B894;
    border-radius: 8px;
}

QToolTip {
    background-color: #1E1F2E;
    color: #FFFFFF;
    border: 1px solid #6C5CE7;
    border-radius: 6px;
    padding: 6px;
}
"""

class AppMode(str, Enum):
    PORTABLE = "portable"
    INSTALLED = "installed"


def create_windows_shortcut(target_exe: pathlib.Path, shortcut_path: pathlib.Path, icon_path: pathlib.Path = None, arguments: str = ""):
    if not sys.platform.startswith("win"):
        return

    icon_str = f'oLink.IconLocation = "{icon_path}"' if icon_path and icon_path.exists() else ''
    args_str = f'oLink.Arguments = "{arguments}"' if arguments else ''
    vbs_script = f"""
    Set oWS = WScript.CreateObject("WScript.Shell")
    sLinkFile = "{shortcut_path}"
    Set oLink = oWS.CreateShortcut(sLinkFile)
    oLink.TargetPath = "{target_exe}"
    oLink.WorkingDirectory = "{target_exe.parent}"
    {args_str}
    {icon_str}
    oLink.Save
    """
    vbs_path = target_exe.parent / "create_shortcut.vbs"
    try:
        vbs_path.write_text(vbs_script)
        subprocess.run(["cscript", "//Nologo", str(vbs_path)], check=True)
        vbs_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"Shortcut creation failed: {e}")


UNINSTALL_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SyncDriveStudio"


def register_windows_uninstaller(install_dir: pathlib.Path, exe_path: pathlib.Path, icon_path: pathlib.Path = None):
    """Adds an entry to Windows 'Apps & Features' / 'Add or Remove Programs' so
    the app can be found and uninstalled the normal way, instead of only via a
    script buried in the install folder that most users would never find."""
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "SyncDrive Studio")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{exe_path}" --uninstall')
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
            if icon_path and icon_path.exists():
                winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon_path))
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "SyncDrive Studio")
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        print(f"Could not register uninstaller: {e}")


def unregister_windows_uninstaller():
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY_KEY)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Could not remove uninstaller registry entry: {e}")


def run_uninstall_flow(install_dir: pathlib.Path, is_portable: bool):
    """Removes shortcuts, the registry entry, saved app data, and (for a System
    Install) the installed program folder itself. Asks for confirmation first."""
    app = QApplication.instance() or QApplication(sys.argv)

    msg_box = QMessageBox()
    msg_box.setWindowTitle("Uninstall SyncDrive Studio")
    msg_box.setText("Are you sure you want to completely remove SyncDrive Studio?")
    msg_box.setInformativeText(
        "This will delete SyncDrive Studio's saved settings and activity log, "
        + ("and the desktop/Start Menu shortcuts." if is_portable else
           "shortcuts, and the installed program folder.")
    )
    msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg_box.setDefaultButton(QMessageBox.StandardButton.No)
    if msg_box.exec() != QMessageBox.StandardButton.Yes:
        return

    removed = []
    errors = []

    # 1. App data (saved jobs, config) — both portable and installed modes
    for app_data_dir in {pathlib.Path.home() / ".syncdrive_studio", install_dir / ".config"}:
        if app_data_dir.exists():
            try:
                shutil.rmtree(app_data_dir)
                removed.append(str(app_data_dir))
            except Exception as e:
                errors.append(f"{app_data_dir}: {e}")

    # 2. Shortcuts
    for shortcut in [
        pathlib.Path(os.path.expanduser("~/Desktop")) / "SyncDrive Studio.lnk",
        pathlib.Path(os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs")) / "SyncDrive Studio.lnk",
        pathlib.Path(os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs")) / "Uninstall SyncDrive Studio.lnk",
    ]:
        if shortcut.exists():
            try:
                shortcut.unlink()
                removed.append(str(shortcut))
            except Exception as e:
                errors.append(f"{shortcut}: {e}")

    # 3. Windows "Add or Remove Programs" entry
    unregister_windows_uninstaller()

    if errors:
        QMessageBox.warning(
            None, "Uninstall — Some Items Could Not Be Removed",
            "Removed:\n" + "\n".join(removed) + "\n\nCould not remove:\n" + "\n".join(errors)
        )
    else:
        QMessageBox.information(
            None, "Uninstall Complete",
            "SyncDrive Studio settings and shortcuts have been removed. Your Main and Backup folders were NOT touched."
            + ("" if is_portable else
               "\n\nThe program folder will finish removing itself in a few seconds "
               "after this window closes (it can't delete itself while running).")
        )

    # 4. Installed program folder — the running .exe can't delete itself directly
    # on Windows, so hand off to a short-lived batch script that waits for this
    # process to exit, then deletes the folder.
    if not is_portable and sys.platform.startswith("win") and install_dir.exists():
        bat_path = pathlib.Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "syncdrive_studio_cleanup.bat"
        bat_script = f"""@echo off
timeout /t 2 /nobreak > NUL
rmdir /s /q "{install_dir}"
del "%~f0"
"""
        try:
            bat_path.write_text(bat_script)
            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
        except Exception as e:
            print(f"Could not schedule folder cleanup: {e}")

    sys.exit(0)


SINGLE_INSTANCE_KEY = "SyncDriveStudio-SingleInstance-v1"


def acquire_single_instance_or_notify_running():
    """If another instance is already running, asks it (over a local socket)
    to restore itself to the foreground — which un-minimizes it from the tray
    the same way double-clicking the tray icon does — tells the user, and
    returns None so the caller exits instead of opening a second window.
    Otherwise starts listening for future launches and returns the server
    (the caller must keep a reference to it for the app's lifetime)."""
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(200):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
        QMessageBox.information(
            None, "SyncDrive Studio",
            "SyncDrive Studio is already running — bringing it to the front."
        )
        return None

    # No server responded — either this is genuinely the first instance, or a
    # previous instance crashed and left a stale server registration behind.
    # removeServer() clears a stale one; it's a no-op if none exists.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)
    return server




def resource_path(name: str) -> pathlib.Path:
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    return base / name


def fmt_size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024


def fmt_time(t) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


HOW_IT_WORKS = (
    "HOW IT WORKS\n\n"
    "• Main is your original folder. Backup is the copy.\n"
    "• Files only travel Main ➜ Backup. Main is never changed unless YOU choose it for one file.\n"
    "• New file in Main  ➜ copied to Backup.\n"
    "• Changed file in Main ➜ the new version is copied; the old Backup version is kept in\n"
    "  Backup/.backup_versions/<date>.\n"
    "• File only in Backup ➜ you choose: leave it, move it to Backup/.backup_trash, or copy it to Main.\n"
    "• If a file differs and the Backup copy is newer (or the same date), you choose which to keep.\n"
    "• Nothing is ever erased automatically. You empty versions/trash yourself.\n"
    "• Files are compared by size and date first, then by content (SHA-256) when needed."
)

DISCLAIMER = (
    "DISCLAIMER OF LIABILITY:\n\n"
    "SyncDrive Studio is free software provided 'AS-IS' with no warranty. The author is not liable for "
    "data loss or damage. You use it at your own risk. Always keep an independent copy of important data."
)


class SetupWizardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SyncDrive Studio — Setup")
        self.setMinimumSize(640, 700)
        self.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET +
                           "QGroupBox QLabel, QRadioButton, QCheckBox { color: #E6E8F5; } "
                           "QGroupBox { color: #B9BCD8; }")

        self.selected_mode = AppMode.PORTABLE
        self.custom_install_path = str(pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SyncDrive Studio")
        self.main_path = ""
        self.backup_path = ""

        layout = QVBoxLayout(self)
        title = QLabel("Welcome to SyncDrive Studio")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #6C5CE7;")
        layout.addWidget(title)

        how = QTextEdit(); how.setReadOnly(True); how.setPlainText(HOW_IT_WORKS)
        how.setMinimumHeight(190)
        layout.addWidget(how)

        folders = QGroupBox("1 · Your folders (you can also set these later)")
        fl = QVBoxLayout(folders)
        self.main_edit = QLineEdit(); self.main_edit.setPlaceholderText("Main folder — your original files")
        self.backup_edit = QLineEdit(); self.backup_edit.setPlaceholderText("Backup folder — where copies go")
        for label, edit in (("Main:", self.main_edit), ("Backup:", self.backup_edit)):
            row = QHBoxLayout()
            lab = QLabel(label); lab.setFixedWidth(55)
            btn = QPushButton("Browse..."); btn.setObjectName("RibbonBtn")
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            row.addWidget(lab); row.addWidget(edit); row.addWidget(btn)
            fl.addLayout(row)
        layout.addWidget(folders)

        mode_group = QGroupBox("2 · How to run")
        mode_box = QVBoxLayout(mode_group)
        self.radio_portable = QRadioButton("📁 Portable (no installation, settings stay next to the program)")
        self.radio_portable.setChecked(True)
        self.radio_portable.toggled.connect(lambda: self.dir_group.setEnabled(self.radio_install.isChecked()))
        self.radio_install = QRadioButton("💻 Install (copy to Program Files, add shortcuts and an Uninstall entry)")
        mode_box.addWidget(self.radio_portable)
        mode_box.addWidget(self.radio_install)
        layout.addWidget(mode_group)

        self.dir_group = QGroupBox("Install location")
        dir_box = QHBoxLayout(self.dir_group)
        self.path_input = QLineEdit(self.custom_install_path)
        browse_btn = QPushButton("Browse..."); browse_btn.setObjectName("RibbonBtn")
        browse_btn.clicked.connect(self.browse_install_dir)
        dir_box.addWidget(self.path_input); dir_box.addWidget(browse_btn)
        self.dir_group.setEnabled(False)
        layout.addWidget(self.dir_group)

        disc = QTextEdit(); disc.setReadOnly(True); disc.setPlainText(DISCLAIMER); disc.setMaximumHeight(90)
        layout.addWidget(disc)
        self.accept_cb = QCheckBox("I understand and accept the disclaimer")
        self.accept_cb.stateChanged.connect(lambda: self.confirm_btn.setEnabled(self.accept_cb.isChecked()))
        layout.addWidget(self.accept_cb)

        self.confirm_btn = QPushButton("Start")
        self.confirm_btn.setObjectName("RibbonBtnPrimary")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.finish)
        layout.addWidget(self.confirm_btn)

    def _browse(self, edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Select folder", edit.text() or "")
        if folder:
            edit.setText(folder)

    def browse_install_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select install location")
        if folder:
            self.path_input.setText(str(pathlib.Path(folder) / "SyncDrive Studio"))

    def finish(self):
        err = ""
        m, b = self.main_edit.text().strip(), self.backup_edit.text().strip()
        if m and b:
            err = eng.check_roots(pathlib.Path(m), pathlib.Path(b))
        if err:
            QMessageBox.warning(self, "Check your folders", err)
            return
        self.main_path, self.backup_path = m, b
        self.selected_mode = AppMode.INSTALLED if self.radio_install.isChecked() else AppMode.PORTABLE
        self.custom_install_path = self.path_input.text().strip()
        self.accept()


class AnalyzeWorker(QThread):
    status = pyqtSignal(str)
    done = pyqtSignal(object)

    def __init__(self, main: str, backup: str):
        super().__init__()
        self.main, self.backup = main, backup
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            plan = eng.build_plan(self.main, self.backup, lambda: self._stop, self.status.emit)
        except Exception as e:  # never leave the UI waiting
            plan = eng.Plan(self.main, self.backup, error=f"Unexpected error while analyzing: {e}")
        self.done.emit(plan)


class BackupWorker(QThread):
    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, ops: List[eng.Operation], main: str, backup: str, verify: bool):
        super().__init__()
        self.ops, self.main, self.backup, self.verify = ops, pathlib.Path(main), pathlib.Path(backup), verify
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        stamp = eng.stamp_now()
        stats = {"ok": 0, "failed": 0, "total": len(self.ops), "stopped": False, "stamp": stamp}
        total = max(1, len(self.ops))
        for i, op in enumerate(self.ops, 1):
            if self._stop:
                stats["stopped"] = True
                self.log.emit("🛑 Stopped by user. Already finished files are kept.")
                break
            try:
                msg = eng.apply_operation(op, self.main, self.backup, stamp, self.verify)
                stats["ok"] += 1
                self.log.emit(msg)
            except Exception as e:
                stats["failed"] += 1
                self.log.emit(f"⚠️ FAILED {op.item.rel}: {e}  (nothing was lost; continuing)")
            self.progress.emit(int(i / total * 100), f"{i:,} / {len(self.ops):,}  ·  {op.item.rel}")
        self.done.emit(stats)


class MainWindow(QMainWindow):
    CONFLICT_CHOICES = [("Skip for now", None),
                        ("Keep Main version  (update Backup)", "keep_main"),
                        ("Keep Backup version  (replace Main)", "keep_backup")]
    BACKUP_ONLY_CHOICES = [("Leave alone", None),
                           ("Move to Backup trash", "trash"),
                           ("Copy to Main", "copy_to_main")]

    def __init__(self, app_mode: AppMode, config_dir: pathlib.Path, install_dir: pathlib.Path = None):
        super().__init__()
        self.app_mode = app_mode
        self.config_dir = config_dir
        self.install_dir = install_dir
        self.settings_file = config_dir / "settings.json"
        self.log_file = config_dir / "backup.log"
        self.plan = None
        self.rows = []              # [(category, Item, QComboBox|None)]
        self.analyzer = None
        self.worker = None
        self.single_instance_server = None
        self._auto_analyze_after_backup = False

        self.setWindowTitle("SyncDrive Studio — Main ➜ Backup")
        icon = resource_path("app_icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1180, 820)
        self.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET)
        self._build_ui()
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _folder_card(self, title: str, subtitle: str, edit: QLineEdit):
        card = QFrame(); card.setObjectName("PathCard")
        lay = QVBoxLayout(card)
        head = QLabel(f"<b>{title}</b>  <span style='color:#8A8DA8'>{subtitle}</span>")
        lay.addWidget(head)
        row = QHBoxLayout()
        edit.setPlaceholderText("Choose a folder or drive...")
        btn = QPushButton("Browse..."); btn.setObjectName("RibbonBtn")
        btn.clicked.connect(lambda: self._browse(edit))
        row.addWidget(edit); row.addWidget(btn)
        lay.addLayout(row)
        return card

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.main_edit = QLineEdit(); self.backup_edit = QLineEdit()
        root.addWidget(self._folder_card("MAIN", "your original files — only read, never changed by backup", self.main_edit))
        arrow = QLabel("⬇  copies new and changed files  ⬇"); arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet("color:#6C5CE7; font-weight:bold;")
        root.addWidget(arrow)
        root.addWidget(self._folder_card("BACKUP", "receives the copies; old versions and trash are kept here", self.backup_edit))

        bar = QHBoxLayout()
        self.btn_analyze = QPushButton("🔍 Analyze"); self.btn_analyze.setObjectName("RibbonBtnPrimary")
        self.btn_analyze.clicked.connect(self.analyze)
        self.btn_start = QPushButton("▶ Start Backup"); self.btn_start.setObjectName("RibbonBtnPrimary")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_backup)
        self.btn_stop = QPushButton("⏹ Stop"); self.btn_stop.setObjectName("StopBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_all)
        self.verify_cb = QCheckBox("Verify every copy (slower, safest)")
        self.verify_cb.setChecked(True)
        bar.addWidget(self.btn_analyze); bar.addWidget(self.btn_start); bar.addWidget(self.btn_stop)
        bar.addSpacing(12); bar.addWidget(self.verify_cb); bar.addStretch()
        for text, slot in (("📂 Old versions", lambda: self.open_store(eng.VERSIONS_DIR)),
                           ("📂 Trash", lambda: self.open_store(eng.TRASH_DIR)),
                           ("🧹 Empty versions…", lambda: self.empty_store(eng.VERSIONS_DIR)),
                           ("🧹 Empty trash…", lambda: self.empty_store(eng.TRASH_DIR))):
            b = QPushButton(text); b.setObjectName("RibbonBtn"); b.clicked.connect(slot); bar.addWidget(b)
        root.addLayout(bar)

        self.summary_lbl = QLabel("Choose Main and Backup, then press Analyze. Nothing is changed by Analyze.")
        self.summary_lbl.setWordWrap(True)
        root.addWidget(self.summary_lbl)

        bulk = QHBoxLayout()
        bulk.addWidget(QLabel("Conflicts:"))
        for text, idx in (("All: Keep Main", 1), ("All: Keep Backup", 2), ("All: Skip", 0)):
            b = QPushButton(text); b.setObjectName("RibbonBtn")
            b.clicked.connect(lambda _=False, i=idx: self._bulk("conflict", i)); bulk.addWidget(b)
        bulk.addSpacing(20)
        bulk.addWidget(QLabel("Only on Backup:"))
        for text, idx in (("All: Leave alone", 0), ("All: Move to trash", 1), ("All: Copy to Main", 2)):
            b = QPushButton(text); b.setObjectName("RibbonBtn")
            b.clicked.connect(lambda _=False, i=idx: self._bulk("backup_only", i)); bulk.addWidget(b)
        bulk.addStretch()
        root.addLayout(bulk)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["What will happen", "File", "Main", "Backup", "Your decision"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 230); self.table.setColumnWidth(2, 250)
        self.table.setColumnWidth(3, 250); self.table.setColumnWidth(4, 270)
        split.addWidget(self.table)

        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        split.addWidget(self.log_view)
        split.setSizes([480, 180])
        root.addWidget(split, 1)

        prog = QHBoxLayout()
        self.progress_bar = QProgressBar(); self.progress_bar.setValue(0)
        self.status_lbl = QLabel("Ready")
        prog.addWidget(self.progress_bar, 2); prog.addWidget(self.status_lbl, 3)
        root.addLayout(prog)

    # ------------------------------------------------------------ settings/log
    def _load_settings(self):
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        self.main_edit.setText(data.get("main", ""))
        self.backup_edit.setText(data.get("backup", ""))
        self.verify_cb.setChecked(bool(data.get("verify", True)))

    def _save_settings(self):
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps({
                "main": self.main_edit.text().strip(),
                "backup": self.backup_edit.text().strip(),
                "verify": self.verify_cb.isChecked(),
            }, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"⚠️ Could not save settings: {e}")

    def log(self, msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_view.appendPlainText(line)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
        except Exception:
            pass

    def _browse(self, edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Select folder", edit.text() or "")
        if folder:
            edit.setText(folder)
            self._save_settings()

    # ------------------------------------------------------------- analyze
    def _busy(self) -> bool:
        return bool((self.analyzer and self.analyzer.isRunning()) or (self.worker and self.worker.isRunning()))

    def _set_busy(self, busy: bool):
        self.btn_analyze.setEnabled(not busy)
        self.btn_start.setEnabled(False if busy else bool(self.plan and self.plan.ok))
        self.btn_stop.setEnabled(busy)
        self.main_edit.setEnabled(not busy); self.backup_edit.setEnabled(not busy)

    def analyze(self):
        if self._busy():
            return
        m, b = self.main_edit.text().strip(), self.backup_edit.text().strip()
        err = eng.check_roots(pathlib.Path(m), pathlib.Path(b))
        if err:
            QMessageBox.warning(self, "Check your folders", err)
            return
        self._save_settings()
        self.plan = None
        self.table.setRowCount(0); self.rows = []
        self.progress_bar.setRange(0, 0)
        self.status_lbl.setText("🔍 Scanning...")
        self.log(f"--- Analyze: Main={m}  Backup={b} ---")
        self._set_busy(True)
        self.analyzer = AnalyzeWorker(m, b)
        self.analyzer.status.connect(self.status_lbl.setText)
        self.analyzer.done.connect(self.on_plan)
        self.analyzer.start()

    def on_plan(self, plan):
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
        self.plan = plan
        if not plan.ok:
            self.status_lbl.setText("Stopped")
            self.summary_lbl.setText(f"⛔ {plan.error}")
            self.log(f"⛔ {plan.error}")
            self._set_busy(False)
            if plan.error != "Cancelled.":
                QMessageBox.warning(self, "Nothing was changed", plan.error)
            return
        for w in plan.warnings:
            self.log(f"⚠️ {w}")
        self._fill_table(plan)
        n_auto = len(plan.new) + len(plan.updates)
        self.summary_lbl.setText(
            f"<b>{len(plan.new):,}</b> new  ·  <b>{len(plan.updates):,}</b> updated  ·  "
            f"<b style='color:#FDCB6E'>{len(plan.conflicts):,}</b> conflicts (you decide)  ·  "
            f"<b style='color:#FDCB6E'>{len(plan.backup_only):,}</b> only on Backup (you decide)  ·  "
            f"{plan.identical:,} identical" + (f" ({plan.hashed:,} confirmed by content)" if plan.hashed else ""))
        self.status_lbl.setText("Analysis done — review, then Start Backup")
        self.log(f"Analysis: {len(plan.new)} new, {len(plan.updates)} updated, {len(plan.conflicts)} conflicts, "
                 f"{len(plan.backup_only)} only on Backup, {plan.identical} identical.")
        self._set_busy(False)
        if n_auto == 0 and not plan.conflicts and not plan.backup_only:
            self.table_message("Everything is already backed up. ✅")

    def table_message(self, text: str):
        self.table.setRowCount(1)
        it = QTableWidgetItem(text); it.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table.setItem(0, 0, it); self.table.setSpan(0, 0, 1, 5)

    def _cell(self, text, color=None, tip=None):
        it = QTableWidgetItem(text)
        if color:
            it.setForeground(QColor(color))
        if tip:
            it.setToolTip(tip)
        return it

    def _side_text(self, size, mtime, tag=""):
        return f"{fmt_time(mtime)} · {fmt_size(size)}" + (f"  — {tag}" if tag else "")

    def _fill_table(self, plan):
        self.table.clearSpans()
        total = len(plan.conflicts) + len(plan.backup_only) + len(plan.updates) + len(plan.new)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(total)
        self.rows = []
        GREEN, AMBER, RED, MUTED = "#00B894", "#FDCB6E", "#E17055", "#8A8DA8"
        r = 0

        def add(category, item, what, what_color, main_txt, main_col, back_txt, back_col, combo_choices=None):
            nonlocal r
            self.table.setItem(r, 0, self._cell(what, what_color))
            self.table.setItem(r, 1, self._cell(item.rel, None, item.rel + (f"\n{item.note}" if item.note else "")))
            self.table.setItem(r, 2, self._cell(main_txt, main_col, os.path.join(plan.main, item.rel)))
            self.table.setItem(r, 3, self._cell(back_txt, back_col, os.path.join(plan.backup, item.rel)))
            combo = None
            if combo_choices:
                combo = QComboBox()
                for label, _ in combo_choices:
                    combo.addItem(label)
                combo.setMinimumHeight(28)
                self.table.setCellWidget(r, 4, combo)
            else:
                self.table.setItem(r, 4, self._cell("automatic", MUTED))
            self.rows.append((category, item, combo))
            r += 1

        def tags(mt, bt):
            if abs(mt - bt) <= eng.MTIME_TOLERANCE:
                return "same date", "same date", MUTED, MUTED
            return (("NEWER", "older", GREEN, AMBER) if mt > bt else ("older", "NEWER", AMBER, GREEN))

        for it in plan.conflicts:
            mt_tag, bt_tag, mc, bc = tags(it.main_mtime, it.backup_mtime)
            add("conflict", it, f"⚠️ CONFLICT — {it.note.split(' · ')[0]}", AMBER,
                self._side_text(it.main_size, it.main_mtime, mt_tag), mc,
                self._side_text(it.backup_size, it.backup_mtime, bt_tag), bc, self.CONFLICT_CHOICES)
        for it in plan.backup_only:
            add("backup_only", it, "❓ Only on Backup", AMBER, "— not in Main —", RED,
                self._side_text(it.backup_size, it.backup_mtime), None, self.BACKUP_ONLY_CHOICES)
        for it in plan.updates:
            mt_tag, bt_tag, mc, bc = tags(it.main_mtime, it.backup_mtime)
            add("update", it, "🔄 Update Backup (old version kept)", GREEN,
                self._side_text(it.main_size, it.main_mtime, mt_tag), mc,
                self._side_text(it.backup_size, it.backup_mtime, bt_tag), bc)
        for it in plan.new:
            add("new", it, "➕ Copy to Backup (new)", GREEN,
                self._side_text(it.main_size, it.main_mtime), None, "— not in Backup yet —", MUTED)
        self.table.setUpdatesEnabled(True)

    def _bulk(self, category: str, index: int):
        for cat, _item, combo in self.rows:
            if cat == category and combo is not None:
                combo.setCurrentIndex(index)

    # -------------------------------------------------------------- backup
    def _collect_operations(self):
        ops = []
        for cat, item, combo in self.rows:
            if cat == "new":
                ops.append(eng.Operation("new", item))
            elif cat == "update":
                ops.append(eng.Operation("update", item))
            elif combo is not None:
                choices = self.CONFLICT_CHOICES if cat == "conflict" else self.BACKUP_ONLY_CHOICES
                kind = choices[combo.currentIndex()][1]
                if kind:
                    ops.append(eng.Operation(kind, item))
        return ops

    def start_backup(self):
        if self._busy() or not self.plan or not self.plan.ok:
            return
        ops = self._collect_operations()
        if not ops:
            QMessageBox.information(self, "Nothing to do", "No files selected for any action.")
            return
        count = lambda k: sum(1 for o in ops if o.kind == k)
        risky = []
        if count("trash"):
            risky.append(f"• {count('trash')} file(s) moved to Backup trash (recoverable)")
        if count("keep_backup"):
            risky.append(f"• {count('keep_backup')} file(s) in MAIN replaced by the Backup version (Main's old copy is saved first)")
        if count("copy_to_main"):
            risky.append(f"• {count('copy_to_main')} file(s) copied from Backup into MAIN")
        text = (f"{count('new')} new, {count('update') + count('keep_main')} updated.\n")
        if risky:
            text += "\nThese actions go beyond a normal backup:\n" + "\n".join(risky) + "\n"
        text += "\nNothing is erased. Continue?"
        box = QMessageBox(self); box.setWindowTitle("Confirm backup"); box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._save_settings()
        self.log(f"--- Backup started: {len(ops)} operation(s) ---")
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
        self._set_busy(True)
        self.worker = BackupWorker(ops, self.plan.main, self.plan.backup, self.verify_cb.isChecked())
        self.worker.progress.connect(lambda p, m: (self.progress_bar.setValue(p), self.status_lbl.setText(m)))
        self.worker.log.connect(self.log)
        self.worker.done.connect(self.on_backup_done)
        self.worker.start()

    def on_backup_done(self, stats: dict):
        self.log(f"--- Finished: {stats['ok']} done, {stats['failed']} failed"
                 + (", stopped early" if stats["stopped"] else "") + " ---")
        if stats["failed"]:
            QMessageBox.warning(self, "Some files failed",
                                f"{stats['failed']} file(s) could not be processed. Nothing was lost — see the log.")
        self.progress_bar.setValue(100 if not stats["stopped"] else self.progress_bar.value())
        self.status_lbl.setText("Done — re-checking...")
        self._set_busy(False)
        self.analyze()   # refresh: shows whatever was skipped or failed

    def stop_all(self):
        if self.analyzer and self.analyzer.isRunning():
            self.analyzer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        self.status_lbl.setText("Stopping...")

    # --------------------------------------------------- versions / trash
    def _store(self, name: str):
        b = self.backup_edit.text().strip()
        return pathlib.Path(b) / name if b else None

    def open_store(self, name: str):
        p = self._store(name)
        if not p or not p.is_dir():
            QMessageBox.information(self, "Empty", "Nothing has been stored there yet.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def empty_store(self, name: str):
        if self._busy():
            return
        p = self._store(name)
        if not p or not p.is_dir():
            QMessageBox.information(self, "Empty", "Nothing has been stored there yet.")
            return
        n, size = eng.folder_stats(p)
        label = "old versions" if name == eng.VERSIONS_DIR else "trash"
        box = QMessageBox(self); box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(f"Empty {label}")
        box.setText(f"PERMANENTLY delete {n:,} file(s) ({fmt_size(size)}) from the Backup's {label} folder?\n\n"
                    f"{p}\n\nThis cannot be undone. Open the folder first if you want to restore something.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            eng.empty_folder(p, pathlib.Path(self.backup_edit.text().strip()))
            self.log(f"🧹 Emptied {label}: {n} file(s), {fmt_size(size)}")
        except Exception as e:
            QMessageBox.warning(self, "Could not empty", str(e))

    # ------------------------------------------------------------- window
    def show_normal_and_raise(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        if self._busy():
            r = QMessageBox.question(self, "Work in progress", "A backup/analysis is running. Stop it and quit?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.stop_all()
            for t in (self.analyzer, self.worker):
                if t and t.isRunning():
                    t.wait(15000)
        self._save_settings()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET)

    if "--uninstall" in sys.argv:
        if getattr(sys, "frozen", False):
            _exe_dir_for_uninstall = pathlib.Path(sys.executable).parent
        else:
            _exe_dir_for_uninstall = pathlib.Path(__file__).parent
        _mode_file = _exe_dir_for_uninstall / ".app_mode"
        _is_portable = _mode_file.exists() and _mode_file.read_text().strip() == AppMode.PORTABLE.value
        run_uninstall_flow(_exe_dir_for_uninstall, _is_portable)
        sys.exit(0)

    single_instance_server = acquire_single_instance_or_notify_running()
    if single_instance_server is None:
        sys.exit(0)

    if getattr(sys, "frozen", False):
        exe_path = pathlib.Path(sys.executable)
    else:
        exe_path = pathlib.Path(__file__)
    exe_dir = exe_path.parent

    mode_file = exe_dir / ".app_mode"
    wizard_main = wizard_backup = ""
    if mode_file.exists():
        selected_mode = AppMode.PORTABLE if mode_file.read_text().strip() == AppMode.PORTABLE.value else AppMode.INSTALLED
        target_install_dir = exe_dir
    else:
        wizard = SetupWizardDialog()
        if wizard.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        selected_mode = wizard.selected_mode
        target_install_dir = pathlib.Path(wizard.custom_install_path) if selected_mode == AppMode.INSTALLED else exe_dir
        wizard_main, wizard_backup = wizard.main_path, wizard.backup_path
        try:
            mode_file.write_text(selected_mode.value)
        except Exception:
            pass

    config_dir = exe_dir / ".config" if selected_mode == AppMode.PORTABLE else pathlib.Path.home() / ".syncdrive_studio"
    config_dir.mkdir(parents=True, exist_ok=True)
    if wizard_main or wizard_backup:
        try:
            (config_dir / "settings.json").write_text(json.dumps(
                {"main": wizard_main, "backup": wizard_backup, "verify": True}, indent=2), encoding="utf-8")
        except Exception:
            pass

    if selected_mode == AppMode.INSTALLED and getattr(sys, "frozen", False) and target_install_dir:
        try:
            target_install_dir.mkdir(parents=True, exist_ok=True)
            installed_exe = target_install_dir / "SyncDriveStudio.exe"
            if exe_path.resolve() != installed_exe.resolve():
                shutil.copy2(exe_path, installed_exe)
                try:
                    (target_install_dir / ".app_mode").write_text(AppMode.INSTALLED.value)
                except Exception:
                    pass
            programs = pathlib.Path(os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs"))
            icon_file = resource_path("app_icon.ico")
            create_windows_shortcut(installed_exe, pathlib.Path(os.path.expanduser("~/Desktop")) / "SyncDrive Studio.lnk", icon_file)
            create_windows_shortcut(installed_exe, programs / "SyncDrive Studio.lnk", icon_file)
            create_windows_shortcut(installed_exe, programs / "Uninstall SyncDrive Studio.lnk", icon_file, arguments="--uninstall")
            register_windows_uninstaller(target_install_dir, installed_exe, icon_file)
        except PermissionError:
            if sys.platform.startswith("win"):
                QMessageBox.warning(None, "Administrator Required",
                                    f"Writing to '{target_install_dir}' requires Administrator rights.\n"
                                    "Please right-click the program and select 'Run as Administrator'.")
                sys.exit(1)

    window = MainWindow(app_mode=selected_mode, config_dir=config_dir, install_dir=target_install_dir)
    window.single_instance_server = single_instance_server
    single_instance_server.newConnection.connect(window.show_normal_and_raise)
    window.show()
    sys.exit(app.exec())
