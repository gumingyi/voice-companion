# Run only after the current executable has been built and verified.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$latestExe = Join-Path $projectRoot 'dist-v0.5/VoiceCompanion/VoiceCompanion.exe'
if (-not (Test-Path -LiteralPath $latestExe)) { throw 'Current version not found; cleanup cancelled.' }
$smoke = Join-Path $projectRoot 'docs/verification/exe_v05_result.json'
if (-not (Test-Path -LiteralPath $smoke)) { throw 'Current executable verification record missing.' }
$checked = Get-Content -LiteralPath $smoke -Raw | ConvertFrom-Json
if (-not ($checked.window_visible -and $checked.frozen -and $checked.vosk_loaded -and $checked.web_service_started -and $checked.ui_assets_present) -or $checked.error_type) { throw 'Current executable verification failed.' }
$removed = [System.Collections.Generic.List[object]]::new()
function Remove-ProjectArtifact([string]$relative) {
    $absolute = [IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
    $prefix = $projectRoot.TrimEnd('\') + '\'
    if (-not $absolute.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing deletion outside project.' }
    if (-not (Test-Path -LiteralPath $absolute)) { return }
    $item = Get-Item -LiteralPath $absolute -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing reparse-point deletion.' }
    if ($item.PSIsContainer) {
        $links = @(Get-ChildItem -LiteralPath $absolute -Directory -Recurse -Force | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
        if ($links.Count) { throw 'Refusing directory with linked descendants.' }
        $running = @(Get-CimInstance Win32_Process -Filter "Name='VoiceCompanion.exe'" | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($absolute + '\', [StringComparison]::OrdinalIgnoreCase) })
        if ($running.Count) { throw 'An old executable is running; close it before cleanup.' }
        $size = (Get-ChildItem -LiteralPath $absolute -File -Recurse -Force | Measure-Object Length -Sum).Sum
    } else { $size = $item.Length }
    Remove-Item -LiteralPath $absolute -Recurse -Force
    $removed.Add([pscustomobject]@{path=$relative; bytes=[long]$size})
}
foreach ($relative in @('dist','dist-v0.2','dist-v0.3','dist-v0.4','build','__pycache__','.pytest_cache','assistant_app/__pycache__','tests/__pycache__','tests/.temp','docs/defense_setup','VoiceCompanion.spec','docs/UPDATE-0.2.md','docs/UPDATE-0.3.md')) {
    Remove-ProjectArtifact $relative
}
foreach ($name in @('VoiceCompanion-source.zip','VoiceCompanion-Windows-x64.zip','VoiceCompanion-source-v0.2.zip','VoiceCompanion-Windows-x64-v0.2.zip','VoiceCompanion-source-v0.3.zip','VoiceCompanion-Windows-x64-v0.3.zip','VoiceCompanion-source-v0.4.zip','VoiceCompanion-Windows-x64-v0.4.zip')) {
    Remove-ProjectArtifact ('release/' + $name)
}
$keep = @('ui','pytest-v0.5.log','pytest-v0.5.xml','build-v0.5.log','deepseek_latency.json','deepseek_ui_latency.json','streaming_windows_result.json','streaming_windows_run.log','streaming_desktop.png','mobile_lan_browser_result.json','mobile_lan.png','synthetic_chinese.wav','exe_v05_result.json','cleanup_report.json')
foreach ($item in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'docs/verification') -Force) {
    if ($keep -notcontains $item.Name) { Remove-ProjectArtifact ('docs/verification/' + $item.Name) }
}
$total = ($removed | Measure-Object bytes -Sum).Sum
$report = [pscustomobject]@{removed=$removed.ToArray(); total_bytes=[long]$total; preserved=@('dist-v0.5','source','models','.venv','examples','user settings and Windows credentials','original thesis/PPT/PDF files outside project')}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $projectRoot 'docs/verification/cleanup_report.json') -Encoding UTF8
Write-Output ('removed_items=' + $removed.Count)
Write-Output ('reclaimed_MB=' + [math]::Round($total / 1MB, 1))
