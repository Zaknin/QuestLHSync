# Pico P2 native listener/parameter ownership tracing: OFFLINE ONLY.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    python -m unittest pico.tests.test_k0_listener_xrefs -v
    if ($LASTEXITCODE -ne 0) { throw 'Listener XREF safety tests failed' }

    if (-not $EvidenceDir) {
        $found = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $found) { throw 'Missing previous private firmware capture' }
        $EvidenceDir = $found.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $cam = Join-Path $dir 'libpvrtrackingcamera.so'
    $svc = Join-Path $dir 'libpvrtrackingservice.so'
    foreach ($item in @(
        @{ File=$cam; Hash='cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' },
        @{ File=$svc; Hash='45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' }
    )) {
        if (-not (Test-Path -LiteralPath $item.File -PathType Leaf)) { throw "Missing private ELF: $($item.File)" }
        $actual = (Get-FileHash -LiteralPath $item.File -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $item.Hash) { throw "SHA256 mismatch: $($item.File)" }
    }

    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
        $env:ANDROID_SDK_ROOT
    } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $objdump = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe'
    if (-not (Test-Path -LiteralPath $objdump -PathType Leaf)) { throw "llvm-objdump missing: $objdump" }

    $windows = @(
        @{ Name='01-CameraManager-constructor-parameters'; ELF=$svc; Start='0xa7190'; Stop='0xa7230' },
        @{ Name='02-CameraManager-setParameters-first'; ELF=$svc; Start='0xa89e0'; Stop='0xa8a40' },
        @{ Name='03-CameraManager-setParameters-second'; ELF=$svc; Start='0xa8ba4'; Stop='0xa8bf8' },
        @{ Name='04-CameraManager-setParameters-third'; ELF=$svc; Start='0xa8d08'; Stop='0xa8d58' },
        @{ Name='05-CameraManager-setParameters-fourth'; ELF=$svc; Start='0xa90a0'; Stop='0xa90f8' },
        @{ Name='06-CameraImageListener-forwarder'; ELF=$svc; Start='0xabbfc'; Stop='0xabc64' },
        @{ Name='07-PvrQuickCamera-setPvrImageListener'; ELF=$cam; Start='0x639e0'; Stop='0x63a70' },
        @{ Name='08-PvrCameraDevice-setPvrImageListener'; ELF=$cam; Start='0x65004'; Stop='0x65050' },
        @{ Name='09-CameraManager-collect-listener-context'; ELF=$svc; Start='0xab440'; Stop='0xab4b0' }
    )

    foreach ($window in $windows) {
        $args = @('-d', '--demangle', '--no-show-raw-insn',
                  "--start-address=$($window.Start)", "--stop-address=$($window.Stop)", $window.ELF)
        $lines = @(& $objdump @args)
        if ($LASTEXITCODE -ne 0 -or $lines.Count -lt 8) {
            throw "Unexpectedly empty disassembly: $($window.Name)"
        }
        $file = Join-Path $dir ($window.Name + '.txt')
        $lines | Set-Content -LiteralPath $file -Encoding utf8
        Write-Host "=== $($window.Name) ==="
        $lines | Select-Object -Skip 3
    }
    Write-Host '=== INTERPRETATION SAFETY ==='
    Write-Host 'Raw +0x330/+0x338 addresses may belong to unrelated objects; inspect register-base provenance.'
    Write-Host 'Matching listener vtable does NOT prove active K0 producer registration.'
    Write-Host "All text reports private in $dir"
    Write-Host 'PICO_STATUS=OFFLINE_ONLY; exact_time=false; live_lighthouse_correction_allowed=false'
}
finally {
    Pop-Location
}
