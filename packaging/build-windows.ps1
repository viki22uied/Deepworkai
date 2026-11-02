# Builds the marketplace package on Windows: DeepWorkAi.lplug4 with the app bundled inside.
# Usage (from the repo root, in PowerShell):   .\packaging\build-windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Native tools write warnings to stderr, which "Stop" turns into errors on PowerShell 5.1;
# judge them by exit code instead.
function Run([scriptblock]$Cmd, [switch]$Show) {
  $ErrorActionPreference = "Continue"
  $out = & $Cmd 2>&1 | ForEach-Object { "$_" }
  if ($Show -or $LASTEXITCODE) { $out | Write-Host }
  if ($LASTEXITCODE) { throw "Failed ($LASTEXITCODE): $Cmd" }
}

Write-Host "1/4  Python dependencies"
Run { python -m pip install --upgrade pip }
Run { python -m pip install -r requirements.txt pyinstaller }

Write-Host "2/4  Building DeepWorkAI.exe"
if (Test-Path build) { Remove-Item build -Recurse -Force }
Run { python -m PyInstaller packaging/DeepWorkAI.spec --distpath build/app --workpath build/work --noconfirm }
if (-not (Test-Path build/app/DeepWorkAI/DeepWorkAI.exe)) { throw "App build failed" }

Write-Host "3/4  Smoke test"
Run { python packaging/smoke_test.py build/app/DeepWorkAI/DeepWorkAI.exe } -Show

Write-Host "4/4  Packing the plugin"
Push-Location deepworkai/plugin
Run { npm ci }
Run { npm run build:prod }
Run { npx logitoolkit pack } -Show
Pop-Location
# Logitech recommends pluginName_version.lplug4, e.g. DeepWorkAi_4_0.lplug4
$ver = (Get-Content deepworkai/plugin/package.json -Raw | ConvertFrom-Json).version.Split(".")
$out = "deepworkai/plugin/DeepWorkAi_$($ver[0])_$($ver[1]).lplug4"
Move-Item deepworkai/plugin/DeepWorkAi.lplug4 $out -Force
Get-Item $out | ForEach-Object { "Done: $($_.FullName)  ($([math]::Round($_.Length/1MB,1)) MB)" }
