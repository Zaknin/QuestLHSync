# Static PowerShell 7 contract checks; no recording/device/power operation is run.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$scriptPath = Join-Path $repo 'pico\tools\capture_ch7_controlled.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {
    throw ('PowerShell parse errors: ' + (($parseErrors | ForEach-Object Message) -join '; '))
}

$source = Get-Content -LiteralPath $scriptPath -Raw
$required = @(
    "Write-P3KMarker 'BASELINE_READY'",
    "Write-P3KMarker 'OFF'",
    "Write-P3KMarker 'OFF_READY'",
    "Write-P3KMarker 'ON'",
    "Write-P3KMarker 'ON_READY'",
    "Write-P3KMarker 'SPINUP_DONE'",
    "Write-P3KMarker 'PASS_DONE'",
    '[System.Diagnostics.Stopwatch]::GetTimestamp()',
    '[System.Diagnostics.Stopwatch]::Frequency',
    'Wait-P3KActiveSeconds 20',
    'Wait-P3KActiveSeconds 25'
)
foreach ($text in $required) {
    if (-not $source.Contains($text)) { throw "Missing capture contract token: $text" }
}

$forbidden = '(?im)^\s*(adb|steamvr|powercfg|bcdedit|Set-ItemProperty|Set-Service|Start-Service|Stop-Service|Restart-Service|Invoke-Expression)\b'
if ($source -match $forbidden) { throw 'Capture script contains a prohibited device/system command.' }
if (-not $source.Contains('recording did not actively advance') -and
    -not $source.Contains('Recording size did not grow')) {
    throw 'Capture script lacks an active-recording growth preflight.'
}

Write-Output 'PASS: capture script parses under PowerShell 7 and preserves the local-marker-only contract.'
