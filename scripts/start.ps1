param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonPath) {
        $bootstrapPython = $PythonPath
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $bootstrapPython = (& py -3.10 -c 'import sys; print(sys.executable)')
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.10 x64, or supply -PythonPath.' }
    } else {
        $bootstrapPython = 'python'
    }
    & $bootstrapPython -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,12) and sys.maxsize > 2**32, "Requires Python 3.10-3.12 x64"'
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python. Python 3.8 pytorch environment is not modified.' }
    & $bootstrapPython -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed creating venv.' }
}
& $venvPython -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,12)'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported project venv Python.' }
$stamp = Join-Path $projectRoot '.venv/voicecompanion-deps-v1'
if (-not (Test-Path -LiteralPath $stamp)) {
    & $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check Internet and retry.' }
    New-Item -ItemType File -Path $stamp -Force | Out-Null
}
$modelFile = Join-Path $projectRoot 'models/vosk-model-small-cn-0.22/am/final.mdl'
if (-not (Test-Path -LiteralPath $modelFile)) {
    & $venvPython (Join-Path $PSScriptRoot 'download_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'Chinese model download failed. See README for manual installation.' }
}
& $venvPython (Join-Path $projectRoot 'main.py')
exit $LASTEXITCODE
