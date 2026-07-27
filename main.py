import sys
import subprocess
import importlib.util

# List of required packages mapped to their import names
REQUIRED_PACKAGES = {
    "PyQt6": "PyQt6",
    "pydantic": "pydantic",
    "psutil": "psutil"
}

def auto_install_dependencies():
    """Checks for required packages and auto-installs missing ones via pip."""
    missing = []
    for pkg_name, import_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(import_name) is None:
            missing.append(pkg_name)

    if missing:
        print(f"Missing dependencies detected: {missing}. Installing automatically...")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", *missing
            ])
            print("Dependencies installed successfully!")
        except Exception as e:
            print(f"Failed to auto-install dependencies: {e}")
            sys.exit(1)

# Run the auto-installer BEFORE attempting imports of 3rd party libraries
auto_install_dependencies()

# --- Normal Application Imports ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel, QTextEdit, QCheckBox, QComboBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt
from models import SyncJob, SyncMode, ConflictPolicy, ScheduleType
from engine import SyncEngine
from drive_detector import DriveWatcherThread


class JobDialog(QDialog):
    """Dialog to create or edit a Sync Job with multi-drive support."""
    def __init__(self, parent=None, job: SyncJob = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Sync Job" if job else "Create New Sync Job")
        self.resize(500, 400)
        self.job = job

        layout = QFormLayout(self)

        self.name_input = QLineEdit(job.name if job else "New Sync Job")
        layout.addRow("Job Name:", self.name_input)

        self.sources_input = QLineEdit(", ".join(job.sources) if job else "C:/SourceFolder")
        layout.addRow("Sources (comma-separated):", self.sources_input)

        self.targets_input = QLineEdit(", ".join(job.targets) if job else "E:/TargetDrive1, F:/TargetDrive2")
        layout.addRow("Targets (comma-separated):", self.targets_input)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([m.value for m in SyncMode])
        if job:
            self.mode_combo.setCurrentText(job.mode.value)
        layout.addRow("Sync Mode:", self.mode_combo)

        self.policy_combo = QComboBox()
        self.policy_combo.addItems([p.value for p in ConflictPolicy])
        if job:
            self.policy_combo.setCurrentText(job.conflict_policy.value)
        layout.addRow("Conflict Policy:", self.policy_combo)

        self.schedule_combo = QComboBox()
        self.schedule_combo.addItems([s.value for s in ScheduleType])
        if job:
            self.schedule_combo.setCurrentText(job.schedule_type.value)
        layout.addRow("Schedule Trigger:", self.schedule_combo)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def get_job(self) -> SyncJob:
        sources = [s.strip() for s in self.sources_input.text().split(",") if s.strip()]
        targets = [t.strip() for t in self.targets_input.text().split(",") if t.strip()]
        
        return SyncJob(
            id=self.job.id if self.job else None,
            name=self.name_input.text().strip(),
            sources=sources,
            targets=targets,
            mode=SyncMode(self.mode_combo.currentText()),
            conflict_policy=ConflictPolicy(self.policy_combo.currentText()),
            schedule_type=ScheduleType(self.schedule_combo.currentText())
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SyncDrive Studio")
        self.resize(950, 620)

        self.engine = SyncEngine()
        self.jobs = [
            SyncJob(
                name="Multi-Drive Backup Example",
                sources=["C:/ImportantDocs"],
                targets=["E:/BackupDrive_1", "F:/BackupDrive_2"],
                mode=SyncMode.ONE_WAY_MIRROR,
                conflict_policy=ConflictPolicy.KEEP_NEWEST,
                schedule_type=ScheduleType.ON_DRIVE_CONNECT
            )
        ]

        self.init_ui()
        self.refresh_job_list()
        self.init_drive_watcher()

    def init_ui(self):
        main_widget = QWidget()
        layout = QHBoxLayout(main_widget)

        # Left Panel - Jobs List & Management
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("Sync Jobs Overview"))

        self.job_list = QListWidget()
        self.job_list.currentRowChanged.connect(self.on_job_selected)
        left_panel.addWidget(self.job_list)

        job_btn_layout = QHBoxLayout()
        add_btn = QPushButton("+ New Job")
        add_btn.clicked.connect(self.add_job)
        edit_btn = QPushButton("Edit Job")
        edit_btn.clicked.connect(self.edit_job)
        delete_btn = QPushButton("Delete Job")
        delete_btn.clicked.connect(self.delete_job)

        job_btn_layout.addWidget(add_btn)
        job_btn_layout.addWidget(edit_btn)
        job_btn_layout.addWidget(delete_btn)
        left_panel.addLayout(job_btn_layout)

        # Right Panel - Controls, Details, & Execution Logs
        right_panel = QVBoxLayout()

        opts_layout = QHBoxLayout()
        self.dry_run_cb = QCheckBox("Dry Run Mode (Simulate without modifying files)")
        opts_layout.addWidget(self.dry_run_cb)
        right_panel.addLayout(opts_layout)

        run_btn = QPushButton("▶ Run Selected Job")
        run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        run_btn.clicked.connect(self.run_job)
        right_panel.addWidget(run_btn)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        right_panel.addWidget(QLabel("Activity Log / Dry Run Execution Plan:"))
        right_panel.addWidget(self.log_output)

        layout.addLayout(left_panel, 1)
        layout.addLayout(right_panel, 2)
        self.setCentralWidget(main_widget)

    def refresh_job_list(self):
        self.job_list.clear()
        for j in self.jobs:
            self.job_list.addItem(f"{j.name} [{j.mode.value}]")
        if self.jobs:
            self.job_list.setCurrentRow(0)

    def on_job_selected(self, index: int):
        if 0 <= index < len(self.jobs):
            job = self.jobs[index]
            self.log_output.append(
                f"Selected Job: '{job.name}' | Sources: {len(job.sources)} | Targets: {len(job.targets)} | Trigger: {job.schedule_type.value}"
            )

    def add_job(self):
        dialog = JobDialog(self)
        if dialog.exec():
            new_job = dialog.get_job()
            self.jobs.append(new_job)
            self.refresh_job_list()

    def edit_job(self):
        idx = self.job_list.currentRow()
        if idx < 0:
            return
        dialog = JobDialog(self, job=self.jobs[idx])
        if dialog.exec():
            updated_job = dialog.get_job()
            self.jobs[idx] = updated_job
            self.refresh_job_list()

    def delete_job(self):
        idx = self.job_list.currentRow()
        if idx >= 0:
            del self.jobs[idx]
            self.refresh_job_list()

    def init_drive_watcher(self):
        self.watcher = DriveWatcherThread()
        self.watcher.drive_connected.connect(self.on_drive_plugged_in)
        self.watcher.start()

    def on_drive_plugged_in(self, mountpoint: str):
        self.log_output.append(f"🔌 Drive detected at {mountpoint}")
        for job in self.jobs:
            if job.schedule_type == ScheduleType.ON_DRIVE_CONNECT and job.is_active:
                if any(mountpoint in t for t in job.targets):
                    self.log_output.append(f"Auto-triggering job: '{job.name}'")
                    self.execute_job_instance(job, dry_run=False)

    def run_job(self):
        idx = self.job_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "No Job Selected", "Please select or create a job first.")
            return
        job = self.jobs[idx]
        is_dry_run = self.dry_run_cb.isChecked()
        self.execute_job_instance(job, dry_run=is_dry_run)

    def execute_job_instance(self, job: SyncJob, dry_run: bool):
        mode_str = "DRY RUN SIMULATION" if dry_run else "LIVE EXECUTION"
        self.log_output.append(f"\n--- Starting {job.name} ({mode_str}) ---")

        actions = self.engine.execute_job(
            job,
            dry_run=dry_run,
            progress_callback=lambda msg: self.log_output.append(msg)
        )

        for act in actions:
            target_str = act.target_path or act.source_path
            self.log_output.append(f"[{act.action_type}] {target_str} ({act.reason})")

        self.log_output.append("--- Task Finished ---\n")

    def closeEvent(self, event):
        self.watcher.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
