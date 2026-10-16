# Pico P2: compact, SHA-pinned OFFLINE audit of QuickCamera callback and ELF dependencies.
# No ADB, no Camera2 access, no runtime injection, no tracking changes.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $EvidenceDir) {
    $candidate = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $candidate) { throw 'Previously saved Pico PVR ELF evidence not found' }
    $EvidenceDir = $candidate.FullName
}
$dir = (Resolve-Path $EvidenceDir).Path
$camera = Join-Path $dir 'libpvrtrackingcamera.so'
$service = Join-Path $dir 'libpvrtrackingservice.so'
foreach ($e in @(
    @{ File=$camera; SHA='cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' },
    @{ File=$service; SHA='45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' }
)) {
    if (-not (Test-Path -LiteralPath $e.File -PathType Leaf)) { throw "Missing: $($e.File)" }
    $actual = (Get-FileHash -LiteralPath $e.File -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $e.SHA) { throw "SHA256 mismatch: $($e.File)" }
}

$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
    $env:ANDROID_SDK_ROOT
} else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$toolDir = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin'
$objdump = Join-Path $toolDir 'llvm-objdump.exe'
$readelf = Join-Path $toolDir 'llvm-readelf.exe'
foreach ($tool in @($objdump, $readelf)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Missing: $tool" }
}

function Run-Native([string]$exe, [string[]]$argv) {
    $lines = @(& $exe @argv)
    if ($LASTEXITCODE -ne 0) { throw "Native offline inspection failed: $exe $($argv -join ' ')" }
    return $lines
}

Write-Host '=== SHA256-verified offline ELF dependencies (camera/service) ==='
foreach ($elf in @($camera, $service)) {
    $lines = @(Run-Native $readelf @('--dynamic', $elf))
    $outputFile = Join-Path $dir ((Split-Path $elf -Leaf) + '.dependencies.txt')
    $lines | Set-Content -LiteralPath $outputFile -Encoding utf8
    $needed = @($lines | Select-String -Pattern '\(NEEDED\)|\(SONAME\)' | ForEach-Object { $_.Line.Trim() })
    Write-Host ("{0}:" -f (Split-Path $elf -Leaf))
    if ($needed.Count) { $needed | Select-Object -First 45 } else { Write-Host '(No NEEDED symbols displayed)' }
}

Write-Host '=== Camera callback and cross-DSO symbol references ==='
foreach ($elf in @($camera, $service)) {
    $lines = @(Run-Native $objdump @('--dynamic-syms', '--demangle', $elf))
    $save = Join-Path $dir ((Split-Path $elf -Leaf) + '.symbols.txt')
    $lines | Set-Content -LiteralPath $save -Encoding utf8
    $hits = @($lines | Select-String -Pattern 'PvrCameraDeviceCallback|PvrCameraDevice::|CameraReader::|PvrImageReaderListener::|QuickCameraClient|CameraManager::collectCameraInfo|CameraManager::onFrameAvailable|vtable for pvr::' | ForEach-Object { $_.Line })
    Write-Host ("{0}: {1} symbol matches (first 65 displayed)" -f (Split-Path $elf -Leaf), $hits.Count)
    $hits | Select-Object -First 65
}

Write-Host '=== QuickCamera callback object + vtable call (source, NOT proof of callee) ==='
$source = @(Run-Native $objdump @('-d', '--demangle', '--no-show-raw-insn', '--start-address=0x666c4', '--stop-address=0x666f4', $camera))
$source | Set-Content -LiteralPath (Join-Path $dir 'quickcamera-virtual-callback.txt') -Encoding utf8
$source | Select-Object -Skip 3

Write-Host '=== CameraManager pre-write metadata and timing adjustment ==='
$writer = @(Run-Native $objdump @('-d', '--demangle', '--no-show-raw-insn', '--start-address=0xaae70', '--stop-address=0xaaf08', $service))
$writer | Set-Content -LiteralPath (Join-Path $dir 'service-metadata-to-k0-writer.txt') -Encoding utf8
$writer | Select-Object -Skip 3

Write-Host '=== PvrImageReaderListener alternative path: relevant frame assembly ==='
$other = @(Run-Native $objdump @('-d', '--demangle', '--no-show-raw-insn', '--start-address=0x40140', '--stop-address=0x40930', $camera))
$other | Set-Content -LiteralPath (Join-Path $dir 'alternative-imagereader-frame-construction.txt') -Encoding utf8
$matches = @($other | Select-String -Pattern '\bbl\b|\bblr\b|\bstp\b.*\[sp,\s*#0x|\bstr\b.*\[sp,\s*#0x' | ForEach-Object { $_.Line })
Write-Host ("Relevant alternative-path instructions: {0}; displaying first 75" -f $matches.Count)
$matches | Select-Object -First 75

Write-Host 'RESULT: virtual callback target, QuickCamera time source and active K0 producer branch still require source-level proof.'
Write-Host "Evidence retained locally: $dir"
Write-Host 'OBSERVE ONLY. No timestamps or LHSync driver behavior changed.'
