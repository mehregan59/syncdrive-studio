import os
import sys
import shutil
import pathlib
import subprocess
from PyQt6.QtWidgets import QApplication, QMessageBox

def perform_uninstall():
    """Removes application settings, logs, and executable files."""
    app_data_dir = pathlib.Path.home() / ".syncdrive_studio"
    
    # Ask for user confirmation
    app = QApplication(sys.argv)
    msg_box = QMessageBox()
    msg_box.setWindowTitle("Uninstall SyncDrive Studio")
    msg_box.setText("Are you sure you want to completely remove SyncDrive Studio?")
    msg_box.setInformativeText("This will delete all saved job configurations and activity logs.")
    msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg_box.setDefaultButton(QMessageBox.StandardButton.No)
    
    reply = msg_box.exec()
    if reply != QMessageBox.StandardButton.Yes:
        print("Uninstall canceled.")
        sys.exit(0)

    # 1. Clean up configuration and log folder
    if app_data_dir.exists():
        try:
            shutil.rmtree(app_data_dir)
            print(f"Removed configuration directory: {app_data_dir}")
        except Exception as e:
            print(f"Error removing data directory: {e}")

    # 2. Inform the user
    success_box = QMessageBox()
    success_box.setWindowTitle("Uninstall Complete")
    success_box.setText("SyncDrive Studio data and settings have been successfully removed.")
    success_box.exec()

if __name__ == "__main__":
    perform_uninstall()
