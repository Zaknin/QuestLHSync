# Pico P2 focused K0 timestamp producer provenance. OFFLINE ONLY.
# Uses owner's already saved and hash-verified Pico OS 5.11.2 ELF files.
# Does not execute code on the HMD, open cameras, or modify LHSync.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $EvidenceDir) {
    $e = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'p2-static-clock-private-*' |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $e) { throw 'Previously saved PVR static evidence is missing' }
    $EvidenceDir = $e.FullName
}
$dir = (Resolve-Path $EvidenceDir).Path
$camera = Join-Path $dir 'libpvrtrackingcamera.so'
$service = Join-Path $dir 'libpvrtrackingservice.so'
$expected = @(
    @{ Path=$camera; Hash='cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' },
    @{ Path=$service; Hash='45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' }
)
foreach ($entry in $expected) {
    if (-not (Test-Path -LiteralPath $entry.Path -PathType Leaf)) { throw "ELF missing: $($entry.Path)" }
    $digest = (Get-FileHash -LiteralPath $entry.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($digest -ne $entry.Hash) { throw "ELF SHA256 mismatch, STOP: $($entry.Path)" }
}
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
    $env:ANDROID_SDK_ROOT
} else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$objdump = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe'
if (-not (Test-Path -LiteralPath $objdump -PathType Leaf)) { throw 'NDK 27.2 llvm-objdump.exe missing' }

$regions = @(
    @{ Name='01-QuickCamera-FrameMetaDate-to-FrameItem'; Binary=$camera; Start='0x66670'; End='0x66740' },
    @{ Name='02-AImageReader-TimestampTree-and-Dispatch'; Binary=$camera; Start='0x3aa4c'; End='0x3ab30' },
    @{ Name='03-PvrImageReaderListener-FrameItem'; Binary=$camera; Start='0x3fe00'; End='0x40140' },
    @{ Name='04-CameraManager-K0-Ring-Header-Timestamps'; Binary=$service; Start='0xab7b8'; End='0xab830' },
    @{ Name='05-CameraManager-OnFrameAvailable-All-Branches'; Binary=$service; Start='0xaa8f4'; End='0xab150' }
)
foreach ($region in $regions) {
    $output = @(& $objdump '-d' '--demangle' '--no-show-raw-insn' ("--start-address=" + $region.Start) ("--stop-address=" + $region.End) $region.Binary)
    if ($LASTEXITCODE -ne 0 -or $output.Count -lt 8) { throw "Disassembly failed: $($region.Name)" }
    $file = Join-Path $dir ($region.Name + '.txt')
    $output | Set-Content -LiteralPath $file -Encoding utf8
    Write-Host "=== $($region.Name) ==="
    if ($region.Name -like '05-*') {
        # Show only calls to the main K0 writer and collection/dispatch logic.
        $matches = @($output | Select-String -Pattern 'collectCameraInfo|writeToSm|writeToExpSm|onFrameAvailable|mov\s+w2,|orr\s+w2,' -Context 5,2)
        foreach ($match in $matches) {
            $match.Context.PreContext
            $match.Line
            $match.Context.PostContext
        }
    } else {
        $output | Select-Object -Skip 3
    }
}

# No --start-address for objdump -s: some NDK versions show .dynsym
# instead of the requested .rodata segment. Read PT_LOAD ELF data
# with the independent stdlib helper and the proven effective VA.
python (Join-Path $repo 'pico\tools\elf_cstring_at_va.py') --elf $camera --va 0x254d7 --max-bytes 256
if ($LASTEXITCODE -ne 0) { throw 'Native image callback format string extraction failed' }
Write-Host 'COMPLETE: all timestamp-source evidence remains private and offline.'
Write-Host "Location: $dir"
