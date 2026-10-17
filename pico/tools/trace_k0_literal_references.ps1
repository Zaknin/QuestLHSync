# PICO P2: verify both timestamp ROM pairs and their static ADRP+load references.
# Uses only saved SHA-pinned PVR ELF and LLVM disassembler; no HMD/ADB.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python -m unittest pico.tests.test_k0_literal_references pico.tests.test_k0_alternate_constants -v
    if ($LASTEXITCODE -ne 0) { throw 'Static reference regression tests FAILED' }

    if (-not $EvidenceDir) {
        $folder = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $folder) { throw 'Saved private Pico ELF folder missing' }
        $EvidenceDir = $folder.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    if (-not (Test-Path -LiteralPath $service -PathType Leaf)) { throw "Service ELF missing: $service" }
    $expect = '45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de'
    if ((Get-FileHash -LiteralPath $service -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expect) {
        throw 'ELF SHA256 mismatch; cannot apply fixed source address mapping'
    }
    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
        $env:ANDROID_SDK_ROOT
    } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $objdump = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe'
    if (-not (Test-Path -LiteralPath $objdump -PathType Leaf)) { throw "Offline LLVM objdump missing: $objdump" }

    $out = Join-Path $dir 'p2-k0-timestamp-literal-references.json'
    python -m pico.tools.audit_k0_literal_references --service $service --objdump $objdump --output $out
    if ($LASTEXITCODE -ne 0) { throw 'Literal cross-reference analysis failed' }
    Write-Host "Full private report: $out"
    Write-Host 'No literal load alone proves the active mode or optical exposure instant.'
    Write-Host 'OBSERVE ONLY; exact_time=false; no tracking changes.'
}
finally {
    Pop-Location
}
