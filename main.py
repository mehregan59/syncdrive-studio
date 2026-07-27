import sys
import os
import time
import uuid
import shutil
import subprocess
import importlib.util
import multiprocessing
import pathlib
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
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QIcon, QColor
from models import SyncJob, SyncMode, ConflictPolicy, ScheduleType
from engine import SyncEngine
from drive_detector import DriveWatcherThread

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


class WatchdogSignalBridge(QObject):
    file_changed = pyqtSignal(str)


if WATCHDOG_AVAILABLE:
    class RobustChangeHandler(FileSystemEventHandler):
        def __init__(self, bridge: WatchdogSignalBridge, debounce_seconds: int = 3):
            super().__init__()
            self.bridge = bridge
            self.debounce_seconds = debounce_seconds
            self.last_event_time = 0

        def on_any_event(self, event):
            if event.is_directory or "$RECYCLE.BIN" in event.src_path or event.src_path.endswith(".tmp"):
                return
            
            current_time = time.time()
            if current_time - self.last_event_time > self.debounce_seconds:
                self.last_event_time = current_time
                self.bridge.file_changed.emit(f"Change detected: {os.path.basename(event.src_path)}")

    class SmartFolderWatcherManager:
        def __init__(self, watch_paths: List[str], callback: Callable[[str], None], debounce_seconds: int = 3):
            self.watch_paths = watch_paths
            self.callback = callback
            self.bridge = WatchdogSignalBridge()
            self.bridge.file_changed.connect(self.callback)
            
            self.handler = RobustChangeHandler(self.bridge, debounce_seconds=debounce_seconds)
            self.observer = Observer()

        def start(self):
            for path_str in self.watch_paths:
                clean_path = os.path.abspath(os.path.normpath(path_str))
                if os.path.exists(clean_path):
                    try:
                        self.observer.schedule(self.handler, path=clean_path, recursive=True)
                    except Exception as e:
                        print(f"Error watching path '{clean_path}': {e}")
            self.observer.start()

        def stop(self):
            if self.observer.is_alive():
                self.observer.stop()
                self.observer.join()


GOODSYNC_STUDIO_STYLESHEET = """
QMainWindow {
    background-color: #12131C;
}

QWidget {
    color: #E2E4F0;
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 12px;
}

/* Top Toolbar Ribbon */
#ToolbarFrame {
    background-color: #1E1F2E;
    border-bottom: 1px solid #28293D;
    padding: 6px;
}

QPushButton#RibbonBtn {
    background-color: #28293D;
    color: #FFFFFF;
    border: 1px solid #3B3C54;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
}

QPushButton#RibbonBtn:hover {
    background-color: #6C5CE7;
    border-color: #7D6EEB;
}

QPushButton#RibbonBtnPrimary {
    background-color: #6C5CE7;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: bold;
    font-size: 13px;
}

QPushButton#RibbonBtnPrimary:hover {
    background-color: #7D6EEB;
}

/* Connection Header Bar */
#ConnectionHeader {
    background-color: #171824;
    border-radius: 10px;
    padding: 8px 14px;
    border: 1px solid #28293D;
}

/* Card Containers */
#DashboardCard {
    background-color: #1E1F2E;
    border-radius: 12px;
    border: 1px solid #28293D;
}

/* Trees & Tables */
QTreeWidget, QListWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background-color: #171824;
    border: 1px solid #2B2C42;
    border-radius: 8px;
    padding: 4px;
    color: #FFFFFF;
}

QHeaderView::section {
    background-color: #1E1F2E;
    color: #8E8EA8;
    padding: 6px;
    border: none;
    font-weight: bold;
}

QTreeWidget::item {
    padding: 6px;
    border-bottom: 1px solid #1E1F2E;
}

QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #6C5CE7;
    color: #FFFFFF;
}

/* Progress Bar */
QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #171824;
    text-align: center;
    color: white;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #00B894;
    border-radius: 6px;
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

    def run(self):
        try:
            actions = self.engine.plan_job(self.job)
            total = len(actions)

            for idx, action in enumerate(actions, 1):
                pct = int((idx / total) * 100) if total > 0 else 100
                msg = f"[{action.action_type}] {action.target_path or action.source_path}"

                # Emit to Diff Tree View
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

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(job.interval_minutes if job else 30)
        self.interval_spin.setSuffix(" Minutes")
        top_layout.addRow("Repeat Interval:", self.interval_spin)

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
        self.interval_spin.setEnabled(selected_mode == ScheduleType.INTERVAL.value)

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
                interval_minutes=self.interval_spin.value()
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
        self.setWindowTitle(f"SyncDrive Studio - GoodSync Style [{self.app_mode.value.upper()}]")
        self.resize(1150, 720)
        self.setStyleSheet(GOODSYNC_STUDIO_STYLESHEET)

        icon_path = (self.install_dir or config_dir) / "app_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

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
        self.init_ui()
        self.refresh_job_tree()
        self.init_drive_watcher()
        self.init_timers_and_smart_watchers()

    def init_ui(self):
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------------- 1. Top Ribbon Toolbar (GoodSync Style) ----------------
        toolbar = QFrame()
        toolbar.setObjectName("ToolbarFrame")
        tb_layout = QHBoxLayout(toolbar)

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

        tb_layout.addSpacing(20)

        self.btn_analyze = QPushButton("🔍 Analyze (Preview)")
        self.btn_analyze.setObjectName("RibbonBtnPrimary")
        self.btn_analyze.clicked.connect(lambda: self.run_job(force_dry_run=True))
        tb_layout.addWidget(self.btn_analyze)

        self.btn_sync = QPushButton("🔄 Sync Now")
        self.btn_sync.setObjectName("RibbonBtnPrimary")
        self.btn_sync.setStyleSheet("background-color: #00B894;")
        self.btn_sync.clicked.connect(lambda: self.run_job(force_dry_run=False))
        tb_layout.addWidget(self.btn_sync)

        tb_layout.addSpacing(20)

        self.dry_run_cb = QCheckBox("Dry-Run Check")
        self.dry_run_cb.setToolTip("Scans drive differences without performing file changes.")
        tb_layout.addWidget(self.dry_run_cb)

        tb_layout.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.setFixedHeight(18)
        tb_layout.addWidget(self.progress_bar)

        layout.addWidget(toolbar)

        # ---------------- 2. Source <-> Target Connector Header ----------------
        conn_frame = QFrame()
        conn_frame.setObjectName("ConnectionHeader")
        conn_layout = QHBoxLayout(conn_frame)

        self.src_lbl = QLabel("📁 Source: (Select a job)")
        self.src_lbl.setStyleSheet("font-weight: bold; color: #00ADB5;")
        
        arrow_lbl = QLabel(" ↔ ")
        arrow_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #6C5CE7;")

        self.dst_lbl = QLabel("💾 Target: (Select a job)")
        self.dst_lbl.setStyleSheet("font-weight: bold; color: #00B894;")

        conn_layout.addWidget(self.src_lbl)
        conn_layout.addWidget(arrow_lbl)
        conn_layout.addWidget(self.dst_lbl)
        conn_layout.addStretch()

        layout.addWidget(conn_frame)

        # ---------------- 3. Main Split View (Job Tree + Diff View) ----------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Panel: GoodSync Task List Tree
        self.job_tree = QTreeWidget()
        self.job_tree.setHeaderLabel("All Sync Jobs")
        self.job_tree.setFixedWidth(220)
        self.job_tree.currentItemChanged.connect(self.on_job_tree_selected)
        splitter.addWidget(self.job_tree)

        # Right Center Panel: Differential Comparison Tree Table
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
        rc_layout.addWidget(self.diff_tree)

        # Bottom Realtime Log Output
        self.log_output = QTextEdit()
        self.log_output.setFixedHeight(120)
        self.log_output.setReadOnly(True)
        rc_layout.addWidget(self.log_output)

        splitter.addWidget(right_container)
        splitter.setSizes([220, 930])

        layout.addWidget(splitter)
        self.setCentralWidget(main_widget)

    def refresh_job_tree(self):
        self.job_tree.clear()
        
        backup_node = QTreeWidgetItem(self.job_tree, ["📁 One-Way Backup Tasks"])
        mirror_node = QTreeWidgetItem(self.job_tree, ["🪞 Mirror Tasks"])
        twoway_node = QTreeWidgetItem(self.job_tree, ["🔄 Bidirectional Tasks"])

        for job in self.jobs:
            text = f"⚡ {job.name}"
            if job.mode == SyncMode.ONE_WAY_BACKUP:
                item = QTreeWidgetItem(backup_node, [text])
            elif job.mode == SyncMode.ONE_WAY_MIRROR:
                item = QTreeWidgetItem(mirror_node, [text])
            else:
                item = QTreeWidgetItem(twoway_node, [text])
            item.setData(0, Qt.ItemDataRole.UserRole, job.id)

        self.job_tree.expandAll()

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
            self.log_output.append(f"ℹ️ Selected task: '{job.name}' [{job.mode.value}]")

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
        def _callback(msg: str):
            self.on_smart_change(job, msg)
        return _callback

    def init_timers_and_smart_watchers(self):
        for w in self.smart_watchers:
            w.stop()
        self.smart_watchers.clear()

        for job in self.jobs:
            if not job.is_active:
                continue

            if job.schedule_type == ScheduleType.INTERVAL:
                timer = QTimer(self)
                interval_ms = job.interval_minutes * 60 * 1000
                timer.timeout.connect(lambda j=job: self.execute_job_instance(j, dry_run=False))
                timer.start(interval_ms)
                self.log_output.append(f"⏱️ Scheduled timer: '{job.name}' ({job.interval_minutes}m)")

            elif job.schedule_type == ScheduleType.ON_FILE_CHANGE and WATCHDOG_AVAILABLE:
                valid_paths = [os.path.abspath(os.path.normpath(p)) for p in job.sources if pathlib.Path(p).exists()]
                if valid_paths:
                    callback_slot = self._create_change_callback(job)
                    watcher = SmartFolderWatcherManager(valid_paths, callback=callback_slot, debounce_seconds=job.debounce_seconds)
                    watcher.start()
                    self.smart_watchers.append(watcher)
                    self.log_output.append(f"👁️ OS Kernel Watcher Active: '{job.name}'")

    def on_smart_change(self, job: SyncJob, msg: str):
        self.log_output.append(f"🔔 {msg} for '{job.name}' -> Executing task...")
        self.execute_job_instance(job, dry_run=False)

    def on_drive_plugged_in(self, mountpoint: str):
        self.log_output.append(f"🔌 Drive Plugged In: {mountpoint}")
        for job in self.jobs:
            if job.schedule_type == ScheduleType.ON_DRIVE_CONNECT and job.is_active:
                if any(mountpoint in t for t in job.targets):
                    self.execute_job_instance(job, dry_run=False)

    def run_job(self, force_dry_run: bool = False):
        job = self.get_selected_job()
        if job:
            is_dry = force_dry_run or self.dry_run_cb.isChecked()
            self.execute_job_instance(job, dry_run=is_dry)

    def execute_job_instance(self, job: SyncJob, dry_run: bool):
        self.btn_analyze.setEnabled(False)
        self.btn_sync.setEnabled(False)
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

    def add_diff_tree_item(self, item_data: dict):
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
        self.progress_bar.setValue(100)
        self.log_output.append(f"✅ Sync Finished. Operations: {len(actions)}\n")

    def closeEvent(self, event):
        self.watcher.stop()
        for w in self.smart_watchers:
            w.stop()
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
