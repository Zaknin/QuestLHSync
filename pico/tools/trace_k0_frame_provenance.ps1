# PICO P2: saved firmware call-chain provenance only. No ADB.
# Disambiguate camera image stamp, diagnostic formatting, the actual
# CameraManager image-ring writer and *separate* exposure metadata ring.
# No live processes, no ADB, no camera opens, no adjustments.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $EvidenceDir) {
    $e = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'p2-static-clock-private-*' |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $e) { throw 'Prior SHA-pinned PVR ELF capture not found' }
    $EvidenceDir = $e.FullName
}
$dir = (Resolve-Path $EvidenceDir).Path
$camera = Join-Path $dir 'libpvrtrackingcamera.so'
$service = Join-Path $dir 'libpvrtrackingservice.so'
$required = @(
    @{ Path = $camera; Hash = 'cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' },
    @{ Path = $service; Hash = '45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' }
)
foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
        throw "Missing offline ELF: $($item.Path)"
    }
    $hash = (Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $item.Hash) { throw "SHA256 changed; refusing old virtual addresses: $($item.Path)" }
}

$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
    $env:ANDROID_SDK_ROOT
} else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$objdump = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe'
if (-not (Test-Path -LiteralPath $objdump)) { throw "Missing NDK llvm-objdump: $objdump" }

$sections = @(
    @{ Name='01-CameraReader-ImageTimestampAndBoottime'; Binary=$camera; From='0x3a898'; To='0x3a935' },
    @{ Name='02-CameraReader-FrameTimestampDispatch'; Binary=$camera; From='0x3a928'; To='0x3aa98' },
    @{ Name='03-PrintfFormatHelper-NOT-clock-conversion'; Binary=$camera; From='0x3b4c0'; To='0x3b568' },
    @{ Name='04-CameraReader-ProcessFrame'; Binary=$camera; From='0x3be24'; To='0x3c210' },
    @{ Name='05-PvrImageReaderListener-ProcessFrame'; Binary=$camera; From='0x3fca8'; To='0x40000' },
    @{ Name='06-QuickCamera-Dequeue-And-Metadata'; Binary=$camera; From='0x66620'; To='0x66734' },
    @{ Name='07-CameraManager-WriteToSm-MAIN-image-ring'; Binary=$service; From='0xab634'; To='0xab988' },
    @{ Name='08-CameraManager-WriteToExpSm-SEPARATE-exposure-ring'; Binary=$service; From='0xacd04'; To='0xace04' }
)
# These are narrow deterministic extraction windows, not the full function
# bodies. For multiple versions, SHA validation above MUST precede them.
foreach ($part in $sections) {
    $args = @('-d','--no-show-raw-insn','--demangle',
              "--start-address=$($part.From)", "--stop-address=$($part.To)",
              $part.Binary)
    $result = @(& $objdump @args)
    if ($LASTEXITCODE -ne 0 -or $result.Count -lt 10) {
        throw "ELF disassembly failed/sparse: $($part.Name)"
    }
    $destination = Join-Path $dir ($part.Name + '.txt')
    $result | Set-Content -LiteralPath $destination -Encoding utf8
    Write-Host ("=== {0} ===" -f $part.Name)
    # Print key short blocks; full bounded disassembly is saved beside the ELFs.
    $result | Select-Object -Skip 3 -First 70
}
# 0x3a8e4 references a string literal: dump the rodata backing the
# vsnprintf formatting call, to avoid mistaking logging for synchronization.
$rodata = @(& $objdump '-s' '--start-address=0x254c0' '--stop-address=0x25550' $camera)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect callback format string' }
$rodata | Set-Content -LiteralPath (Join-Path $dir '09-Callback-Format-String.txt') -Encoding utf8
Write-Host '=== 09-CameraReader-Callback-Format-String (rodata hex + ASCII) ==='
$rodata | Select-Object -First 28

Write-Host "COMPLETE: offline-only static evidence in $dir"
Write-Host 'Do not post binaries or device factory calibration; text excerpts only.'
