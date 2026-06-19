# CoC Farm Bot v1.5.5 - Python 3.14 Windows EXE Release

This release moves the source runner and packaged Windows EXE build to Python 3.14.

## What Changed

- Built the Windows EXE with Python 3.14.
- Updated local build scripts and GitHub Actions to use Python 3.14.
- Added startup logging for the exact Python runtime version.
- Added clear unsupported-version messages for older Python versions.
- Kept Python 3.15 marked experimental because PySide6 does not currently publish compatible wheels.

## Main Features

- Modern HTML GUI with live bot logs.
- Start and stop farming sessions from the GUI.
- Open LDPlayer and Clash of Clans from the app.
- Manual actions including Open Game, Screenshot, Return Home, Detect Loot, Manual Attack, and Reload Config.
- Bases and Armies tabs with JSON persistence.
- Existing farming, ADB, OCR, army, updater, config, log, and session logic preserved.

## Install

1. Download `CoC-Farm-Bot-Windows.zip`.
2. Extract it to a folder such as `C:\CoC-Farm-Bot`.
3. Run `CoC Farm Bot.exe`.

No Python, pip, Git, terminal commands, or developer tools are required for the release ZIP.

## Known Requirements

- Windows 10 or Windows 11.
- LDPlayer.
- Clash of Clans installed inside LDPlayer.
- LDPlayer resolution set to `1920 x 1080`.
- ADB debugging enabled.

If LDPlayer is installed outside common locations, set:

```text
ADB_PATH=C:\path\to\LDPlayer\adb.exe
LDCONSOLE_PATH=C:\path\to\LDPlayer\ldconsole.exe
```

## Troubleshooting

- **Windows SmartScreen or antivirus warning:** the app is not code-signed. Only run it if downloaded from this repository's GitHub Releases page.
- **Open Game fails:** verify LDPlayer is installed, ADB debugging is enabled, and Clash of Clans is installed.
- **Screenshot fails:** make sure LDPlayer is running and the game is open.
- **Detection fails:** confirm the emulator resolution is exactly `1920 x 1080`.
- **LDPlayer path issue:** if LDPlayer is installed in a custom location, set `ADB_PATH` and `LDCONSOLE_PATH`.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, sponsored by, or approved by Supercell. Clash of Clans is a trademark of Supercell. Use at your own risk.
