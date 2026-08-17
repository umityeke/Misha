# -*- mode: python ; coding: utf-8 -*-

import sys


platform_excludes = {
    "darwin": ["win32api", "win32com", "winreg"],
    "win32": ["AppKit", "Cocoa", "Foundation", "objc"],
    "linux": ["AppKit", "Cocoa", "Foundation", "objc", "win32api", "win32com", "winreg"],
}.get(sys.platform, [])

non_runtime_excludes = [
    "IPython",
    "cv2",
    "jupyter",
    "matplotlib",
    "notebook",
    "pytest",
    "psycopg2",
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('core/prompt.txt', 'core'),
    ],
    hiddenimports=['sounddevice'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=platform_excludes + non_runtime_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Misha',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='packaging/macos/entitlements.plist',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Misha',
)

app = BUNDLE(
    coll,
    name='Misha.app',
    icon='logo.icns',
    bundle_identifier='com.umityeke.misha',
    info_plist={
        'CFBundleDisplayName': 'Misha',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '13.0',
        'NSMicrophoneUsageDescription': 'Misha yalnızca açık sesli komut ve sahip sesi kaydı sırasında mikrofona erişir.',
        'NSCameraUsageDescription': 'Misha yalnızca açık kamera analizi komutlarında kameraya erişir.',
        'NSHighResolutionCapable': True,
    },
)
