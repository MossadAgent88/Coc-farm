# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CoC Bot.
# Build with:  pyinstaller CoCBot.spec   (build.bat does this for you)
# Produces a stable folder package at: dist\Coc-farm\Coc-farm.exe

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# Bundle the whole templates/ folder (images the bot matches against) at the
# root of the unpacked exe, where vision.py and gui.py look for it via _MEIPASS.
datas = [("templates", "templates")]
datas += [("web_gui", "web_gui")]
# customtkinter ships theme/asset files it loads at runtime.
datas += collect_data_files("customtkinter")
# The GUI renders the uploaded HTML through PySide6 QtWebEngine. Bundle Qt's
# helper processes, translations, resources, and plugins explicitly.
pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all("PySide6")
datas += pyside_datas

binaries = []
binaries += pyside_binaries
binaries += collect_dynamic_libs("PySide6")

hiddenimports = collect_submodules("cocbot")
hiddenimports += pyside_hiddenimports
hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

block_cipher = None

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Coc-farm",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # no PowerShell / console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="templates/logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Coc-farm",
)
