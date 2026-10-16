# PICO P2: saved firmware call-chain provenance only. No ADB.
# Inspect the x5=image stamp / x6=BOOTTIME callback arguments and
# K0 ring writer; never touch a live process or clock.
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
    @{ Name='01-CameraReader-ImageAndBoot-args'; Binary=$camera; From='0x3a898'; To='0x3a940' },
    @{ Name='02-CameraReader-OutlinedHelper'; Binary=$camera; From='0x3b4c0'; To='0x3b700' },
    @{ Name='03-QuickCamera-FrameMetadata'; Binary=$camera; From='0x66600'; To='0x666dc' },
    @{ Name='04-K0-DataBuffer-Copy'; Binary=$service; From='0xaccd0'; To='0xace04' }
)
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
    $result | Select-Object -Skip 3 -First 90
}
Write-Host "COMPLETE: offline-only static evidence in $dir"
Write-Host 'Do not post binaries or device factory calibration; text excerpts only.'
