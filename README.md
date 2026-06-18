# CoC Farm Bot

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?logo=windows&logoColor=white)](#requirements)
[![Release](https://img.shields.io/github/v/release/MossadAgent88/Coc-farm?label=latest%20release)](https://github.com/MossadAgent88/Coc-farm/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/MossadAgent88/Coc-farm/build.yml?label=windows%20build)](https://github.com/MossadAgent88/Coc-farm/actions)
[![License](https://img.shields.io/badge/license-see%20repo-lightgrey)](#disclaimer)

CoC Farm Bot is a Windows desktop app for running a Clash of Clans farming bot through LDPlayer. It provides a modern GUI for starting and stopping farming sessions, opening the game, saving base and army links, viewing live logs, and running manual tools such as screenshot, loot detection, and return-home actions.

> Unofficial community project. This repository is not affiliated with, endorsed by, sponsored by, or approved by Supercell.

## Download

Normal users should download the Windows build from GitHub Releases:

**[Download the latest Windows release](https://github.com/MossadAgent88/Coc-farm/releases/latest)**

Download `CoC-Farm-Bot-Windows.zip`, extract it, and run `CoC Farm Bot.exe`.

Normal users do **not** need Python, pip, Git, Visual Studio, or terminal commands when using the release ZIP.

## Quick Start

1. Download `CoC-Farm-Bot-Windows.zip` from the latest GitHub Release.
2. Extract the ZIP anywhere, for example `C:\CoC-Farm-Bot`.
3. Open LDPlayer and make sure Clash of Clans is installed.
4. Run `CoC Farm Bot.exe`.
5. Click **Open Game**.
6. Adjust settings if needed, then click **Start**.

Keep the extracted folder together. The `_internal` folder next to the `.exe` contains required runtime files.

## Screenshot

Add a screenshot or short GIF here after publishing the first release:

```text
docs/screenshot.png
```

Recommended capture: main window with the Settings tab and live Log panel visible.

## Features

| Area | What it does |
| --- | --- |
| Farming | Searches for bases, checks loot, attacks, and returns home. |
| Manual tools | Open Game, Return Home, Screenshot, Detect Loot, Manual Attack, Reload Config. |
| Logs | Streams bot output live into the GUI. |
| Settings | Saves and reloads settings using the existing `settings.json` config system. |
| Bases | Save, open, copy, and organize Clash base links. |
| Armies | Save, open, copy, and organize Clash army links. |
| Packaging | Windows `.exe` release package built with PyInstaller. |

## Requirements

For the release ZIP:

- Windows 10 or Windows 11.
- LDPlayer installed.
- Clash of Clans installed inside LDPlayer.
- LDPlayer resolution set to **1920 x 1080**.
- ADB debugging enabled in LDPlayer.

The bot is tuned for 1920 x 1080 screenshots. Other emulator resolutions can break detection.

## LDPlayer Setup

1. Install LDPlayer.
2. Install Clash of Clans from the Play Store inside LDPlayer.
3. Open LDPlayer settings.
4. Set display resolution to **1920 x 1080**.
5. Enable ADB debugging / local ADB connection.
6. Start the bot and click **Open Game**.

The app auto-detects common LDPlayer install locations, including LDPlayer 9 and newer LDPlayer folders. If LDPlayer is installed somewhere custom, set these Windows environment variables:

```text
ADB_PATH=C:\path\to\LDPlayer\adb.exe
LDCONSOLE_PATH=C:\path\to\LDPlayer\ldconsole.exe
```

Restart the app after changing environment variables.

## How To Use

### Start farming

1. Launch `CoC Farm Bot.exe`.
2. Click **Open Game**.
3. Wait until the village screen is visible.
4. Review loot and attack settings.
5. Click **Start**.

### Stop farming

Click **Stop**. The app stops the bot process and returns the GUI to idle.

### Manual actions

- **Open Game** starts LDPlayer if needed, then opens Clash of Clans.
- **Return Home** uses the bot navigation flow to reach the village screen.
- **Screenshot** saves an emulator screenshot to the normal screenshots folder and logs the path.
- **Detect Loot** reads visible loot from the current screen.
- **Attack Now** runs a manual attack using the selected side.
- **Reload Config** reloads settings from `settings.json`.

### Bases and Armies

Use the **Bases** and **Armies** tabs to save Clash links with names, town hall level, tags, and notes. Data is stored next to the app in JSON files:

- `bases.json`
- `armies.json`

## Settings

The GUI saves settings to `settings.json` in the app folder. Useful settings include:

| Setting | Meaning |
| --- | --- |
| Minimum loot | Minimum total loot before accepting a base. |
| Minimum Gold / Elixir / Dark Elixir | Resource-specific filters. |
| Max searches | Maximum number of bases to skip before giving up. |
| Attack side | Preferred attack direction or random. |
| Donations | Whether donation checks are enabled. |
| Debug screenshots | Saves additional diagnostic screenshots. |
| Fatigue / breaks | Adds human-like delays and breaks. |

If settings get confusing, close the app, move `settings.json` aside, and restart. The app will use defaults.

## Troubleshooting

### Windows says the app is unknown

The release is not code-signed. Windows SmartScreen may show a warning. Choose **More info** and **Run anyway** only if you downloaded the ZIP from this repository's GitHub Releases.

### App opens but Open Game fails

- Confirm LDPlayer is installed.
- Confirm ADB debugging is enabled in LDPlayer.
- Confirm Clash of Clans is installed inside LDPlayer.
- If LDPlayer is in a custom folder, set `ADB_PATH` and `LDCONSOLE_PATH`.

### Bot cannot detect buttons or loot

- Set LDPlayer resolution to **1920 x 1080**.
- Make sure the game is not covered by popups.
- Use **Screenshot** and check the saved image.
- Enable debug screenshots only when diagnosing problems.

### Screenshot fails

- Start LDPlayer.
- Open Clash of Clans.
- Make sure ADB is connected.
- Check the GUI log for the exact ADB error.

### The app starts but nothing happens

Check the **Log** tab. Errors are streamed there, including missing LDPlayer paths, ADB connection problems, and update-check failures.

## Updating

1. Download the newest ZIP from [GitHub Releases](https://github.com/MossadAgent88/Coc-farm/releases/latest).
2. Extract it to a new folder.
3. Copy your old `settings.json`, `bases.json`, and `armies.json` into the new folder if you want to keep them.
4. Run the new `CoC Farm Bot.exe`.

## FAQ

### Do I need Python?

No. If you download the Windows release ZIP, Python is not required.

### Do I need to run terminal commands?

No. Extract the ZIP and run the `.exe`.

### Can I move the `.exe` by itself?

No. Keep `CoC Farm Bot.exe` together with the `_internal` folder from the ZIP.

### Does this support emulators other than LDPlayer?

The current release is built around LDPlayer ADB and `ldconsole`.

### Is this affiliated with Supercell?

No. It is an unofficial community project.

## Developer Build

These steps are only for developers who want to build from source.

Requirements:

- Python 3.12 or compatible Python 3.x
- Git
- Windows

Build:

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv-build\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe -c "import webview; import clr; print('webview/pythonnet import OK')"
.\.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --clean CoCBot.spec
```

The built app is created at:

```text
dist\Coc-farm\Coc-farm.exe
```

To create a clean release ZIP locally:

```powershell
.\scripts\package_windows_release.ps1 -Build
```

## GitHub Release Process

For maintainers:

1. Merge release changes into `main`.
2. Build and test the release ZIP from a clean extracted folder.
3. Create or update the GitHub Release asset only after the EXE opens.
4. Attach `CoC-Farm-Bot-Windows.zip` and `CoC-Farm-Bot-Windows.zip.sha256`.

Manual tag command:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

## Disclaimer

This project is unofficial and is not affiliated with Supercell. Clash of Clans is a trademark of Supercell. Use this software at your own risk and review the game rules and terms before using automation.
