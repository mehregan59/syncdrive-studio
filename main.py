import sys
import os
import shutil
import subprocess
import importlib.util
import multiprocessing
import pathlib
from enum import Enum

# List of required packages
REQUIRED_PACKAGES = {
    "PyQt6": "PyQt6",
    "pydantic": "pydantic",
    "psutil": "psutil"
}

def auto_install_dependencies():
    """Checks for required packages and displays a visual progress bar during installation."""
    missing = [pkg for pkg, imp in REQUIRED_PACKAGES.items() if importlib.util.find_spec(imp) is None]

    if missing:
        print("\n==================================================")
        print(" [SyncDrive Studio] First-Time Setup Detected")
        print(f" Installing required libraries: {', '.join(missing)}")
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
        print("\n\n✅ All dependencies successfully installed!\n")

# Run auto-installer only when running as source
if not getattr(sys, 'frozen', False):
    auto_install_dependencies()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel, QTextEdit, QCheckBox, QComboBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QMessageBox,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from models import SyncJob, SyncMode, ConflictPolicy, ScheduleType
from engine import SyncEngine
from drive_detector import DriveWatcherThread


DARK_STYLESHEET = """
QMainWindow { background-color: #121212; }
QWidget { color: #E0E0E0; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QGroupBox { font-weight: bold; border: 1px solid #2D2D2D; border-radius: 8px; margin-top: 12px; padding-top: 10px; background-color: #1E1E1E; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #00ADB5; }
QPushButton { background-color: #00ADB5; color: #FFFFFF; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background-color: #00FFF5; color: #121212; }
QPushButton:disabled { background-color: #333333; color: #777777; }
QLineEdit, QComboBox, QTextEdit, QListWidget { background-color: #252525; border: 1px solid #333333; border-radius: 6px; padding: 6px; color: #EEEEEE; }
QProgressBar { border: 1px solid #333333; border-radius: 6px; text-align: center; background-color: #252525; }
QProgressBar::chunk { background-color: #00ADB5; border-radius: 5px; }
QRadioButton { color: #EEEEEE; font-size: 13px; padding: 4px; }
"""


class AppMode(str, Enum):
    PORTABLE = "portable"
    INSTALLED = "installed"


class SetupWizardDialog(QDialog):
    """First-run installation wizard to choose between Portable or Install Mode."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SyncDrive Studio - Setup Wizard")
        self.setFixedSize(500, 320)
        self.setStyleSheet(DARK_STYLESHEET)
        self.selected_mode = AppMode.PORTABLE

        layout = QVBoxLayout(self)

        title = QLabel("Welcome to SyncDrive Studio")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ADB5; margin-bottom: 5px;")
        subtitle = QLabel("Select how you would like to run the application on this machine:")
        subtitle.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Selection Group
        mode_group = QGroupBox("Deployment Mode")
        mode_box = QVBoxLayout(mode_group)

        self.radio_portable = QRadioButton("📁 Portable Mode (Recommended for USB Drives)")
        self.radio_portable.setChecked(True)
        lbl_portable = QLabel("   • Stores configurations in the app folder.\n   • No registry modifications or system files written.")
        lbl_portable.setStyleSheet("color: #888888; font-size: 11px;")

        self.radio_install = QRadioButton("💻 System Install Mode (Recommended for Desktop PCs)")
        lbl_install = QLabel("   • Stores profiles in User AppData (~/.syncdrive_studio).\n   • Includes uninstaller tool and system integration.")
        lbl_install.setStyleSheet("color: #888888; font-size: 11px;")

        mode_box.addWidget(self.radio_portable)
        mode_box.addWidget(lbl_portable)
        mode_box.addSpacing(10)
        mode_box.addWidget(self.radio_install)
        mode_box.addWidget(lbl_install)

        layout.addWidget(mode_group)

        # Action Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm & Launch")
        self.buttons.accepted.connect(self.on_confirm)
        layout.addWidget(self.buttons)

    def on_confirm(self):
        if self.radio_install.isChecked():
            self.selected_mode = AppMode.INSTALLED
        else:
            self.selected_mode = AppMode.PORTABLE
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

                # Perform copy/delete operations
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
    """Redesigned Job Creation Dialog with Top Selectors and Visual Dual Drive Cards."""
    def __init__(self, parent=None, job: SyncJob = None):
        super().__init__(parent)
        self.setWindowTitle("Configure Sync Job")
        self.resize(650, 480)
        self.setStyleSheet(DARK_STYLESHEET)
        self.job = job

        layout = QVBoxLayout(self)

        # Top Configuration Bar
        top_group = QGroupBox("1. Execution Settings & Sync Mode")
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
        top_layout.addRow("Trigger Schedule:", self.schedule_combo)

        layout.addWidget(top_group)

        # Middle Dual Section (Source vs Targets)
        drive_section = QHBoxLayout()

        # Left Card: Sources
        src_group = QGroupBox("2. Source Drive / Folders")
        src_box = QVBoxLayout(src_group)
        self.src_input = QLineEdit(", ".join(job.sources) if job else "")
        self.src_input.setPlaceholderText("Select or enter folder paths...")
        src_browse = QPushButton("📁 Browse Source")
        src_browse.clicked.connect(self.browse_source)
        src_box.addWidget(self.src_input)
        src_box.addWidget(src_browse)
        drive_section.addWidget(src_group)

        # Right Card: Targets
        dst_group = QGroupBox("3. Target Drives / Folders")
        dst_box = QVBoxLayout(dst_group)
        self.dst_input = QLineEdit(", ".join(job.targets) if job else "")
        self.dst_input.setPlaceholderText("Select target drives/folders...")
        dst_browse = QPushButton("💾 Browse Target")
        dst_browse.clicked.connect(self.browse_target)
        dst_box.addWidget(self.dst_input)
        dst_box.addWidget(dst_browse)
        drive_section.addWidget(dst_group)

        layout.addLayout(drive_section)

        # Dialog Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            current = [s.strip() for s in self.src_input.text().split(",") if s.strip()]
            current.append(folder)
            self.src_input.setText(", ".join(current))

    def browse_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder / Drive")
        if folder:
            current = [t.strip() for t in self.dst_input.text().split(",") if t.strip()]
            current.append(folder)
            self.dst_input.setText(", ".join(current))

    def get_job(self) -> SyncJob:
        sources = [s.strip() for s in self.src_input.text().split(",") if s.strip()]
        targets = [t.strip() for t in self.dst_input.text().split(",") if t.strip()]

        return SyncJob(
            id=self.job.id if self.job else None,
            name=self.name_input.text().strip(),
            sources=sources,
            targets=targets,
            mode=SyncMode(self.mode_combo.currentText()),
            schedule_type=ScheduleType(self.schedule_combo.currentText())
        )


class MainWindow(QMainWindow):
    def __init__(self, app_mode: AppMode, config_dir: pathlib.Path):
        super().__init__()
        self.app_mode = app_mode
        self.config_dir = config_dir
        self.setWindowTitle(f"SyncDrive Studio [{self.app_mode.value.upper()} MODE]")
        self.resize(1000, 680)
        self.setStyleSheet(DARK_STYLESHEET)

        self.engine = SyncEngine()
        self.jobs = [
            SyncJob(
                name="Multi-Drive Photo Backup",
                sources=["C:/Photos"],
                targets=["E:/Drive_Backup1", "F:/Drive_Backup2"],
                mode=SyncMode.ONE_WAY_BACKUP,
                schedule_type=ScheduleType.ON_DRIVE_CONNECT
            )
        ]

        self.init_ui()
        self.refresh_job_list()
        self.init_drive_watcher()

    def init_ui(self):
        main_widget = QWidget()
        layout = QHBoxLayout(main_widget)

        # Left Sidebar Panel
        left_panel = QVBoxLayout()
        left_group = QGroupBox("Active Jobs")
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

        # Uninstall / Cleanup Data Button
        uninstall_btn = QPushButton("🗑️ Uninstall / Wipe Setup Data")
        uninstall_btn.setStyleSheet("background-color: #D9534F; color: white; margin-top: 10px;")
        uninstall_btn.clicked.connect(self.run_uninstall)
        left_box.addWidget(uninstall_btn)

        left_panel.addWidget(left_group)

        # Right Dashboard Panel
        right_panel = QVBoxLayout()

        # Visual Dashboard Cards
        dash_group = QGroupBox("Live Execution Dashboard")
        dash_layout = QVBoxLayout(dash_group)

        self.status_label = QLabel(f"Status: Ready ({self.app_mode.value.capitalize()} Mode)")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #00ADB5;")
        dash_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        dash_layout.addWidget(self.progress_bar)

        ctrl_layout = QHBoxLayout()
        self.dry_run_cb = QCheckBox("Dry Run Mode (Simulate without file changes)")
        ctrl_layout.addWidget(self.dry_run_cb)

        self.run_btn = QPushButton("▶ Run Selected Job")
        self.run_btn.setStyleSheet("font-size: 14px; padding: 10px;")
        self.run_btn.clicked.connect(self.run_job)
        ctrl_layout.addWidget(self.run_btn)

        dash_layout.addLayout(ctrl_layout)
        right_panel.addWidget(dash_group)

        # Activity Log Card
        log_group = QGroupBox("Live Report & Activity Log")
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
            self.job_list.addItem(f"⚡ {j.name} [{j.mode.value}]")
        if self.jobs:
            self.job_list.setCurrentRow(0)

    def on_job_selected(self, index: int):
        if 0 <= index < len(self.jobs):
            job = self.jobs[index]
            self.log_output.append(f"ℹ️ Selected: '{job.name}' | Sources: {len(job.sources)} | Targets: {len(job.targets)}")

    def add_job(self):
        dialog = ModernJobDialog(self)
        if dialog.exec():
            self.jobs.append(dialog.get_job())
            self.refresh_job_list()

    def edit_job(self):
        idx = self.job_list.currentRow()
        if idx >= 0:
            dialog = ModernJobDialog(self, job=self.jobs[idx])
            if dialog.exec():
                self.jobs[idx] = dialog.get_job()
                self.refresh_job_list()

    def delete_job(self):
        idx = self.job_list.currentRow()
        if idx >= 0:
            del self.jobs[idx]
            self.refresh_job_list()

    def run_uninstall(self):
        reply = QMessageBox.warning(
            self,
            "Uninstall & Clear Data",
            f"Are you sure you want to remove all configuration data?\n\nTarget directory:\n{self.config_dir}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self.config_dir.exists():
                shutil.rmtree(self.config_dir, ignore_errors=True)
            QMessageBox.information(self, "Uninstall Complete", "Setup data and profiles have been completely removed.")
            self.close()

    def init_drive_watcher(self):
        self.watcher = DriveWatcherThread()
        self.watcher.drive_connected.connect(self.on_drive_plugged_in)
        self.watcher.start()

    def on_drive_plugged_in(self, mountpoint: str):
        self.log_output.append(f"🔌 Drive Attached: {mountpoint}")
        for job in self.jobs:
            if job.schedule_type == ScheduleType.ON_DRIVE_CONNECT and job.is_active:
                if any(mountpoint in t for t in job.targets):
                    self.log_output.append(f"🚀 Auto-triggering: '{job.name}'")
                    self.execute_job_instance(job, dry_run=False)

    def run_job(self):
        idx = self.job_list.currentRow()
        if idx < 0:
            QMessageBox.critical(self, "Error", "No job selected!")
            return
        job = self.jobs[idx]
        self.execute_job_instance(job, dry_run=self.dry_run_cb.isChecked())

    def execute_job_instance(self, job: SyncJob, dry_run: bool):
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        mode_str = "DRY RUN SIMULATION" if dry_run else "LIVE SYNC"
        self.status_label.setText(f"Status: Running {job.name} ({mode_str})...")
        self.log_output.append(f"\n--- Starting {job.name} [{mode_str}] ---")

        self.worker = SyncWorker(self.engine, job, dry_run)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.error_signal.connect(self.on_error)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, percent: int, msg: str):
        self.progress_bar.setValue(percent)
        self.log_output.append(msg)

    def on_error(self, err_msg: str):
        self.run_btn.setEnabled(True)
        self.status_label.setText("Status: Error encountered!")
        self.log_output.append(f"❌ ERROR: {err_msg}")
        QMessageBox.critical(self, "Sync Error", f"An error occurred during execution:\n{err_msg}")

    def on_finished(self, actions):
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("Status: Completed successfully")
        self.log_output.append(f"✅ Sync Finished. Total actions planned/executed: {len(actions)}\n")

    def closeEvent(self, event):
        self.watcher.stop()
        event.accept()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)

    # Determine Base Executable Directory
    if getattr(sys, 'frozen', False):
        exe_dir = pathlib.Path(sys.executable).parent
    else:
        exe_dir = pathlib.Path(__file__).parent

    mode_file = exe_dir / ".app_mode"
    portable_config_dir = exe_dir / ".config"
    installed_config_dir = pathlib.Path.home() / ".syncdrive_studio"

    selected_mode = None
    config_dir = None

    # Check for existing mode file
    if mode_file.exists():
        mode_str = mode_file.read_text().strip()
        selected_mode = AppMode.PORTABLE if mode_str == AppMode.PORTABLE.value else AppMode.INSTALLED
    else:
        # Prompt First-Run Wizard
        wizard = SetupWizardDialog()
        if wizard.exec() == QDialog.DialogCode.Accepted:
            selected_mode = wizard.selected_mode
            try:
                mode_file.write_text(selected_mode.value)
            except Exception:
                pass  # Read-only location fallback
        else:
            sys.exit(0)

    # Assign configuration storage path based on selected mode
    if selected_mode == AppMode.PORTABLE:
        config_dir = portable_config_dir
    else:
        config_dir = installed_config_dir

    config_dir.mkdir(parents=True, exist_ok=True)

    window = MainWindow(app_mode=selected_mode, config_dir=config_dir)
    window.show()
    sys.exit(app.exec())
