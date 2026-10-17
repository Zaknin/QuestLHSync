# PICO P2: check compiled alternate timing constants against the existing K0 recording.
# OFFLINE ONLY, using one old SHA-pinned libpvrtrackingservice.so; no ADB.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python -m unittest pico.tests.test_k0_alternate_constants pico.tests.test_k0_q1_coefficients -v
    if ($LASTEXITCODE -ne 0) { throw 'Offline constant regression tests failed' }
    if (-not $EvidenceDir) {
        $candidate = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'p2-static-clock-private-*' |
            Sort-Object Name -Descending | Select-Object -First 1
        if (-not $candidate) { throw 'No saved private vendor ELF directory' }
        $EvidenceDir = $candidate.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    if (-not (Test-Path -LiteralPath $service -PathType Leaf)) { throw "Missing saved ELF: $service" }
    $output = Join-Path $dir 'p2-alternate-timing-literals.json'
    python -m pico.tools.audit_k0_alternate_constants --service $service --output $output
    if ($LASTEXITCODE -ne 0) { throw 'ELF RO literal scan failed' }
    Write-Host "Private literal audit: $output"
    Write-Host 'Result is about STATIC ROM constants, not runtime parameter mutation.'
    Write-Host 'OBSERVE ONLY; no device, SLAM, or SteamVR changes.'
}
finally {
    Pop-Location
}
