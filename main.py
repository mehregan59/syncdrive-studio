import sys
import os
import time
import shutil
import subprocess
import importlib.util
import multiprocessing
import pathlib
import ctypes
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
    """Checks for required packages and installs missing ones with visual progress."""
    missing = [pkg for pkg, imp in REQUIRED_PACKAGES.items() if importlib.util.find_spec(imp) is None]

    if missing:
        print("\n==================================================")
        print(" [SyncDrive Studio] First-Time Setup & Module Check")
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
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon
from models import SyncJob, SyncMode, ConflictPolicy, ScheduleType
from engine import SyncEngine
from drive_detector import DriveWatcherThread

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


if WATCHDOG_AVAILABLE:
    class SmartChangeHandler(FileSystemEventHandler):
        def __init__(self, callback: Callable[[], None], debounce_seconds: int = 5):
            super().__init__()
            self.callback = callback
            self.debounce_seconds = debounce_seconds
            self.last_event_time = 0

        def on_any_event(self, event):
            if event.is_directory:
                return
            
            current_time = time.time()
            if current_time - self.last_event_time > self.debounce_seconds:
                self.last_event_time = current_time
                self.callback()

    class SmartFolderWatcherThread(QThread):
        change_detected = pyqtSignal(str)

        def __init__(self, watch_paths: List[str], debounce_seconds: int = 5):
            super().__init__()
            self.watch_paths = watch_paths
            self.debounce_seconds = debounce_seconds
            self.observer = Observer()

        def run(self):
            handler = SmartChangeHandler(
                callback=self._on_change_triggered,
                debounce_seconds=self.debounce_seconds
            )

            for path_str in self.watch_paths:
                try:
                    self.observer.schedule(handler, path=path_str, recursive=True)
                except Exception as e:
                    print(f"Unable to watch path {path_str}: {e}")

            self.observer.start()
            try:
                while self.observer.is_alive():
                    time.sleep(1)
            finally:
                self.observer.stop()
                self.observer.join()

        def _on_change_triggered(self):
            self.change_detected.emit("Smart file change event detected (debounced)")

        def stop(self):
            self.observer.stop()
            self.wait()


DARK_STYLESHEET = """
QMainWindow { background-color: #121212; }
QWidget { color: #E0E0E0; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QGroupBox { font-weight: bold; border: 1px solid #2D2D2D; border-radius: 8px; margin-top: 12px; padding-top: 10px; background-color: #1E1E1E; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #00ADB5; }
QPushButton { background-color: #00ADB5; color: #FFFFFF; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background-color: #00FFF5; color: #121212; }
QPushButton:disabled { background-color: #333333; color: #777777; }
QLineEdit, QComboBox, QTextEdit, QListWidget, QSpinBox { background-color: #252525; border: 1px solid #333333; border-radius: 6px; padding: 6px; color: #EEEEEE; }
QProgressBar { border: 1px solid #333333; border-radius: 6px; text-align: center; background-color: #252525; }
QProgressBar::chunk { background-color: #00ADB5; border-radius: 5px; }
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
    """Setup Wizard with Disclaimer, Mode Selector, Custom Installation Location, and Progress Bar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SyncDrive Studio - Setup & Installation Wizard")
        self.setFixedSize(580, 520)
        self.setStyleSheet(DARK_STYLESHEET)
        
        self.selected_mode = AppMode.PORTABLE
        self.custom_install_path = str(pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SyncDrive Studio")

        layout = QVBoxLayout(self)
        
        title = QLabel("Welcome to SyncDrive Studio Setup")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ADB5;")
        layout.addWidget(title)

        # 1. Disclaimer Section
        disc_group = QGroupBox("⚠️ License & Legal Disclaimer")
        disc_box = QVBoxLayout(disc_group)
        disc_text = QTextEdit()
        disc_text.setReadOnly(True)
        disc_text.setText(
            "DISCLAIMER OF LIABILITY:\n\n"
            "SyncDrive Studio is free software created solely for personal and utility use. "
            "This software is provided 'AS-IS', WITHOUT WARRANTY OF ANY KIND, express or implied, including "
            "but not limited to the warranties of merchantability, fitness for a particular purpose, or non-infringement.\n\n"
            "In no event shall the author or copyright holders be liable for any claim, damages, data loss, "
            "drive corruption, or other liability arising from, out of, or in connection with the software "
            "or the use or other dealings in the software.\n\n"
            "By checking the box below and continuing, you acknowledge that you are using this tool at your own risk."
        )
        disc_text.setMaximumHeight(120)
        disc_box.addWidget(disc_text)

        self.accept_cb = QCheckBox("I understand and accept the disclaimer terms")
        self.accept_cb.stateChanged.connect(self.toggle_next_button)
        disc_box.addWidget(self.accept_cb)
        layout.addWidget(disc_group)

        # 2. Deployment Mode Selection
        mode_group = QGroupBox("Select Deployment Strategy")
        mode_box = QVBoxLayout(mode_group)

        self.radio_portable = QRadioButton("📁 Portable Mode (No system changes, runs from current folder/USB)")
        self.radio_portable.setChecked(True)
        self.radio_portable.toggled.connect(self.toggle_location_box)

        self.radio_install = QRadioButton("💻 System Install Mode (Copies to system, adds shortcuts)")

        mode_box.addWidget(self.radio_portable)
        mode_box.addWidget(self.radio_install)
        layout.addWidget(mode_group)

        # 3. Custom Install Directory Selector
        self.dir_group = QGroupBox("Installation Target Folder")
        dir_box = QHBoxLayout(self.dir_group)
        self.path_input = QLineEdit(self.custom_install_path)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_install_dir)
        dir_box.addWidget(self.path_input)
        dir_box.addWidget(browse_btn)
        self.dir_group.setEnabled(False)
        layout.addWidget(self.dir_group)

        # 4. Installation Progress
        self.prog_group = QGroupBox("Setup Progress")
        prog_box = QVBoxLayout(self.prog_group)
        self.install_progress = QProgressBar()
        self.install_progress.setValue(0)
        self.status_lbl = QLabel("Status: Waiting for user confirmation...")
        prog_box.addWidget(self.install_progress)
        prog_box.addWidget(self.status_lbl)
        layout.addWidget(self.prog_group)

        # Confirm Button
        self.confirm_btn = QPushButton("Install & Launch")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.start_installation)
        layout.addWidget(self.confirm_btn)

    def toggle_next_button(self):
        self.confirm_btn.setEnabled(self.accept_cb.isChecked())

    def toggle_location_box(self):
        self.dir_group.setEnabled(self.radio_install.isChecked())

    def browse_install_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Target Installation Folder")
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
            if i == 20: self.status_lbl.setText("Status: Provisioning environment...")
            elif i == 50: self.status_lbl.setText("Status: Writing binary files...")
            elif i == 80: self.status_lbl.setText("Status: Setting up shortcuts & configuration...")
            QApplication.processEvents()

        self.status_lbl.setText("Status: Installation Complete!")
        time.sleep(0.3)
        self.accept()


class SyncWorker(QThread):
    progress_update = pyqtSignal(int, str)
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

            if self.dry_run or total == 0:
                self.finished_signal.emit(actions)
                return

            for idx, action in enumerate(actions, 1):
                pct = int((idx / total) * 100)
                msg = f"[{action.action_type}] {action.target_path or action.source_path}"

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
        self.setWindowTitle("Configure Sync Job & Smart Triggers")
        self.resize(650, 520)
        self.setStyleSheet(DARK_STYLESHEET)
        self.job = job

        layout = QVBoxLayout(self)

        top_group = QGroupBox("1. Execution Settings & Smart Triggers")
        top_layout = QFormLayout(top_group)

        self.name_input = QLineEdit(job.name if job else "New Sync Job")
        top_layout.addRow("Job Name:", self.name_input)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([m.value for m in SyncMode])
        if job: self.mode_combo.setCurrentText(job.mode.value)
        top_layout.addRow("Sync Behavior:", self.mode_combo)

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

        src_group = QGroupBox("2. Source Folders")
        src_box = QVBoxLayout(src_group)
        self.src_input = QLineEdit(", ".join(job.sources) if job else "")
        src_browse = QPushButton("📁 Select Source")
        src_browse.clicked.connect(self.browse_source)
        src_box.addWidget(self.src_input)
        src_box.addWidget(src_browse)
        drive_section.addWidget(src_group)

        dst_group = QGroupBox("3. Target Drives / Folders")
        dst_box = QVBoxLayout(dst_group)
        self.dst_input = QLineEdit(", ".join(job.targets) if job else "")
        dst_browse = QPushButton("💾 Select Target")
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
        is_interval = (selected_mode == ScheduleType.INTERVAL.value)
        self.interval_spin.setEnabled(is_interval)

    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            current = [s.strip().strip('"').strip("'") for s in self.src_input.text().split(",") if s.strip()]
            current.append(folder)
            self.src_input.setText(", ".join(current))

    def browse_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder / Drive")
        if folder:
            current = [t.strip().strip('"').strip("'") for t in self.dst_input.text().split(",") if t.strip()]
            current.append(folder)
            self.dst_input.setText(", ".join(current))

    def validate_and_accept(self):
        sources = [s.strip().strip('"').strip("'") for s in self.src_input.text().split(",") if s.strip()]
        targets = [t.strip().strip('"').strip("'") for t in self.dst_input.text().split(",") if t.strip()]

        if not sources or not targets:
            QMessageBox.warning(self, "Validation Error", "Please provide at least one valid Source and Target folder.")
            return

        self.accept()

    def get_job(self) -> SyncJob:
        sources = [s.strip().strip('"').strip("'") for s in self.src_input.text().split(",") if s.strip()]
        targets = [t.strip().strip('"').strip("'") for t in self.dst_input.text().split(",") if t.strip()]

        try:
            return SyncJob(
                id=self.job.id if self.job else None,
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
        self.setWindowTitle(f"SyncDrive Studio [{self.app_mode.value.upper()} MODE]")
        self.resize(1000, 680)
        self.setStyleSheet(DARK_STYLESHEET)

        icon_path = (self.install_dir or config_dir) / "app_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.engine = SyncEngine()
        self.jobs = [
            SyncJob(
                name="Smart Photo Backup",
                sources=["C:/Photos"],
                targets=["E:/BackupDrive"],
                mode=SyncMode.ONE_WAY_BACKUP,
                schedule_type=ScheduleType.ON_FILE_CHANGE,
                interval_minutes=15
            )
        ]

        self.smart_watchers = []
        self.init_ui()
        self.refresh_job_list()
        self.init_drive_watcher()
        self.init_timers_and_smart_watchers()

    def init_ui(self):
        main_widget = QWidget()
        layout = QHBoxLayout(main_widget)

        left_panel = QVBoxLayout()
        left_group = QGroupBox("Active Sync Jobs")
        left_box = QVBoxLayout(left_group)

        self.job_list = QListWidget()
        self.job_list.currentRowChanged.connect(self.on_job_selected)
        left_box.addWidget(self.job_list)

        btn_box = QHBoxLayout()
        add_btn = QPushButton("+ New")
        add_btn.clicked.connect(self.add_job)
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self.edit_job)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_job)

        btn_box.addWidget(add_btn)
        btn_box.addWidget(edit_btn)
        btn_box.addWidget(del_btn)
        left_box.addLayout(btn_box)

        uninstall_btn = QPushButton("🗑️ Uninstall SyncDrive Studio")
        uninstall_btn.setStyleSheet("background-color: #D9534F; color: white; margin-top: 10px;")
        uninstall_btn.clicked.connect(self.run_uninstall)
        left_box.addWidget(uninstall_btn)

        left_panel.addWidget(left_group)

        right_panel = QVBoxLayout()
        dash_group = QGroupBox("Execution Engine Dashboard")
        dash_layout = QVBoxLayout(dash_group)

        self.status_label = QLabel(f"Status: Active Engine ({self.app_mode.value.capitalize()})")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #00ADB5;")
        dash_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        dash_layout.addWidget(self.progress_bar)

        ctrl_layout = QHBoxLayout()
        self.dry_run_cb = QCheckBox("Dry Run Mode (Simulate without copying)")
        ctrl_layout.addWidget(self.dry_run_cb)

        self.run_btn = QPushButton("▶ Run Selected Job")
        self.run_btn.clicked.connect(self.run_job)
        ctrl_layout.addWidget(self.run_btn)

        dash_layout.addLayout(ctrl_layout)
        right_panel.addWidget(dash_group)

        log_group = QGroupBox("Live Action Log")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        right_panel.addWidget(log_group)

        layout.addLayout(left_panel, 1)
        layout.addLayout(right_panel, 2)
        self.setCentralWidget(main_widget)

    def refresh_job_list(self):
        self.job_list.clear()
        for j in self.jobs:
            self.job_list.addItem(f"⚡ {j.name} [{j.schedule_type.value}]")
        if self.jobs:
            self.job_list.setCurrentRow(0)

    def on_job_selected(self, index: int):
        if 0 <= index < len(self.jobs):
            job = self.jobs[index]
            self.log_output.append(f"ℹ️ Selected '{job.name}' | Trigger: {job.schedule_type.value}")

    def add_job(self):
        dialog = ModernJobDialog(self)
        if dialog.exec():
            new_job = dialog.get_job()
            if new_job:
                self.jobs.append(new_job)
                self.refresh_job_list()
                self.init_timers_and_smart_watchers()

    def edit_job(self):
        idx = self.job_list.currentRow()
        if idx >= 0:
            dialog = ModernJobDialog(self, job=self.jobs[idx])
            if dialog.exec():
                updated_job = dialog.get_job()
                if updated_job:
                    self.jobs[idx] = updated_job
                    self.refresh_job_list()
                    self.init_timers_and_smart_watchers()

    def delete_job(self):
        idx = self.job_list.currentRow()
        if idx >= 0:
            del self.jobs[idx]
            self.refresh_job_list()
            self.init_timers_and_smart_watchers()

    def run_uninstall(self):
        reply = QMessageBox.warning(
            self,
            "Uninstall SyncDrive Studio",
            "Are you sure you want to uninstall SyncDrive Studio?\nThis will remove application shortcuts and config data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            desktop_link = pathlib.Path(os.path.expanduser("~/Desktop")) / "SyncDrive Studio.lnk"
            start_link = pathlib.Path(os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs")) / "SyncDrive Studio.lnk"
            
            desktop_link.unlink(missing_ok=True)
            start_link.unlink(missing_ok=True)

            mode_file = self.config_dir.parent / ".app_mode"
            mode_file.unlink(missing_ok=True)

            if self.config_dir.exists():
                shutil.rmtree(self.config_dir, ignore_errors=True)

            QMessageBox.information(self, "Uninstall Complete", "SyncDrive Studio has been successfully removed.")
            self.close()

    def init_drive_watcher(self):
        self.watcher = DriveWatcherThread()
        self.watcher.drive_connected.connect(self.on_drive_plugged_in)
        self.watcher.start()

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
                self.log_output.append(f"⏱️ Scheduled timer: '{job.name}' every {job.interval_minutes} mins")

            elif job.schedule_type == ScheduleType.ON_FILE_CHANGE and WATCHDOG_AVAILABLE:
                valid_paths = [p for p in job.sources if pathlib.Path(p).exists()]
                if valid_paths:
                    watcher = SmartFolderWatcherThread(valid_paths, debounce_seconds=job.debounce_seconds)
                    watcher.change_detected.connect(lambda msg, j=job: self.on_smart_change(j, msg))
                    watcher.start()
                    self.smart_watchers.append(watcher)
                    self.log_output.append(f"👁️ Active Kernel Watcher: '{job.name}' monitoring source folders")

    def on_smart_change(self, job: SyncJob, msg: str):
        self.log_output.append(f"🔔 {msg} for '{job.name}'")
        self.execute_job_instance(job, dry_run=False)

    def on_drive_plugged_in(self, mountpoint: str):
        self.log_output.append(f"🔌 Drive Attached: {mountpoint}")
        for job in self.jobs:
            if job.schedule_type == ScheduleType.ON_DRIVE_CONNECT and job.is_active:
                if any(mountpoint in t for t in job.targets):
                    self.execute_job_instance(job, dry_run=False)

    def run_job(self):
        idx = self.job_list.currentRow()
        if idx >= 0:
            self.execute_job_instance(self.jobs[idx], dry_run=self.dry_run_cb.isChecked())

    def execute_job_instance(self, job: SyncJob, dry_run: bool):
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        mode_str = "SIMULATION" if dry_run else "LIVE SYNC"
        self.status_label.setText(f"Status: Executing {job.name} ({mode_str})...")

        self.worker = SyncWorker(self.engine, job, dry_run)
        self.worker.progress_update.connect(lambda pct, msg: (self.progress_bar.setValue(pct), self.log_output.append(msg)))
        self.worker.error_signal.connect(lambda err: QMessageBox.critical(self, "Error", err))
        self.worker.finished_signal.connect(self.on_sync_finished)
        self.worker.start()

    def on_sync_finished(self, actions):
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("Status: Engine Idle / Ready")
        self.log_output.append(f"✅ Sync Finished. Operations: {len(actions)}\n")

    def closeEvent(self, event):
        self.watcher.stop()
        for w in self.smart_watchers:
            w.stop()
        event.accept()


# --- Application Entrypoint ---
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
