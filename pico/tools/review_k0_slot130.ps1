# P2 diagnostic only: replay saved 1,204 K0 frames and inspect third timestamp.
# Does not connect to the headset and cannot change Pico/SteamVR tracking.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python -m unittest pico.tests.test_qtimer_bridge pico.tests.test_shadow_k0_time pico.tests.test_k0_slot130 -v
    if ($LASTEXITCODE -ne 0) { throw 'Offline timing regression tests failed; no slot130 analysis' }

    if (-not $EvidenceDir) {
        $found = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'qtimer-p2-private-*' |
            Sort-Object Name -Descending | Select-Object -First 1
        if (-not $found) { throw 'No private paired PVR/K0 clock recording found' }
        $EvidenceDir = $found.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $before = Join-Path $dir 'before.txt'
    $k0 = Join-Path $dir 'k0.csv'
    $after = Join-Path $dir 'after.txt'
    foreach ($file in @($before, $k0, $after)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Missing paired clock evidence: $file"
        }
    }
    $out = Join-Path $dir 'slot130-audit.json'
    python -m pico.tools.audit_k0_slot130 --before $before --csv $k0 --after $after --output $out --summary
    if ($LASTEXITCODE -ne 0) { throw 'Offline slot130 audit failed' }
    Write-Host "Private detailed result: $out"
    Write-Host 'OBSERVE ONLY: neither physical exposure nor exact_time verified.'
}
finally {
    Pop-Location
}
