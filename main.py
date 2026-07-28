import sys
import os
import time
import uuid
import shutil
import subprocess
import importlib.util
import multiprocessing
import pathlib
from datetime import datetime
from enum import Enum
from typing import List, Callable

# MUST call freeze_support at script load time for Windows PyInstaller single-file builds
if __name__ == "__main__":
    multiprocessing.freeze_support()

REQUIRED_PACKAGES = {
    "PyQt6": "PyQt6",
    "pydantic": "pydantic",
    "psutil": "psutil",
    "watchdog": "watchdog"
}

def auto_install_dependencies():
    missing = [pkg for pkg, imp in REQUIRED_PACKAGES.items() if importlib.util.find_spec(imp) is None]
    if missing:
        print("\n==================================================")
        print(" [SyncDrive Studio] Installing Dependencies")
        print(f" Packages: {', '.join(missing)}")
        print("==================================================\n")
        total = len(missing)
        for idx, pkg in enumerate(missing, 1):
            percent = int((idx / total) * 100)
            bar = '█' * (percent // 5) + '-' * (20 - (percent // 5))
            print(f"\rInstalling {pkg:<12} [{bar}] {percent}%", end="", flush=True)
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                print(f"\n❌ Error installing {pkg}: {e}")
                sys.exit(1)
        print("\n\n✅ Dependencies updated successfully!\n")

if not getattr(sys, 'frozen', False):
    auto_install_dependencies()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel, QTextEdit, QCheckBox, QComboBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QMessageBox,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QSpinBox, QFrame,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter, QSystemTrayIcon, QMenu,
    QStyle
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QIcon, QColor, QAction
from models import SyncJob, SyncMode, ConflictPolicy, ScheduleType
from engine import SyncEngine
from drive_detector import DriveWatcherThread

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


# --- Thread-Safe Watchdog Signal Bridge ---
class WatchdogSignalBridge(QObject):
    file_changed = pyqtSignal(str, str)  # (event_type, path)
    watcher_error = pyqtSignal(str)      # (human-readable error message)


if WATCHDOG_AVAILABLE:
    class RobustChangeHandler(FileSystemEventHandler):
        def __init__(self, bridge: WatchdogSignalBridge):
            super().__init__()
            self.bridge = bridge

        def _handle_event(self, event_type: str, src_path: str):
            try:
                # System files filter to prevent C-level thread crashes on drive roots
                ignored_keywords = ["$RECYCLE.BIN", "System Volume Information", ".tmp", "~", "desktop.ini"]
                if any(kw in src_path for kw in ignored_keywords):
                    return

                # NOTE: every raw event is forwarded here. Debouncing/coalescing happens
                # on the Qt-thread side (SmartFolderWatcherManager) via QTimer, so rapid
                # successive changes are batched into one sync instead of being dropped.
                filename = os.path.basename(src_path) or src_path
                self.bridge.file_changed.emit(event_type, filename)
            except Exception:
                pass

        def on_created(self, event):
            self._handle_event("Created", event.src_path)

        def on_modified(self, event):
            if not event.is_directory:
                self._handle_event("Modified", event.src_path)

        def on_deleted(self, event):
            self._handle_event("Deleted", event.src_path)

        def on_moved(self, event):
            dest = getattr(event, 'dest_path', event.src_path)
            self._handle_event("Renamed", dest)

    class SmartFolderWatcherManager:
        def __init__(self, watch_paths: List[str], callback: Callable[[str, str], None], debounce_seconds: int = 1):
            self.watch_paths = watch_paths
            self.callback = callback
            self.debounce_seconds = max(1, debounce_seconds)
            self.active = False  # True once at least one path is actually being watched

            self.bridge = WatchdogSignalBridge()
            self.bridge.file_changed.connect(self._on_raw_change)

            self.handler = RobustChangeHandler(self.bridge)
            self.observer = Observer()

            # Trailing-edge debounce timer lives on the Qt (main) thread, so bursts of
            # filesystem events collapse into a single sync instead of being discarded.
            self._debounce_timer = QTimer()
            self._debounce_timer.setSingleShot(True)
            self._debounce_timer.timeout.connect(self._fire_debounced_callback)
            self._pending_event = None

        def _on_raw_change(self, event_type: str, filename: str):
            self._pending_event = (event_type, filename)
            self._debounce_timer.start(self.debounce_seconds * 1000)

        def _fire_debounced_callback(self):
            if self._pending_event is not None:
                event_type, filename = self._pending_event
                self._pending_event = None
                self.callback(event_type, filename)

        def start(self):
            errors = []
            scheduled_count = 0
            for path_str in self.watch_paths:
                clean_path = os.path.abspath(os.path.normpath(path_str))
                if not os.path.exists(clean_path):
                    errors.append(f"Path does not exist: '{clean_path}'")
                    continue
                try:
                    self.observer.schedule(self.handler, path=clean_path, recursive=True)
                    scheduled_count += 1
                except Exception as e:
                    errors.append(f"Could not watch '{clean_path}': {e}")

            if scheduled_count > 0:
                try:
                    self.observer.start()
                    self.active = True
                except Exception as e:
                    errors.append(f"Watcher failed to start: {e}")
                    self.active = False

            if errors:
                self.bridge.watcher_error.emit(" | ".join(errors))

        def stop(self):
            self._debounce_timer.stop()
            if self.observer.is_alive():
                self.observer.stop()
                self.observer.join()


GOODSYNC_STUDIO_STYLESHEET = """
QMainWindow {
    background-color: #0F1017;
}

QWidget {
    color: #E6E8F5;
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 12px;
}

/* Top Toolbar Ribbon */
#ToolbarFrame {
    background-color: #181A26;
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
    background-color: #14151F;
    border-bottom: 1px solid #262838;
    padding: 8px 14px;
}

#PathCard {
    background-color: #1A1C29;
    border: 1px solid #2A2C40;
    border-radius: 8px;
    padding: 5px 12px;
}

/* Stat / Dashboard Cards */
#StatCard {
    background-color: #171826;
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
QTreeWidget, QListWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background-color: #14151F;
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
    background-color: #1A1C29;
    color: #8A8CAD;
    padding: 7px;
    border: none;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}

QTreeWidget::item {
    padding: 6px 4px;
    border-bottom: 1px solid #1A1C29;
}

QTreeWidget::item:selected, QListWidget::item:selected {
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
    background-color: #14151F;
}

QCheckBox::indicator:checked {
    background-color: #00B894;
    border-color: #00B894;
}

/* Progress Bar */
QProgressBar {
    border: none;
    border-radius: 8px;
    background-color: #14151F;
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


def create_windows_shortcut(target_exe: pathlib.Path, shortcut_path: pathlib.Path, icon_path: pathlib.Path = None):
    if not sys.platform.startswith("win"):
        return

    icon_str = f'oLink.IconLocation = "{icon_path}"' if icon_path and icon_path.exists() else ''
    vbs_script = f"""
    Set oWS = WScript.CreateObject("WScript.Shell")
    sLinkFile = "{shortcut_path}"
    Set oLink = oWS.CreateShortcut(sLinkFile)
    oLink.TargetPath = "{target_exe}"
    oLink.WorkingDirectory = "{target_exe.parent}"
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


class SetupWizardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SyncDrive Studio - Setup Wizard")
        self.setFixedSize(580, 500)
        self.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET)
        
        self.selected_mode = AppMode.PORTABLE
        self.custom_install_path = str(pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SyncDrive Studio")

        layout = QVBoxLayout(self)
        title = QLabel("Welcome to SyncDrive Studio Setup")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #6C5CE7;")
        layout.addWidget(title)

        disc_group = QGroupBox("⚠️ License & Legal Disclaimer")
        disc_box = QVBoxLayout(disc_group)
        disc_text = QTextEdit()
        disc_text.setReadOnly(True)
        disc_text.setText(
            "DISCLAIMER OF LIABILITY:\n\n"
            "SyncDrive Studio is free utility software provided 'AS-IS' for personal use.\n"
            "The author holds no liability for data loss or hardware issues.\n"
            "By checking accept, you use this application at your own risk."
        )
        disc_text.setMaximumHeight(100)
        disc_box.addWidget(disc_text)

        self.accept_cb = QCheckBox("I accept the disclaimer terms")
        self.accept_cb.stateChanged.connect(self.toggle_next_button)
        disc_box.addWidget(self.accept_cb)
        layout.addWidget(disc_group)

        mode_group = QGroupBox("Deployment Mode")
        mode_box = QVBoxLayout(mode_group)
        self.radio_portable = QRadioButton("📁 Portable Mode (No system installation)")
        self.radio_portable.setChecked(True)
        self.radio_portable.toggled.connect(self.toggle_location_box)

        self.radio_install = QRadioButton("💻 System Install Mode (Copy to Program Files & create shortcuts)")
        mode_box.addWidget(self.radio_portable)
        mode_box.addWidget(self.radio_install)
        layout.addWidget(mode_group)

        self.dir_group = QGroupBox("Installation Path")
        dir_box = QHBoxLayout(self.dir_group)
        self.path_input = QLineEdit(self.custom_install_path)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_install_dir)
        dir_box.addWidget(self.path_input)
        dir_box.addWidget(browse_btn)
        self.dir_group.setEnabled(False)
        layout.addWidget(self.dir_group)

        self.prog_group = QGroupBox("Progress")
        prog_box = QVBoxLayout(self.prog_group)
        self.install_progress = QProgressBar()
        self.install_progress.setValue(0)
        self.status_lbl = QLabel("Status: Waiting for confirmation...")
        prog_box.addWidget(self.install_progress)
        prog_box.addWidget(self.status_lbl)
        layout.addWidget(self.prog_group)

        self.confirm_btn = QPushButton("Install & Launch")
        self.confirm_btn.setObjectName("RibbonBtnPrimary")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.start_installation)
        layout.addWidget(self.confirm_btn)

    def toggle_next_button(self):
        self.confirm_btn.setEnabled(self.accept_cb.isChecked())

    def toggle_location_box(self):
        self.dir_group.setEnabled(self.radio_install.isChecked())

    def browse_install_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder")
        if folder:
            self.custom_install_path = str(pathlib.Path(folder) / "SyncDrive Studio")
            self.path_input.setText(self.custom_install_path)

    def start_installation(self):
        self.selected_mode = AppMode.INSTALLED if self.radio_install.isChecked() else AppMode.PORTABLE
        self.custom_install_path = self.path_input.text().strip()
        self.confirm_btn.setEnabled(False)

        for i in range(1, 101):
            time.sleep(0.015)
            self.install_progress.setValue(i)
            if i == 30: self.status_lbl.setText("Status: Preparing target location...")
            elif i == 70: self.status_lbl.setText("Status: Extracting binaries...")
            QApplication.processEvents()

        self.status_lbl.setText("Status: Installation Complete!")
        time.sleep(0.3)
        self.accept()


class IntervalPicker(QWidget):
    """A friendlier way to set 'sync every N minutes' than a bare spinbox:
    one-click common presets, plus a custom spinbox for anything else."""
    valueChanged = pyqtSignal(int)

    PRESETS = [("5m", 5), ("15m", 15), ("30m", 30), ("1h", 60), ("6h", 360), ("24h", 1440)]

    def __init__(self, parent=None, initial_minutes: int = 30):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self._preset_buttons = []
        for label, minutes in self.PRESETS:
            btn = QPushButton(label)
            btn.setObjectName("PresetBtn")
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda _, m=minutes: self.set_minutes(m))
            row.addWidget(btn)
            self._preset_buttons.append((btn, minutes))

        self.spin = QSpinBox()
        self.spin.setRange(1, 1440)
        self.spin.setSuffix(" min")
        self.spin.setFixedHeight(24)
        self.spin.valueChanged.connect(self._on_spin_changed)
        row.addWidget(self.spin)

        self.set_minutes(initial_minutes)

    def _sync_preset_highlight(self, minutes: int):
        for btn, m in self._preset_buttons:
            btn.blockSignals(True)
            btn.setChecked(m == minutes)
            btn.blockSignals(False)

    def _on_spin_changed(self, value: int):
        self._sync_preset_highlight(value)
        self.valueChanged.emit(value)

    def set_minutes(self, minutes: int):
        self.spin.blockSignals(True)
        self.spin.setValue(minutes)
        self.spin.blockSignals(False)
        self._sync_preset_highlight(minutes)
        self.valueChanged.emit(minutes)

    def value(self) -> int:
        return self.spin.value()


class SyncWorker(QThread):
    progress_update = pyqtSignal(int, str)
    action_item_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(list)

    def __init__(self, engine: SyncEngine, job: SyncJob, dry_run: bool):
        super().__init__()
        self.engine = engine
        self.job = job
        self.dry_run = dry_run
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def run(self):
        try:
            actions = self.engine.plan_job(self.job)
            total = len(actions)

            if total == 0:
                self.progress_update.emit(100, "No pending file changes detected.")

            for idx, action in enumerate(actions, 1):
                if self.stop_requested:
                    self.progress_update.emit(0, "🛑 Sync operation cancelled by user.")
                    break

                pct = int((idx / total) * 100) if total > 0 else 100
                msg = f"[{action.action_type}] {action.target_path or action.source_path}"

                self.action_item_signal.emit({
                    "action_type": action.action_type,
                    "source": action.source_path or "-",
                    "target": action.target_path or "-",
                    "reason": action.reason
                })

                if not self.dry_run:
                    if action.action_type == "COPY_TO_TARGET":
                        d = pathlib.Path(action.target_path)
                        d.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(action.source_path, d)
                    elif action.action_type == "COPY_TO_SOURCE":
                        s = pathlib.Path(action.source_path)
                        s.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(action.target_path, s)
                    elif action.action_type == "DELETE_TARGET":
                        pathlib.Path(action.target_path).unlink(missing_ok=True)

                self.progress_update.emit(pct, msg)

            self.finished_signal.emit(actions)
        except Exception as e:
            self.error_signal.emit(str(e))


class ModernJobDialog(QDialog):
    def __init__(self, parent=None, job: SyncJob = None):
        super().__init__(parent)
        self.setWindowTitle("Configure Sync Task")
        self.resize(600, 460)
        self.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET)
        self.job = job

        layout = QVBoxLayout(self)

        top_group = QGroupBox("General Options")
        top_layout = QFormLayout(top_group)

        self.name_input = QLineEdit(job.name if job else "New Sync Task")
        top_layout.addRow("Task Name:", self.name_input)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([m.value for m in SyncMode])
        if job: self.mode_combo.setCurrentText(job.mode.value)
        top_layout.addRow("Sync Mode:", self.mode_combo)

        self.schedule_combo = QComboBox()
        self.schedule_combo.addItems([s.value for s in ScheduleType])
        if job: self.schedule_combo.setCurrentText(job.schedule_type.value)
        self.schedule_combo.currentTextChanged.connect(self.toggle_trigger_options)
        top_layout.addRow("Trigger Strategy:", self.schedule_combo)

        self.interval_picker = IntervalPicker(initial_minutes=job.interval_minutes if job else 30)
        top_layout.addRow("Repeat Interval:", self.interval_picker)

        layout.addWidget(top_group)

        drive_section = QHBoxLayout()

        src_group = QGroupBox("Left Side (Source)")
        src_box = QVBoxLayout(src_group)
        self.src_input = QLineEdit(", ".join(job.sources) if job else "")
        src_browse = QPushButton("📁 Select Source")
        src_browse.setObjectName("RibbonBtn")
        src_browse.clicked.connect(self.browse_source)
        src_box.addWidget(self.src_input)
        src_box.addWidget(src_browse)
        drive_section.addWidget(src_group)

        dst_group = QGroupBox("Right Side (Target)")
        dst_box = QVBoxLayout(dst_group)
        self.dst_input = QLineEdit(", ".join(job.targets) if job else "")
        dst_browse = QPushButton("💾 Select Target")
        dst_browse.setObjectName("RibbonBtn")
        dst_browse.clicked.connect(self.browse_target)
        dst_box.addWidget(self.dst_input)
        dst_box.addWidget(dst_browse)
        drive_section.addWidget(dst_group)

        layout.addLayout(drive_section)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.toggle_trigger_options(self.schedule_combo.currentText())

    def toggle_trigger_options(self, selected_mode: str):
        self.interval_picker.setEnabled(selected_mode == ScheduleType.INTERVAL.value)

    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            current = [s.strip().strip('"').strip("'") for s in self.src_input.text().split(",") if s.strip()]
            current.append(folder)
            self.src_input.setText(", ".join(current))

    def browse_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder")
        if folder:
            current = [t.strip().strip('"').strip("'") for t in self.dst_input.text().split(",") if t.strip()]
            current.append(folder)
            self.dst_input.setText(", ".join(current))

    def validate_and_accept(self):
        sources = [s.strip().strip('"').strip("'") for s in self.src_input.text().split(",") if s.strip()]
        targets = [t.strip().strip('"').strip("'") for t in self.dst_input.text().split(",") if t.strip()]

        if not sources or not targets:
            QMessageBox.warning(self, "Validation Error", "Please specify valid Source and Target folders.")
            return

        norm_sources = {os.path.abspath(os.path.normpath(s)) for s in sources}
        norm_targets = {os.path.abspath(os.path.normpath(t)) for t in targets}
        overlap = norm_sources & norm_targets
        if overlap:
            QMessageBox.warning(
                self, "Validation Error",
                f"Source and Target cannot be the same folder: {', '.join(overlap)}\n"
                "This would make the sync engine race against itself."
            )
            return

        self.accept()

    def get_job(self) -> SyncJob:
        sources = [s.strip().strip('"').strip("'") for s in self.src_input.text().split(",") if s.strip()]
        targets = [t.strip().strip('"').strip("'") for t in self.dst_input.text().split(",") if t.strip()]
        job_id = self.job.id if (self.job and self.job.id) else str(uuid.uuid4())

        try:
            return SyncJob(
                id=job_id,
                name=self.name_input.text().strip() or "Untitled Job",
                sources=sources,
                targets=targets,
                mode=SyncMode(self.mode_combo.currentText()),
                schedule_type=ScheduleType(self.schedule_combo.currentText()),
                interval_minutes=self.interval_picker.value()
            )
        except Exception as e:
            QMessageBox.critical(self, "Configuration Error", f"Unable to save job:\n{e}")
            return self.job


class MainWindow(QMainWindow):
    def __init__(self, app_mode: AppMode, config_dir: pathlib.Path, install_dir: pathlib.Path = None):
        super().__init__()
        self.app_mode = app_mode
        self.config_dir = config_dir
        self.install_dir = install_dir
        self.force_quit = False
        self.worker = None
        self.setWindowTitle(f"SyncDrive Studio [{self.app_mode.value.upper()}]")
        self.resize(1150, 720)
        self.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET)

        self.engine = SyncEngine()
        self.jobs = [
            SyncJob(
                name="Smart Photo Backup",
                sources=["C:/Data"],
                targets=["E:/BackupDrive"],
                mode=SyncMode.ONE_WAY_BACKUP,
                schedule_type=ScheduleType.ON_FILE_CHANGE,
                interval_minutes=15
            )
        ]

        self.smart_watchers = []
        self.pending_job_ids = set()  # jobs whose file-change trigger fired while busy
        self.init_ui()
        self.init_system_tray()
        self.refresh_job_tree()
        self.init_drive_watcher()
        self.init_timers_and_smart_watchers()

    def init_ui(self):
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Compact Top Ribbon Toolbar
        toolbar = QFrame()
        toolbar.setObjectName("ToolbarFrame")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)

        btn_new = QPushButton("➕ New Job")
        btn_new.setObjectName("RibbonBtn")
        btn_new.clicked.connect(self.add_job)
        tb_layout.addWidget(btn_new)

        btn_edit = QPushButton("✏️ Edit Task")
        btn_edit.setObjectName("RibbonBtn")
        btn_edit.clicked.connect(self.edit_job)
        tb_layout.addWidget(btn_edit)

        btn_del = QPushButton("🗑️ Delete")
        btn_del.setObjectName("RibbonBtn")
        btn_del.clicked.connect(self.delete_job)
        tb_layout.addWidget(btn_del)

        self.btn_toggle_active = QPushButton("⏸ Pause Task")
        self.btn_toggle_active.setObjectName("RibbonBtn")
        self.btn_toggle_active.clicked.connect(self.toggle_selected_job_active)
        tb_layout.addWidget(self.btn_toggle_active)

        tb_layout.addSpacing(15)

        self.btn_analyze = QPushButton("🔍 Analyze (Preview)")
        self.btn_analyze.setObjectName("RibbonBtnPrimary")
        self.btn_analyze.clicked.connect(lambda: self.run_job(force_dry_run=True))
        tb_layout.addWidget(self.btn_analyze)

        self.btn_sync = QPushButton("🔄 Sync Now")
        self.btn_sync.setObjectName("RibbonBtnPrimary")
        self.btn_sync.setStyleSheet("background-color: #00B894;")
        self.btn_sync.clicked.connect(lambda: self.run_job(force_dry_run=False))
        tb_layout.addWidget(self.btn_sync)

        self.btn_stop = QPushButton("🛑 Stop")
        self.btn_stop.setObjectName("StopBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_current_job)
        tb_layout.addWidget(self.btn_stop)

        tb_layout.addSpacing(15)

        # Fast Schedule Selector Bar
        tb_layout.addWidget(QLabel("Trigger:"))
        self.quick_schedule_combo = QComboBox()
        self.quick_schedule_combo.addItems([s.value for s in ScheduleType])
        self.quick_schedule_combo.currentTextChanged.connect(self.on_quick_schedule_changed)
        tb_layout.addWidget(self.quick_schedule_combo)

        self.quick_interval_picker = IntervalPicker()
        self.quick_interval_picker.valueChanged.connect(self.on_quick_interval_changed)
        tb_layout.addWidget(self.quick_interval_picker)

        self.dry_run_cb = QCheckBox("Dry-Run")
        self.dry_run_cb.setToolTip("Scans drive differences without performing file changes.")
        tb_layout.addWidget(self.dry_run_cb)

        tb_layout.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setFixedHeight(18)
        tb_layout.addWidget(self.progress_bar)

        layout.addWidget(toolbar)

        # 2. Compact Source <-> Target Header Bar
        conn_frame = QFrame()
        conn_frame.setObjectName("ConnectionHeader")
        conn_frame.setFixedHeight(40)
        conn_layout = QHBoxLayout(conn_frame)
        conn_layout.setContentsMargins(10, 2, 10, 2)

        src_card = QFrame()
        src_card.setObjectName("PathCard")
        src_c_layout = QHBoxLayout(src_card)
        src_c_layout.setContentsMargins(6, 2, 6, 2)
        self.src_lbl = QLabel("📁 Source: (Select a job)")
        self.src_lbl.setStyleSheet("font-weight: bold; color: #00ADB5;")
        src_c_layout.addWidget(self.src_lbl)
        conn_layout.addWidget(src_card, 1)

        arrow_lbl = QLabel(" ↔ ")
        arrow_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #6C5CE7;")
        conn_layout.addWidget(arrow_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        dst_card = QFrame()
        dst_card.setObjectName("PathCard")
        dst_c_layout = QHBoxLayout(dst_card)
        dst_c_layout.setContentsMargins(6, 2, 6, 2)
        self.dst_lbl = QLabel("💾 Target: (Select a job)")
        self.dst_lbl.setStyleSheet("font-weight: bold; color: #00B894;")
        dst_c_layout.addWidget(self.dst_lbl)
        conn_layout.addWidget(dst_card, 1)

        last_run_card = QFrame()
        last_run_card.setObjectName("PathCard")
        last_run_c_layout = QHBoxLayout(last_run_card)
        last_run_c_layout.setContentsMargins(6, 2, 6, 2)
        self.last_run_lbl = QLabel("🕓 Last synced: —")
        self.last_run_lbl.setStyleSheet("font-weight: bold; color: #B8BAD6;")
        last_run_c_layout.addWidget(self.last_run_lbl)
        conn_layout.addWidget(last_run_card, 1)

        layout.addWidget(conn_frame)

        # 2b. Dashboard stat cards — quick at-a-glance overview
        stats_frame = QFrame()
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(14, 10, 14, 10)
        stats_layout.setSpacing(10)

        def make_stat_card(caption: str):
            card = QFrame()
            card.setObjectName("StatCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(4, 2, 4, 2)
            card_layout.setSpacing(0)
            value_lbl = QLabel("0")
            value_lbl.setObjectName("StatValueLbl")
            caption_lbl = QLabel(caption)
            caption_lbl.setObjectName("StatCaptionLbl")
            card_layout.addWidget(value_lbl)
            card_layout.addWidget(caption_lbl)
            stats_layout.addWidget(card, 1)
            return value_lbl

        self.stat_total_jobs_lbl = make_stat_card("Total Tasks")
        self.stat_active_watchers_lbl = make_stat_card("Live Watchers")
        self.stat_paused_lbl = make_stat_card("Paused Tasks")
        stats_layout.addStretch()
        layout.addWidget(stats_frame)

        # 3. Main Splitter View (No vast empty space)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Panel: Job Tree & Status Badge
        left_widget = QWidget()
        left_box = QVBoxLayout(left_widget)
        left_box.setContentsMargins(4, 4, 4, 4)

        self.watcher_status_lbl = QLabel("👁️ Live Auto-Sync: Idle")
        self.watcher_status_lbl.setStyleSheet("color: #00B894; font-weight: bold; padding: 2px;")
        left_box.addWidget(self.watcher_status_lbl)

        self.job_tree = QTreeWidget()
        self.job_tree.setHeaderLabel("All Sync Tasks")
        self.job_tree.currentItemChanged.connect(self.on_job_tree_selected)
        left_box.addWidget(self.job_tree)

        splitter.addWidget(left_widget)

        # Right Panel: Diff Comparison View + Realtime Log Output
        right_container = QWidget()
        rc_layout = QVBoxLayout(right_container)
        rc_layout.setContentsMargins(4, 4, 4, 4)

        self.diff_tree = QTreeWidget()
        self.diff_tree.setHeaderLabels(["Action Item / File", "Left Source", "Direction", "Right Target", "Status"])
        self.diff_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.diff_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        rc_layout.addWidget(self.diff_tree, 2)
        self._diff_showing_placeholder = False
        self.set_diff_empty_state("No file changes yet — click Analyze (Preview) or Sync Now to compare folders.")

        self.diagnostics_lbl = QLabel("")
        self.diagnostics_lbl.setWordWrap(True)
        self.diagnostics_lbl.setStyleSheet("color: #E74C3C; font-weight: bold; padding: 2px;")
        self.diagnostics_lbl.setVisible(False)
        rc_layout.addWidget(self.diagnostics_lbl)

        log_header = QLabel("Real-Time Change Log & Sync Activity")
        log_header.setStyleSheet("color: #8E8EA8; font-weight: bold; margin-top: 4px;")
        rc_layout.addWidget(log_header)

        self.log_output = QTextEdit()
        self.log_output.setFixedHeight(140)
        self.log_output.setReadOnly(True)
        rc_layout.addWidget(self.log_output, 1)

        splitter.addWidget(right_container)
        splitter.setSizes([230, 920])

        layout.addWidget(splitter)
        self.setCentralWidget(main_widget)

    def init_system_tray(self):
        """Configures System Tray for background watching when minimized or closed."""
        self.tray_icon = QSystemTrayIcon(self)
        
        icon_path = (self.install_dir or self.config_dir) / "app_icon.ico"
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))

        tray_menu = QMenu()
        show_action = QAction("Open SyncDrive Studio", self)
        show_action.triggered.connect(self.show_normal_and_raise)
        
        hide_action = QAction("Minimize to Tray", self)
        hide_action.triggered.connect(self.hide)

        quit_action = QAction("Exit Completely", self)
        quit_action.triggered.connect(self.exit_app_completely)

        tray_menu.addAction(show_action)
        tray_menu.addAction(hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.show()

    def show_normal_and_raise(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal_and_raise()

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                QTimer.singleShot(0, self.hide)
                self.tray_icon.showMessage(
                    "SyncDrive Studio",
                    "Running in background. Double-click tray icon to restore.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
        super().changeEvent(event)

    def refresh_job_tree(self):
        self.job_tree.clear()
        backup_node = QTreeWidgetItem(self.job_tree, ["📁 One-Way Backup Tasks"])
        mirror_node = QTreeWidgetItem(self.job_tree, ["🪞 Mirror Tasks"])
        twoway_node = QTreeWidgetItem(self.job_tree, ["🔄 Bidirectional Tasks"])

        for job in self.jobs:
            status_icon = "⚡" if job.is_active else "⏸"
            text = f"{status_icon} {job.name}"
            if job.mode == SyncMode.ONE_WAY_BACKUP:
                item = QTreeWidgetItem(backup_node, [text])
            elif job.mode == SyncMode.ONE_WAY_MIRROR:
                item = QTreeWidgetItem(mirror_node, [text])
            else:
                item = QTreeWidgetItem(twoway_node, [text])
            item.setData(0, Qt.ItemDataRole.UserRole, job.id)
            if not job.is_active:
                item.setForeground(0, QColor("#5A5B72"))
                item.setToolTip(0, "Paused — won't run on schedule or file changes")

        self.job_tree.expandAll()
        self.update_stat_cards()

    def update_stat_cards(self):
        total = len(self.jobs)
        paused = sum(1 for j in self.jobs if not j.is_active)
        active_watchers = getattr(self, "active_watchers_count", 0)
        self.stat_total_jobs_lbl.setText(str(total))
        self.stat_active_watchers_lbl.setText(str(active_watchers))
        self.stat_paused_lbl.setText(str(paused))

    def get_selected_job(self) -> SyncJob:
        item = self.job_tree.currentItem()
        if item and item.data(0, Qt.ItemDataRole.UserRole):
            job_id = item.data(0, Qt.ItemDataRole.UserRole)
            for j in self.jobs:
                if j.id == job_id:
                    return j
        return self.jobs[0] if self.jobs else None

    def on_job_tree_selected(self, current, previous):
        job = self.get_selected_job()
        if job:
            src_str = ", ".join(job.sources) if job.sources else "None"
            dst_str = ", ".join(job.targets) if job.targets else "None"
            self.src_lbl.setText(f"📁 Source: {src_str}")
            self.dst_lbl.setText(f"💾 Target: {dst_str}")

            last_run_str = job.last_run_at if job.last_run_at else "never"
            self.last_run_lbl.setText(f"🕓 Last synced: {last_run_str}")

            self.btn_toggle_active.setText("▶ Resume Task" if not job.is_active else "⏸ Pause Task")

            # Sync quick toolbar widgets without infinite loop
            self.quick_schedule_combo.blockSignals(True)
            self.quick_schedule_combo.setCurrentText(job.schedule_type.value)
            self.quick_schedule_combo.blockSignals(False)
            self.quick_interval_picker.blockSignals(True)
            self.quick_interval_picker.set_minutes(job.interval_minutes)
            self.quick_interval_picker.setEnabled(job.schedule_type == ScheduleType.INTERVAL)
            self.quick_interval_picker.blockSignals(False)

            self.log_output.append(f"ℹ️ Selected task: '{job.name}' [{job.mode.value}]")

    def toggle_selected_job_active(self):
        job = self.get_selected_job()
        if job:
            job.is_active = not job.is_active
            self.btn_toggle_active.setText("▶ Resume Task" if not job.is_active else "⏸ Pause Task")
            state = "resumed" if job.is_active else "paused"
            self.log_output.append(f"{'▶️' if job.is_active else '⏸️'} Task '{job.name}' {state}.")
            self.refresh_job_tree()
            self.init_timers_and_smart_watchers()
            self.update_stat_cards()

    def on_quick_schedule_changed(self, schedule_val: str):
        job = self.get_selected_job()
        if job:
            job.schedule_type = ScheduleType(schedule_val)
            self.quick_interval_picker.setEnabled(job.schedule_type == ScheduleType.INTERVAL)
            self.init_timers_and_smart_watchers()

    def on_quick_interval_changed(self, interval_val: int):
        job = self.get_selected_job()
        if job:
            job.interval_minutes = interval_val
            self.init_timers_and_smart_watchers()

    def add_job(self):
        dialog = ModernJobDialog(self)
        if dialog.exec():
            new_job = dialog.get_job()
            if new_job:
                self.jobs.append(new_job)
                self.refresh_job_tree()
                self.init_timers_and_smart_watchers()

    def edit_job(self):
        job = self.get_selected_job()
        if job:
            dialog = ModernJobDialog(self, job=job)
            if dialog.exec():
                updated_job = dialog.get_job()
                if updated_job:
                    idx = self.jobs.index(job)
                    self.jobs[idx] = updated_job
                    self.refresh_job_tree()
                    self.init_timers_and_smart_watchers()

    def delete_job(self):
        job = self.get_selected_job()
        if job:
            self.jobs.remove(job)
            self.refresh_job_tree()
            self.init_timers_and_smart_watchers()

    def init_drive_watcher(self):
        self.watcher = DriveWatcherThread()
        self.watcher.drive_connected.connect(self.on_drive_plugged_in)
        self.watcher.start()

    def _create_change_callback(self, job: SyncJob):
        def _callback(event_type: str, filename: str):
            self.on_smart_change(job, event_type, filename)
        return _callback

    def init_timers_and_smart_watchers(self):
        for w in self.smart_watchers:
            w.stop()
        self.smart_watchers.clear()

        active_watchers_count = 0
        watcher_warnings = []

        for job in self.jobs:
            if not job.is_active:
                continue

            if job.schedule_type == ScheduleType.INTERVAL:
                timer = QTimer(self)
                interval_ms = job.interval_minutes * 60 * 1000
                timer.timeout.connect(lambda j=job: self.execute_job_instance(j, dry_run=False))
                timer.start(interval_ms)
                self.log_output.append(f"⏱️ Scheduled timer active: '{job.name}' ({job.interval_minutes}m)")

            elif job.schedule_type == ScheduleType.ON_FILE_CHANGE:
                if not WATCHDOG_AVAILABLE:
                    watcher_warnings.append(f"'{job.name}': real-time watching module ('watchdog') is not installed/bundled in this build.")
                    continue

                valid_paths = [os.path.abspath(os.path.normpath(p)) for p in job.sources if pathlib.Path(p).exists()]
                missing_paths = [p for p in job.sources if not pathlib.Path(p).exists()]
                if missing_paths:
                    watcher_warnings.append(f"'{job.name}': source path(s) not found: {', '.join(missing_paths)}")

                if valid_paths:
                    callback_slot = self._create_change_callback(job)
                    watcher = SmartFolderWatcherManager(valid_paths, callback=callback_slot, debounce_seconds=job.debounce_seconds)
                    watcher.bridge.watcher_error.connect(lambda msg, j=job: self.on_watcher_error(j, msg))
                    watcher.start()
                    self.smart_watchers.append(watcher)
                    if watcher.active:
                        active_watchers_count += 1
                        self.log_output.append(f"👁️ Real-time Watcher Active: '{job.name}' monitoring {len(valid_paths)} folder(s)")
                    else:
                        watcher_warnings.append(f"'{job.name}': watcher failed to start (see log).")

        if watcher_warnings:
            for w in watcher_warnings:
                self.log_output.append(f"⚠️ Auto-Sync issue — {w}")
        self.set_diagnostics(watcher_warnings)

        if active_watchers_count > 0:
            self.watcher_status_lbl.setText(f"👁️ Auto-Sync Active ({active_watchers_count} Task[s])")
            self.watcher_status_lbl.setStyleSheet("color: #00B894; font-weight: bold;")
        elif watcher_warnings:
            self.watcher_status_lbl.setText(f"⚠️ Auto-Sync: {len(watcher_warnings)} issue(s) — see log")
            self.watcher_status_lbl.setStyleSheet("color: #E74C3C; font-weight: bold;")
        else:
            self.watcher_status_lbl.setText("👁️ Auto-Sync: Idle")
            self.watcher_status_lbl.setStyleSheet("color: #8E8EA8; font-weight: normal;")

        self.active_watchers_count = active_watchers_count
        self.update_stat_cards()

    def on_watcher_error(self, job: SyncJob, message: str):
        self.log_output.append(f"⚠️ Watcher error for '{job.name}': {message}")

    def on_smart_change(self, job: SyncJob, event_type: str, filename: str):
        if self.worker and self.worker.isRunning():
            self.pending_job_ids.add(job.id)
            self.log_output.append(f"🔔 Realtime Event: [{event_type}] '{filename}' in '{job.name}' -> sync busy, queued.")
            return
        self.log_output.append(f"🔔 Realtime Event: [{event_type}] '{filename}' in '{job.name}' -> Auto Syncing...")
        self.execute_job_instance(job, dry_run=False)

    def on_drive_plugged_in(self, mountpoint: str):
        self.log_output.append(f"🔌 Drive Plugged In: {mountpoint}")
        for job in self.jobs:
            if job.schedule_type == ScheduleType.ON_DRIVE_CONNECT and job.is_active:
                if any(mountpoint in t for t in job.targets):
                    self.execute_job_instance(job, dry_run=False)

    def stop_current_job(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log_output.append("🛑 Stopping job execution...")

    def run_job(self, force_dry_run: bool = False):
        job = self.get_selected_job()
        if job:
            is_dry = force_dry_run or self.dry_run_cb.isChecked()
            self.execute_job_instance(job, dry_run=is_dry)

    def execute_job_instance(self, job: SyncJob, dry_run: bool):
        if self.worker and self.worker.isRunning():
            return  # Prevent overlapping runs

        self.btn_analyze.setEnabled(False)
        self.btn_sync.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.diff_tree.clear()

        mode_str = "ANALYZE PREVIEW" if dry_run else "LIVE SYNC"
        self.log_output.append(f"\n--- Running '{job.name}' [{mode_str}] ---")

        self.worker = SyncWorker(self.engine, job, dry_run)
        self.worker.progress_update.connect(lambda pct, msg: (self.progress_bar.setValue(pct), self.log_output.append(msg)))
        self.worker.action_item_signal.connect(self.add_diff_tree_item)
        self.worker.error_signal.connect(lambda err: QMessageBox.critical(self, "Error", err))
        self.worker.finished_signal.connect(self.on_sync_finished)
        self.worker.start()

    def set_diff_empty_state(self, message: str):
        self.diff_tree.clear()
        placeholder = QTreeWidgetItem(self.diff_tree, [message, "", "", "", ""])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        font = placeholder.font(0)
        font.setItalic(True)
        placeholder.setFont(0, font)
        placeholder.setForeground(0, QColor("#5A5B72"))
        self._diff_showing_placeholder = True

    def set_diagnostics(self, warnings: List[str]):
        if warnings:
            self.diagnostics_lbl.setText("⚠️ " + "  |  ".join(warnings))
            self.diagnostics_lbl.setVisible(True)
        else:
            self.diagnostics_lbl.clear()
            self.diagnostics_lbl.setVisible(False)

    def add_diff_tree_item(self, item_data: dict):
        if self._diff_showing_placeholder:
            self.diff_tree.clear()
            self._diff_showing_placeholder = False
        direction = "➡️" if item_data["action_type"] == "COPY_TO_TARGET" else ("⬅️" if item_data["action_type"] == "COPY_TO_SOURCE" else "❌")
        tree_item = QTreeWidgetItem(self.diff_tree, [
            os.path.basename(item_data["source"] if item_data["source"] != "-" else item_data["target"]),
            item_data["source"],
            direction,
            item_data["target"],
            item_data["reason"]
        ])
        if item_data["action_type"] == "DELETE_TARGET":
            tree_item.setForeground(4, QColor("#E74C3C"))

    def on_sync_finished(self, actions):
        self.btn_analyze.setEnabled(True)
        self.btn_sync.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.log_output.append(f"✅ Sync Finished. Operations: {len(actions)}\n")
        if not actions:
            self.set_diff_empty_state("No differences found — source and target are already in sync.")

        finished_job = self.worker.job if self.worker else None
        if finished_job and not self.worker.dry_run:
            finished_job.last_run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if self.get_selected_job() and self.get_selected_job().id == finished_job.id:
                self.last_run_lbl.setText(f"🕓 Last synced: {finished_job.last_run_at}")

        if self.pending_job_ids:
            next_job_id = self.pending_job_ids.pop()
            next_job = next((j for j in self.jobs if j.id == next_job_id), None)
            if next_job:
                self.log_output.append(f"🔁 Running queued change for '{next_job.name}'...")
                QTimer.singleShot(0, lambda j=next_job: self.execute_job_instance(j, dry_run=False))

    def exit_app_completely(self):
        self.force_quit = True
        self.close()

    def closeEvent(self, event):
        if not self.force_quit:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "SyncDrive Studio Active",
                "App minimized to System Tray. Background watchers remain active.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            self.watcher.stop()
            for w in self.smart_watchers:
                w.stop()
            self.tray_icon.hide()
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if getattr(sys, 'frozen', False):
        exe_path = pathlib.Path(sys.executable)
        exe_dir = exe_path.parent
    else:
        exe_path = pathlib.Path(__file__)
        exe_dir = exe_path.parent

    mode_file = exe_dir / ".app_mode"
    selected_mode = None
    target_install_dir = None

    is_installed_instance = mode_file.exists() and (exe_dir.name == "SyncDrive Studio")

    if is_installed_instance:
        selected_mode = AppMode.PORTABLE if mode_file.read_text().strip() == AppMode.PORTABLE.value else AppMode.INSTALLED
        target_install_dir = exe_dir
    else:
        wizard = SetupWizardDialog()
        if wizard.exec() == QDialog.DialogCode.Accepted:
            selected_mode = wizard.selected_mode
            if selected_mode == AppMode.INSTALLED:
                target_install_dir = pathlib.Path(wizard.custom_install_path)
            else:
                target_install_dir = exe_dir
            try:
                mode_file.write_text(selected_mode.value)
            except Exception:
                pass
        else:
            sys.exit(0)

    config_dir = exe_dir / ".config" if selected_mode == AppMode.PORTABLE else pathlib.Path.home() / ".syncdrive_studio"
    config_dir.mkdir(parents=True, exist_ok=True)

    if selected_mode == AppMode.INSTALLED and getattr(sys, 'frozen', False) and target_install_dir:
        try:
            target_install_dir.mkdir(parents=True, exist_ok=True)
            installed_exe = target_install_dir / "SyncDriveStudio.exe"

            if exe_path.resolve() != installed_exe.resolve():
                shutil.copy2(exe_path, installed_exe)
                try:
                    (target_install_dir / ".app_mode").write_text(AppMode.INSTALLED.value)
                except Exception:
                    pass

            desktop_shortcut = pathlib.Path(os.path.expanduser("~/Desktop")) / "SyncDrive Studio.lnk"
            start_menu_shortcut = pathlib.Path(os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs")) / "SyncDrive Studio.lnk"
            icon_file = exe_dir / "app_icon.ico"

            create_windows_shortcut(installed_exe, desktop_shortcut, icon_file)
            create_windows_shortcut(installed_exe, start_menu_shortcut, icon_file)
        except PermissionError:
            if sys.platform.startswith("win"):
                QMessageBox.warning(
                    None,
                    "Administrator Required",
                    f"Writing to '{target_install_dir}' requires Administrator rights.\nPlease right-click the setup file and select 'Run as Administrator'."
                )
                sys.exit(1)

    window = MainWindow(app_mode=selected_mode, config_dir=config_dir, install_dir=target_install_dir)
    window.show()
    sys.exit(app.exec())
