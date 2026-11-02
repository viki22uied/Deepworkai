# Builds the marketplace package on Windows: DeepWorkAi.lplug4 with the app bundled inside.
# Usage (from the repo root, in PowerShell):   .\packaging\build-windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "1/4  Python dependencies"
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt pyinstaller | Out-Null

Write-Host "2/4  Building DeepWorkAI.exe"
if (Test-Path build) { Remove-Item build -Recurse -Force }
python -m PyInstaller packaging/DeepWorkAI.spec --distpath build/app --workpath build/work --noconfirm
if (-not (Test-Path build/app/DeepWorkAI/DeepWorkAI.exe)) { throw "App build failed" }

Write-Host "3/4  Smoke test"
python packaging/smoke_test.py build/app/DeepWorkAI/DeepWorkAI.exe

Write-Host "4/4  Packing the plugin"
Push-Location deepworkai/plugin
npm ci
npm run build:prod
npx logitoolkit pack
Pop-Location
Get-ChildItem deepworkai/plugin/*.lplug4 | ForEach-Object { "Done: $($_.FullName)  ($([math]::Round($_.Length/1MB,1)) MB)" }
