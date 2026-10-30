$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$buildPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
& $buildPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed.' }
& $buildPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; packaging stopped.' }
& $buildPython -m PyInstaller --noconfirm --clean --windowed --onedir --distpath dist-v0.5 --name VoiceCompanion --add-data 'assistant_app/mobile.html;assistant_app' --add-data 'assistant_app/assets;assistant_app/assets' --collect-all vosk --collect-submodules uvicorn --hidden-import keyring.backends.Windows main.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination (Join-Path $projectRoot 'dist-v0.5/VoiceCompanion/README.md') -Force
New-Item -ItemType Directory -Path 'dist-v0.5/VoiceCompanion/scripts' -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'allow_mobile.ps1') -Destination 'dist-v0.5/VoiceCompanion/scripts/allow_mobile.ps1' -Force
$modelSource = Join-Path $projectRoot 'models/vosk-model-small-cn-0.22'
if (Test-Path -LiteralPath $modelSource) {
    New-Item -ItemType Directory -Path 'dist-v0.5/VoiceCompanion/models' -Force | Out-Null
    Copy-Item -LiteralPath $modelSource -Destination 'dist-v0.5/VoiceCompanion/models' -Recurse -Force
}
Write-Host 'Built: dist-v0.5/VoiceCompanion/VoiceCompanion.exe (keep the entire folder together).'
