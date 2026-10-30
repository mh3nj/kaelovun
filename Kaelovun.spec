# -*- mode: python ; coding: utf-8 -*-

# Kaelovun (formerly Asset Organizer) — PyInstaller build spec.
# Always build from this file so scripts/ + branding assets ship inside the exe:
#     python -m PyInstaller Kaelovun.spec --noconfirm

import os

try:  # optional drag & drop support ships its own Tk extension files
    from PyInstaller.utils.hooks import collect_data_files
    _dnd_datas = collect_data_files('tkinterdnd2')
except Exception:
    _dnd_datas = []

# Optional: drop 7z.exe (+ 7z.dll) into vendor/7z/ to ship 7-Zip inside the app.
_vendor_7z = [('vendor/7z', 'vendor/7z')] if os.path.isdir('vendor/7z') else []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('scripts', 'scripts'),
        ('assets/icons', 'assets/icons'),
    ] + _dnd_datas + _vendor_7z,
    hiddenimports=[
        'encodings',
        'codecs',
        'charset_normalizer',
        'PIL',
        'PIL._tkinter_finder',
        'pillow_avif',
        'win32com',
        'win32com.client',
        'win32com.client.gencache',
        'win32com.client.genpy',
        'win32com.client.makepy',
        'win32com.client.dynamic',
        'pywintypes',
        'pythoncom',
        'tkinter',
        '_tkinter',
        # New modules
        'pipeline.asset_package',
        'pipeline.job',
        'pipeline.scanner',
        'pipeline.jobqueue',
        'files.archive',
        'files.archive_backends',
        'files.archive_prefs',
        'files.archive_extraction',
        'files.manifest',
        'files.workspace',
        'files.sidecar',
        'pipeline.convert',
        'ui.convert_dialog',
        'ui.summary_dialog',
        'ui.archive_settings',
        'patoolib',
        'send2trash',
        'tkinterdnd2',
        'files.storage',
        'files.preview',
        'files.cleanup',
        'files.session',
        'files.app_settings',
        'files.filename',
        'files.naming',
        'adobe.photoshop',
        'adobe.illustrator',
        'adobe.jsx_bridge',
        'adobe.recovery',
        'affinity.affinity',
        'affinity.mcp_client',
        'affinity.popups',
        'cli',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Kaelovun',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/kaelovun.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Kaelovun',
)
