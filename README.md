# CoC Bot

Automated Clash of Clans bot that farms loot, donates troops, and manages your village. Runs on Windows using LDPlayer (Android emulator).

## What It Does

- Searches for bases with good loot (1.5M+ total)
- Deploys your army automatically
- Donates troops and spells to clanmates
- Requests clan castle troops
- Handles disconnects, popups, and errors automatically
- Auto-restarts if stuck for too long

## What You Need

1. **Windows 10 or 11** (any edition)
2. **Python 3.11 or newer** — [Download here](https://www.python.org/downloads/)
   - During install, check **"Add Python to PATH"**
3. **LDPlayer 9** — [Download here](https://www.ldplayer.net/)
   - Install to the default location: `C:\LDPlayer\LDPlayer9\`
4. **Clash of Clans** installed inside LDPlayer (via Play Store)

## LDPlayer Settings

Open LDPlayer and go to **Settings** (gear icon):

1. **Display** → Resolution: **1920 x 1080**
2. **Other** → Enable **ADB debugging** (Root permission: Open local connection)

These are important — the bot uses exact screen coordinates calibrated for 1920x1080.

## Setup (One Time)

Download or clone this repo to your PC and unzip it somewhere (e.g. your Desktop). Then pick **one** of the two ways below to run it — no terminal required.

> If LDPlayer is installed somewhere other than `C:\LDPlayer\LDPlayer9\`, set these environment variables once via **System Properties → Environment Variables**, otherwise the bot defaults to `C:\LDPlayer\LDPlayer9\`:
> ```
> ADB_PATH=C:\path\to\LDPlayer9\adb.exe
> LDCONSOLE_PATH=C:\path\to\LDPlayer9\ldconsole.exe
> ```

## How to Run (No Terminal)

First, **start LDPlayer** and open Clash of Clans. Wait until you're on the village screen.

### Option A — Just double-click (easiest)

Double-click **`Start CoC Bot.bat`** in the bot folder.

- The **first** time, it installs everything automatically (takes a minute — you'll see a small setup window).
- After that, it just opens the bot window instantly, with no console.
- Press **Start** to begin farming, **Stop** to stop. Closing the window also stops the bot.

You still need [Python 3.11+](https://www.python.org/downloads/) installed (tick **"Add Python to PATH"** during install), and the bot folder has to stay put.

### Option B — Build a real standalone app (CoCBot.exe)

If you'd rather have a single app you can move anywhere and pin to your taskbar:

1. Double-click **`build.bat`** once and wait for it to finish.
2. It creates **`dist\CoCBot.exe`**.
3. Move/copy **`CoCBot.exe`** wherever you like and double-click it to run. No Python folder needed after this.

> Building needs Python installed too, but only for the build step. The finished `CoCBot.exe` is fully standalone.

### Advanced — Run from a terminal (optional)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
.venv\Script