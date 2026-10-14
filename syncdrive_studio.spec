# -*- mode: python ; coding: utf-8 -*-
# Build with:  python -m PyInstaller syncdrive_studio.spec
# (use this spec file, not "main.py", so the icon is bundled correctly)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app_icon.ico', '.')],
    hiddenimports=[],
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
