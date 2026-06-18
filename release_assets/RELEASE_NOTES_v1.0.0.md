# CoC Farm Bot v1.0.0 - Windows EXE Release

This release provides the verified Windows ZIP package and beginner-friendly documentation for CoC Farm Bot.

## What Changed

- Packaged the app as a Windows `.exe` release ZIP.
- Added the Claude Design GUI frontend.
- Added controller-based GUI integration with live logs.
- Added Bases and Armies libraries for Clash links.
- Connected Manual tools including Open Game, Return Home, Screenshot, Detect Loot, Manual Attack, and Reload Config.
- Added LDPlayer startup support through the existing ADB/ldconsole path system.
- Fixed Windows EXE packaging for pywebview/pythonnet so `Python.Runtime.dll` and clr-loader runtime files are bundled together.
- Added beginner-friendly README, quick-start guide, release notes, and GitHub Actions release packaging.

## Main Features

- Start and stop farming from the GUI.
- Open LDPlayer and Clash of Clans from the app.
- Stream bot logs live in the app.
- Save and copy base links.
- Save and copy army links.
- Take emulator screenshots.
- Run manual actions: Open Game, Screenshot, and Return Home.
- Reload settings from the existing config system.

## Install

1. Download `CoC-Farm-Bot-Windows.zip`.
2. Extract it to a folder such as `C:\CoC-Farm-Bot`.
3. Run `CoC Farm Bot.exe`.

No Python, pip, Git, terminal commands, or developer tools are required for the release ZIP.

## Start

1. Install LDPlayer.
2. Install Clash of Clans inside LDPlayer.
3. Set LDPlayer resolution to `1920 x 1080`.
4. Enable ADB debugging / local ADB connection.
5. Run `CoC Farm Bot.exe`.
6. Click **Open Game**.
7. Click **Start** when the village screen is ready.

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

- **Open Game fails:** verify LDPlayer is installed, ADB debugging is enabled, and Clash of Clans is installed.
- **Screenshot fails:** make sure LDPlayer is running and the game is open.
- **Detection fails:** confirm the emulator resolution is exactly `1920 x 1080`.
- **Windows SmartScreen or antivirus warning:** the app is not code-signed. Only run it if downloaded from this repository's GitHub Releases page.
- **LDPlayer path issue:** if LDPlayer is installed in a custom location, set `ADB_PATH` and `LDCONSOLE_PATH` to the matching `adb.exe` and `ldconsole.exe`.
- **Settings issue:** close the app, move `settings.json` aside, and restart to use defaults.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, sponsored by, or approved by Supercell. Clash of Clans is a trademark of Supercell. Use at your own risk.
