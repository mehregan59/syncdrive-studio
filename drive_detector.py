import time
from typing import Set
import psutil
from PyQt6.QtCore import QThread, pyqtSignal


class DriveWatcherThread(QThread):
    # Emits drive mountpoint (e.g., "E:\\" on Windows or "/media/usb" on Linux)
    drive_connected = pyqtSignal(str)

    def __init__(self, check_interval: int = 3):
        super().__init__()
        self.check_interval = check_interval
        self._running = True
        self.known_drives: Set[str] = self._get_current_drives()

    def _get_current_drives(self) -> Set[str]:
        """Returns the set of currently connected disk mount points."""
        try:
            return {p.mountpoint for p in psutil.disk_partitions(all=False)}
        except Exception:
            return set()

    def run(self):
        """Monitors system drive changes in a background thread."""
        while self._running:
            time.sleep(self.check_interval)
            current_drives = self._get_current_drives()
            new_drives = current_drives - self.known_drives

            for drive in new_drives:
                self.drive_connected.emit(drive)

            self.known_drives = current_drives

    def stop(self):
        """Stops the thread gracefully."""
        self._running = False
        self.wait()
