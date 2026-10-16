# Pico P2: decode CameraImageListener switch table and constructor camera config.
# OFFLINE ONLY; only SHA-pinned saved ELFs; no ADB or HMD operations.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    python -m unittest pico.tests.test_k0_listener_xrefs pico.tests.test_k0_listener_table -v
    if ($LASTEXITCODE -ne 0) { throw 'Static routing tests failed; analysis stopped' }
    if (-not $EvidenceDir) {
        $dirRec = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $dirRec) { throw 'Saved Pico vendor ELF evidence missing' }
        $EvidenceDir = $dirRec.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    $camera = Join-Path $dir 'libpvrtrackingcamera.so'
    foreach ($item in @(
        @{ Path=$camera; Hash='cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' },
        @{ Path=$service; Hash='45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' }
    )) {
        if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) { throw "Missing $($item.Path)" }
        if ((Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Hash) { throw "Unexpected vendor ELF SHA256: $($item.Path)" }
    }
    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
        $env:ANDROID_SDK_ROOT
    } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $bin = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin'
    $dump = Join-Path $bin 'llvm-objdump.exe'
    $read = Join-Path $bin 'llvm-readelf.exe'
    foreach ($tool in @($dump, $read)) {
        if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Missing tool: $tool" }
    }
    Write-Host '=== Listener ARM64 jump-table byte mapping ==='
    python -m pico.tools.audit_k0_listener_table --service $service --output (Join-Path $dir 'p2-k0-listener-switch-table.json')
    if ($LASTEXITCODE -ne 0) { throw 'Static listener switch-table failed; no source conclusion' }
    $regions = @(
        @{ Name='01-CameraManager-constructor-prologue'; Elf=$service; First='0xa70e0'; Last='0xa7190' },
        @{ Name='02-CameraManager-constructor-init-A-B'; Elf=$service; First='0xa7190'; Last='0xa7258' },
        @{ Name='03-CameraManager-constructor-loop-end'; Elf=$service; First='0xa7258'; Last='0xa7330' },
        @{ Name='04-CameraManager-onFrame-adjustment'; Elf=$service; First='0xaae7c'; Last='0xaaf08' },
        @{ Name='05-PvrQuickCamera-listener-registration'; Elf=$camera; First='0x6397c'; Last='0x63a60' }
    )
    foreach ($item in $regions) {
        $arguments = @('-d', '--demangle', '--no-show-raw-insn', "--start-address=$($item.First)", "--stop-address=$($item.Last)", $item.Elf)
        $lines = @(& $dump @arguments)
        if ($LASTEXITCODE -ne 0 -or $lines.Count -lt 8) { throw "Failed source window: $($item.Name)" }
        $lines | Set-Content -LiteralPath (Join-Path $dir ($item.Name + '.txt')) -Encoding utf8
        Write-Host "=== $($item.Name) ==="
        $lines | Select-Object -Skip 3 -First 90
    }
    Write-Host '=== Other service vtable GOT and listener callsite candidates ==='
    python -m pico.tools.audit_k0_listener_xrefs --camera $camera --service $service --objdump $dump --readelf $read --output (Join-Path $dir 'p2-listener-xrefs-with-vtable-candidates.txt') --summary
    if ($LASTEXITCODE -ne 0) { throw 'Offline XREF scan failed' }
    Write-Host "Private source traces saved to: $dir"
    Write-Host 'OBSERVE ONLY. exact_time=false; live_lighthouse_correction_allowed=false'
}
finally {
    Pop-Location
}
