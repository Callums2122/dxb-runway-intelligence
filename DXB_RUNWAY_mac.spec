# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("PySide6.QtCharts")

a = Analysis(
    ["run_dxb_runway.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DXB RUNWAY Intelligence",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DXB RUNWAY Intelligence",
)
app = BUNDLE(
    coll,
    name="DXB RUNWAY Intelligence.app",
    icon="assets/dxb_runway.icns",
    bundle_identifier="com.callums2122.dxb-runway-intelligence",
    info_plist={
        "CFBundleShortVersionString": "3.0.0",
        "CFBundleVersion": "3.0.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
)
