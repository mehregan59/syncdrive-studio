# -*- mode: python ; coding: utf-8 -*-
#
# Build with:  pyinstaller syncdrive_studio.spec
#
# WHY THIS FILE EXISTS:
# Running `pyinstaller main.py` directly can silently produce a build where
# `watchdog` fails to import at runtime, even though `pip install watchdog`
# succeeded and the app ran fine with `python main.py`. This happens because
# watchdog picks its OS-specific observer backend (ReadDirectoryChangesW on
# Windows, inotify on Linux, FSEvents on macOS) inside watchdog/observers/,
# and PyInstaller's static import scanner does not always follow that
# selection, so the backend module gets left out of the bundle. The app then
# starts fine, but `from watchdog.observers import Observer` raises
# ImportError inside the frozen .exe, and the app falls back to
# WATCHDOG_AVAILABLE = False with no console visible to show why.
#
# collect_submodules('watchdog') below forces every watchdog submodule
# (including all platform observer backends) into the build regardless of
# which OS you build on, so the .exe always has the right backend available.

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = collect_submodules('watchdog') + [
    'watchdog.observers.winapi',
    'watchdog.observers.read_directory_changes',
    'watchdog.observers.inotify',
    'watchdog.observers.inotify_buffer',
    'watchdog.observers.inotify_c',
    'watchdog.observers.fsevents',
    'watchdog.observers.kqueue',
    'watchdog.observers.polling',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app_icon.ico', '.')],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SyncDriveStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # set True temporarily if you need to see startup errors
    icon='app_icon.ico',
)
