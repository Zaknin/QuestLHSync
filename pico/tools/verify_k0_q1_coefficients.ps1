# Pico P2: verify PVR q1 B/A timing initializer against private K0 1204-frame delta.
# OFFLINE, read-only: never touches Pico, cameras, SteamVR or SLAM.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    python -m unittest pico.tests.test_k0_q1_coefficients pico.tests.test_k0_constructor_literal -v
    if ($LASTEXITCODE -ne 0) { throw 'PVR initializer/ARM64 regression tests failed' }
    if (-not $EvidenceDir) {
        $candidate = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $candidate) { throw 'Previously saved private PVR ELF directory not found' }
        $EvidenceDir = $candidate.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    if (-not (Test-Path -LiteralPath $service -PathType Leaf)) {
        throw "Missing offline service ELF: $service"
    }
    python -m pico.tools.audit_k0_q1_coefficients --service $service --output (Join-Path $dir 'p2-q1-timing-coefficients.json')
    if ($LASTEXITCODE -ne 0) { throw 'SHA-pinned source coefficient inspection failed' }
    Write-Host "Private evidence: $(Join-Path $dir 'p2-q1-timing-coefficients.json')"
    Write-Host 'OBSERVE ONLY; exact_time=false; live correction BLOCKED.'
}
finally {
    Pop-Location
}
