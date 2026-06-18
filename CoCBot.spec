# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CoC Bot.
# Build with:  pyinstaller CoCBot.spec   (build.bat does this for you)
# Produces a stable folder package at: dist\Coc-farm\Coc-farm.exe

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Bundle the whole templates/ folder (images the bot matches against) at the
# root of the unpacked exe, where vision.py and gui.py look for it via _MEIPASS.
datas = [("templates", "templates")]
datas += [("web_gui", "web_gui")]
# customtkinter ships theme/asset files it loads at runtime.
datas += collect_data_files("customtkinter")

hiddenimports = collect_submodules("cocbot")
hiddenimports += collect_submodules("webview")

block_cipher = None

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=[],
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
