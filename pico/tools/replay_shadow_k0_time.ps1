# Pico P2 shadow timestamp analyzer: OFFLINE ONLY (no ADB calls).
# Uses the private captures produced by capture_qtimer_bridge.ps1.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    python -m unittest pico.tests.test_qtimer_bridge pico.tests.test_shadow_k0_time -v
    if ($LASTEXITCODE -ne 0) { throw 'Offline regression tests failed; no shadow projection run' }
    if (-not $EvidenceDir) {
        $pick = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'qtimer-p2-private-*' |
            Sort-Object Name -Descending | Select-Object -First 1
        if (-not $pick) { throw 'No private QTIMER P2 recording found' }
        $EvidenceDir = $pick.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $before = Join-Path $dir 'before.txt'
    $after = Join-Path $dir 'after.txt'
    $k0 = Join-Path $dir 'k0.csv'
    foreach ($file in @($before, $after, $k0)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Missing evidence: $file"
        }
    }
    $out = Join-Path $dir 'shadow.json'
    python .\pico\tools\audit_shadow_k0_time.py --before $before --csv $k0 --after $after --output $out
    if ($LASTEXITCODE -ne 0) { throw 'QTIMER shadow diagnostic failed' }
    Write-Host "Private output: $out"
    Write-Host 'DIAGNOSTIC ONLY; F records, exact_time, SteamVR poses unchanged.'
}
finally {
    Pop-Location
}
