name: Build CoCBot.exe

# Builds the Windows app and publishes it as a GitHub Release whenever a
# version tag (e.g. v1.3.1) is pushed. The in-app Update button downloads
# the CoCBot.exe attached to the latest release.

on:
  push:
    tags:
      - "v*"
  workflow_dispatch: {}   # lets you trigger a build manually from the Actions tab

permissions:
  contents: write          # needed to create the Release

jobs:
  build:
    runs-on: windows-latest
    steps:
      - name: Check out code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller

      - name: Build CoCBot.exe
        run: pyinstaller --noconfirm --clean CoCBot.spec

      - name: Publish release with the exe
        uses: softprops/action-gh-release@v2
        with:
          files: dist/CoCBot.exe
          generate_release_notes: true
