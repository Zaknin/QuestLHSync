# PICO P2 callback/XREF inspection: previously-captured vendor ELF files only.
# No ADB, no HMD, no SLAM, no timestamps changed.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    python -m unittest pico.tests.test_k0_listener_xrefs -v
    if ($LASTEXITCODE -ne 0) { throw 'Listener-XREF parser tests failed' }

    if (-not $EvidenceDir) {
        $folder = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $folder) { throw 'No previously captured PVR firmware ELF found' }
        $EvidenceDir = $folder.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $camera = Join-Path $dir 'libpvrtrackingcamera.so'
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    foreach ($file in @($camera, $service)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Previously captured ELF file missing: $file"
        }
    }

    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
        $env:ANDROID_SDK_ROOT
    } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $tools = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin'
    $objdump = Join-Path $tools 'llvm-objdump.exe'
    $readelf = Join-Path $tools 'llvm-readelf.exe'
    foreach ($tool in @($objdump, $readelf)) {
        if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
            throw "Missing offline LLVM tool: $tool"
        }
    }

    $report = Join-Path $dir 'p2-listener-cross-references.txt'
    python -m pico.tools.audit_k0_listener_xrefs --camera $camera --service $service --objdump $objdump --readelf $readelf --output $report --summary
    if ($LASTEXITCODE -ne 0) { throw 'SHA-pinned ELF listener XREF analysis failed' }
    Write-Host "Full offline evidence: $report"
    Write-Host 'OBSERVE ONLY; device and driver never accessed.'
}
finally {
    Pop-Location
}
