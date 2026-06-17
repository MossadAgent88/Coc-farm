from pathlib import Path

BUILD_YML = r'''name: Build Coc Farm Windows Package

# Builds a stable Windows folder package and publishes it to GitHub Releases.
# File names are intentionally fixed: archive Coc-farm.zip, folder Coc-farm,
# executable Coc-farm.exe. Version numbers belong only in app metadata/release tags.

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
      tag:
        description: "Release tag to create/update, for example v1.5.0"
        required: false
        default: ""

permissions:
  contents: write

jobs:
  build:
    runs-on: windows-latest
    steps:
      - name: Check out code
        uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Validate source
        shell: pwsh
        run: |
          python -m py_compile cocbot/army.py cocbot/event_broom.py cocbot/config.py cocbot/updater.py cocbot/actions.py cocbot/loop.py cocbot/__main__.py cocbot/__init__.py gui.py test_event_broom.py

      - name: Install dependencies
        shell: pwsh
        run: |
          python -m pip install --upgrade pip setuptools wheel
          python -m pip install -r requirements.txt
          python -m pip install pyinstaller

      - name: Build stable Windows package
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          pyinstaller `
            --noconfirm `
            --clean `
            --onedir `
            --windowed `
            --name Coc-farm `
            --add-data "templates;templates" `
            --collect-all customtkinter `
            --collect-all PIL `
            --hidden-import customtkinter `
            --hidden-import PIL.Image `
            --hidden-import cv2 `
            gui.py
          if (!(Test-Path "dist/Coc-farm/Coc-farm.exe")) {
            throw "Build failed: dist/Coc-farm/Coc-farm.exe was not created"
          }

      - name: Resolve release tag
        id: tag
        shell: pwsh
        run: |
          if ("${{ github.ref_type }}" -eq "tag") {
            $tag = "${{ github.ref_name }}"
          } elseif ("${{ inputs.tag }}") {
            $tag = "${{ inputs.tag }}"
          } else {
            $version = python -c "import re; print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', open('cocbot/__init__.py', encoding='utf-8').read()).group(1))"
            $tag = "v$version"
          }
          if (-not $tag.StartsWith('v')) { $tag = "v$tag" }
          "tag=$tag" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
          "zip=Coc-farm.zip" | Out-File -FilePath $env:GITHUB_OUTPUT -Append

      - name: Package ZIP
        shell: pwsh
        run: |
          $ErrorActionPreference = 'Stop'
          Compress-Archive -Path "dist/Coc-farm/*" -DestinationPath "${{ steps.tag.outputs.zip }}" -Force
          if (!(Test-Path "${{ steps.tag.outputs.zip }}")) {
            throw "Release archive was not created: ${{ steps.tag.outputs.zip }}"
          }

      - name: Publish release
        shell: pwsh
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          $ErrorActionPreference = 'Stop'
          $tag = "${{ steps.tag.outputs.tag }}"
          $zip = "${{ steps.tag.outputs.zip }}"
          if (!(Test-Path $zip)) { throw "Release asset missing: $zip" }
          $notes = @"
          ## Windows Package

          Download `$zip`, extract it, and run `Coc-farm.exe` inside the extracted `Coc-farm` folder.

          This build uses stable folder packaging instead of fragile one-file packaging to avoid missing Python DLL / `_MEI` temp extraction crashes.
          "@

          gh release view $tag *> $null
          $exists = ($LASTEXITCODE -eq 0)
          if (-not $exists) {
            gh release create $tag $zip --target "${{ github.sha }}" --title "$tag" --notes $notes --latest
            if ($LASTEXITCODE -eq 0) { exit 0 }
            Write-Host "Release create failed; attempting edit/upload fallback."
          }

          gh release edit $tag --title "$tag" --notes $notes --latest
          if ($LASTEXITCODE -ne 0) { throw "Failed to edit release $tag" }

          for ($i = 1; $i -le 3; $i++) {
            gh release upload $tag $zip --clobber
            if ($LASTEXITCODE -eq 0) { exit 0 }
            Write-Host "Upload attempt $i failed; retrying..."
            Start-Sleep -Seconds 5
          }
          throw "Failed to upload $zip to release $tag after retries"
'''

Path('.github/workflows/build.yml').write_text(BUILD_YML, encoding='utf-8')
for path in (
    '.github/workflows/apply-army-refactor.yml',
    '.github/workflows/apply-army-refactor-fixed.yml',
    '.github/scripts/apply_army_refactor.py',
    '.github/scripts/fix_ci_release.py',
):
    Path(path).unlink(missing_ok=True)
