# Pico P2: saved K0 +130 variation and source refs. OFFLINE ONLY.
[CmdletBinding()]
param([string] $EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    python -m unittest pico.tests.test_k0_slot130_variation -v
    if ($LASTEXITCODE -ne 0) { throw 'Per-frame slot130 tests failed' }

    $paired = Join-Path $root 'pico\build\qtimer-p2-private-20261016-204644'
    $csv = Join-Path $paired 'k0.csv'
    if (-not (Test-Path -LiteralPath $csv -PathType Leaf)) { throw "Missing $csv" }
    python -m pico.tools.audit_k0_slot130_variation --csv $csv --output (Join-Path $paired 'slot130-variation.json')
    if ($LASTEXITCODE -ne 0) { throw 'Slot130 variation analysis failed' }

    if (-not $EvidenceDir) {
        $found = Get-ChildItem -LiteralPath (Join-Path $root 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $found) { throw 'No private native ELF evidence found' }
        $EvidenceDir = $found.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $camera = Join-Path $dir 'libpvrtrackingcamera.so'
    $service = Join-Path $dir 'libpvrtrackingservice.so'
    foreach ($v in @(
        @{ Path=$camera; SHA='cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee' },
        @{ Path=$service; SHA='45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de' }
    )) {
        if (-not (Test-Path -LiteralPath $v.Path -PathType Leaf)) { throw "Missing $($v.Path)" }
        if ((Get-FileHash -LiteralPath $v.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $v.SHA) { throw "Wrong ELF hash: $($v.Path)" }
    }
    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $toolBin = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin'
    $dump = Join-Path $toolBin 'llvm-objdump.exe'
    $read = Join-Path $toolBin 'llvm-readelf.exe'
    if (-not (Test-Path $dump) -or -not (Test-Path $read)) { throw 'LLVM binutils missing' }

    function Get-Disassembly([string] $elf, [string] $first, [string] $last, [string] $label) {
        $out = @(& $dump '-d' '--demangle' '--no-show-raw-insn' "--start-address=$first" "--stop-address=$last" $elf)
        if ($LASTEXITCODE -ne 0 -or $out.Count -lt 7) { throw "Disassembly failed: $label" }
        $out | Set-Content -LiteralPath (Join-Path $dir "$label.txt") -Encoding utf8
        return $out
    }
    Write-Host '=== Native slot130 computation ==='
    $equation = @(Get-Disassembly $service '0xaae7c' '0xaaeb8' 'p2-native-slot130-computation')
    $equation | Select-Object -Skip 3

    Write-Host '=== CameraManager collectCameraInfo relevant calls and fields ==='
    $collector = @(Get-Disassembly $service '0xab15c' '0xab634' 'p2-collectCameraInfo')
    $hits = @($collector | Select-String -Pattern '\bbl\b|#0x14\]|#0x330\]|#0x338\]|#0x2d0\]|#0x2d8\]' | ForEach-Object { $_.Line })
    $hits | Select-Object -First 40
    Write-Host ("Collector matched {0} instructions" -f $hits.Count)

    Write-Host '=== QuickCamera listener registration ==='
    $registration = @(Get-Disassembly $camera '0x65004' '0x6507c' 'p2-quickcamera-set-listener')
    $registration | Select-Object -Skip 3

    Write-Host '=== CameraImageListener vtable relocations (candidate addresses) ==='
    $rels = @(& $read '--relocations' '--wide' $service)
    if ($LASTEXITCODE -ne 0) { throw 'Service relocation inspection failed' }
    $rels | Set-Content -LiteralPath (Join-Path $dir 'p2-service-elf-relocations.txt') -Encoding utf8
    $foundRels = @($rels | Select-String -Pattern '000000000015e69|000000000015e6a|000000000015e6b' | ForEach-Object { $_.Line })
    if ($foundRels.Count) { $foundRels | Select-Object -First 24 } else { Write-Host 'No direct relocation listing for vtable; check packed relocations.' }

    Write-Host "Private distribution: $(Join-Path $paired 'slot130-variation.json')"
    Write-Host "Private ELF traces: $dir"
    Write-Host 'OBSERVE ONLY; no changes to device or SteamVR.'
}
finally { Pop-Location }
