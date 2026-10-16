# Pico P2: private, static firmware clock provenance collection.
# Reads known ELF files with ADB and disassembles narrow historical call sites.
# NO on-device execution beyond 'test -f', no SLAM injection, no camera opens.
[CmdletBinding()]
param([string] $Serial = '192.168.23.12:5555')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
    $env:ANDROID_SDK_ROOT
} else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$ndkRoot = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin'
$objdump = Join-Path $ndkRoot 'llvm-objdump.exe'
if (-not (Test-Path $objdump)) { throw "LLVM objdump missing: $objdump" }

$local = Join-Path $repo ('pico\build\p2-static-clock-private-' +
    (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $local | Out-Null

$files = @(
    @{
        Name = 'libpvrtrackingcamera.so'
        Hash = 'cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee'
        Ranges = @(
            @{ Name = 'camera-AImage-getTimestamp'; From='0x3a720'; To='0x3aa20' },
            @{ Name = 'camera-processFrame'; From='0x3c540'; To='0x3c780' },
            @{ Name = 'quickcamera-dequeue'; From='0x664d0'; To='0x66740' }
        )
    },
    @{
        Name = 'libpvrtrackingservice.so'
        Hash = '45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de'
        Ranges = @(
            @{ Name = 'service-K0-timestamp-copy'; From='0xacc80'; To='0xace80' },
            @{ Name = 'service-writeToSm'; From='0xab5d0'; To='0xab820' }
        )
    }
)

$manifest = @()
foreach ($item in $files) {
    $found = $null
    foreach ($candidate in @("/system/lib64/$($item.Name)", "/vendor/lib64/$($item.Name)")) {
        $check = @(& adb -s $Serial shell su -c "test -f $candidate && echo FOUND")
        if ($LASTEXITCODE -eq 0 -and $check -contains 'FOUND') {
            $found = $candidate
            break
        }
    }
    if (-not $found) { throw "Library not located: $($item.Name)" }

    $binary = Join-Path $local $item.Name
    & adb -s $Serial pull $found $binary
    if ($LASTEXITCODE -ne 0) { throw "ADB pull failed: $found" }
    $sha = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
    $match = $sha -eq $item.Hash
    $manifest += "name=$($item.Name) path=$found sha256=$sha matches_20261013=$match"
    if (-not $match) {
        $manifest | Set-Content -Encoding utf8 (Join-Path $local 'manifest.txt')
        throw "Firmware hash changed for $($item.Name); old disassembly VAs are not safe to reuse."
    }

    # Imported clock APIs are useful negative/positive evidence but not proof
    # of the clock semantics of AImage timestamps returned by the HAL.
    $dyn = @(& $objdump '--dynamic-syms' '--demangle' $binary)
    if ($LASTEXITCODE -ne 0) { throw "Dynamic symbol read failed: $($item.Name)" }
    $dyn | Select-String -Pattern 'AImage_getTimestamp|systemTime|clock_gettime|qtimer|GetTime|elapsedRealtime|boottime' |
        ForEach-Object { $_.Line } |
        Set-Content -Encoding utf8 (Join-Path $local ($item.Name + '.clock-imports.txt'))

    foreach ($range in $item.Ranges) {
        $args = @('--disassemble', '--demangle', '--no-show-raw-insn',
            "--start-address=$($range.From)", "--stop-address=$($range.To)", $binary)
        $result = @(& $objdump @args)
        if ($LASTEXITCODE -ne 0) {
            throw "llvm-objdump failed for $($item.Name) $($range.Name)"
        }
        $target = Join-Path $local ($range.Name + '.txt')
        $result | Set-Content -Encoding utf8 $target
        if ($result.Count -lt 8) {
            Write-Warning "Sparse disassembly in $($range.Name); verify offsets and ELF mapping."
        }
    }
}
$manifest | Set-Content -Encoding utf8 (Join-Path $local 'manifest.txt')

$extract = Join-Path $local 'clock-call-edges.txt'
Get-ChildItem -LiteralPath $local -Filter '*.txt' |
    Where-Object { $_.Name -notin @('clock-call-edges.txt', 'manifest.txt') } |
    ForEach-Object {
        "===== $($_.Name) ====="
        Select-String -LiteralPath $_.FullName -Pattern '\bbl\b|AImage_getTimestamp|systemTime|qtimer|clock_gettime|GetTime' |
            Select-Object -First 65 |
            ForEach-Object { $_.Line }
    } | Set-Content -Encoding utf8 $extract

Write-Host "PASS: firmware static evidence stored locally: $local"
Get-Content -LiteralPath (Join-Path $local 'manifest.txt')
Write-Host "Call edges: $extract"
Write-Host 'NO raw binaries, disassembly, private calibration, or timestamps uploaded to GitHub/Drive.'
