# Pico P2: inspect the native CameraManager base registers and constructor literals.
# SHA-256 pinned offline ELF; no adb, camera, service, SLAM, or SteamVR actions.
[CmdletBinding()]
param([string]$EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python -m unittest pico.tests.test_k0_constructor_literal pico.tests.test_k0_listener_table -v
    if ($LASTEXITCODE -ne 0) { throw 'Offline K0 constructor and dispatch regression failed' }

    if (-not $EvidenceDir) {
        $dirRec = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'p2-static-clock-private-*' |
            Sort-Object Name -Descending | Select-Object -First 1
        if (-not $dirRec) { throw 'No previously saved private vendor ELF evidence found' }
        $EvidenceDir = $dirRec.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    $camera = Join-Path $dir 'libpvrtrackingcamera.so'
    foreach ($entry in @(
        @{ File=$service; Hash='45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' },
        @{ File=$camera; Hash='cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' }
    )) {
        if (-not (Test-Path -LiteralPath $entry.File -PathType Leaf)) { throw "Missing ELF: $($entry.File)" }
        if ((Get-FileHash -LiteralPath $entry.File -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Hash) {
            throw "Firmware ELF SHA256 mismatch: $($entry.File)"
        }
    }

    $out = Join-Path $dir 'p2-ctor-literals-and-base-layout.json'
    python -m pico.tools.audit_k0_constructor_literal --service $service --output $out
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect pinned ELF constants' }

    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
        $env:ANDROID_SDK_ROOT
    } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $objdump = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe'
    if (-not (Test-Path -LiteralPath $objdump -PathType Leaf)) { throw "Missing LLVM objdump: $objdump" }

    $sections = @(
        @{ Name='01-onFrameAvailable-register-base-and-camera-id'; ELF=$service; Start='0xaa8f4'; End='0xaaa70' },
        @{ Name='02-onFrameAvailable-derived-timestamp'; ELF=$service; Start='0xaae54'; End='0xaaf08' },
        @{ Name='03-Constructor-loop-fields'; ELF=$service; Start='0xa7144'; End='0xa720c' },
        @{ Name='04-Constructor-loop-counter'; ELF=$service; Start='0xa72b0'; End='0xa7304' }
    )
    foreach ($section in $sections) {
        $args = @('-d', '--demangle', '--no-show-raw-insn',
                  "--start-address=$($section.Start)", "--stop-address=$($section.End)", $section.ELF)
        $output = @(& $objdump @args)
        if ($LASTEXITCODE -ne 0 -or $output.Count -lt 8) {
            throw "ELF disassembly failed: $($section.Name)"
        }
        $output | Set-Content -LiteralPath (Join-Path $dir ($section.Name + '.txt')) -Encoding utf8
        Write-Host "=== $($section.Name) ==="
        $output | Select-Object -Skip 3 -First 100
    }
    Write-Host "Private ELF/base register report saved in: $dir"
    Write-Host 'Source layout != runtime config proof; QTIMER/exposure claims remain unverified.'
    Write-Host 'OBSERVE ONLY; exact_time=false; no live Lighthouse correction.'
}
finally {
    Pop-Location
}
