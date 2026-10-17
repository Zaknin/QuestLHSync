# P3-A4 private offline bridge trace. Reads locally pinned ELF files; NO ADB.
[CmdletBinding()]
param([string] $OutputRoot = '\\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$build = Join-Path $repo 'pico\build'
function Find-Pinned([string] $pattern, [string] $hash) {
    $found = @(Get-ChildItem -Path (Join-Path $build $pattern) -File -ErrorAction SilentlyContinue |
        Where-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $hash } |
        Sort-Object FullName -Descending)
    if (-not $found) { throw "No SHA-pinned private ELF for $pattern; STOP" }
    return $found[0].FullName
}
$pvr = Find-Pinned 'p2-static-clock-private-*\libpvrtrackingcamera.so' 'cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee'
$core = Find-Pinned 'p3a-producers-*-private\vendor\lib64\quickcamera.core.so' 'fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017'
$hidl = Find-Pinned 'p3a-producers-*-private\vendor\lib64\hw\pico.camera.quickcamera.quickcameramodule@1.0-impl.so' 'c3157e66d842dcdca148f1b98328bd5e7ce80c4ab9bbbacba895465556314f47'
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$tools = @(Get-ChildItem -Path (Join-Path $sdk 'ndk\*\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe') -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
if (-not $tools) { throw 'LLVM objdump NDK not found' }
$objdump = $tools[0].FullName
$run = 'p3a4-bridge-' + (Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$private = Join-Path $build ($run + '-private')
New-Item -ItemType Directory -Path $private -ErrorAction Stop | Out-Null
$bins = @{ pvr=$pvr; core=$core; hidl=$hidl }
$windows = @(
    @{ Name='01-pvr-FrameMetaDate-consumer'; Bin='pvr'; From=0x664d0; To=0x66740 },
    @{ Name='02-core-CSL-timestamp-message'; Bin='core'; From=0x375d0; To=0x376a0 },
    @{ Name='03-core-CSL-fence-write'; Bin='core'; From=0x38670; To=0x38850 },
    @{ Name='04-core-CSL-fallback'; Bin='core'; From=0x38bc0; To=0x38c50 },
    @{ Name='05-core-buffer-allocation'; Bin='core'; From=0x36860; To=0x36b70 },
    @{ Name='06-hidl-buffer-info'; Bin='hidl'; From=0x9494; To=0x96a0 },
    @{ Name='07-hidl-buffer-ready'; Bin='hidl'; From=0x98e4; To=0x9990 },
    @{ Name='08-hidl-configuration'; Bin='hidl'; From=0xa59c; To=0xa6a0 }
)
$metadata = [ordered]@{
    schema='p3a4.offline.bridge.v1'
    status='TRACE_CAPTURED_NOT_PROVEN'
    observe_only=$true
    exact_time=$false
    live_lighthouse_correction_allowed=$false
    mapping_verified=$false
    pose_verified=$false
    frame_meta_bridge_verified=$false
    physical_event_verified=$false
    binaries_copied_into_evidence=$false
    input_sha256=@{}
    symbol_hits=@{}
    windows=@()
}
foreach ($kind in @('pvr','core','hidl')) {
    $path = $bins[$kind]
    $metadata.input_sha256[$kind] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $syms = @(& $objdump '--dynamic-syms' '--demangle' $path)
    if ($LASTEXITCODE -ne 0) { throw "Symbol extraction failed for $kind" }
    $hits = @($syms | Select-String -Pattern 'QuickCameraClient|DeQueueFrame|FrameMetaDate|QuickCameraBufInfo|OnBufferReady|CamQuickAccessDevice|mapMemory|mmap' |
        Select-Object -First 120 | ForEach-Object { $_.Line })
    $metadata.symbol_hits[$kind] = @($hits)
}
# When the PVR ELF exports a real DeQueueFrame symbol, trace a narrow window there.
foreach ($line in $metadata.symbol_hits['pvr']) {
    if ($line -match 'QuickCameraClient|DeQueueFrame') {
        if ($line -match '^\s*([0-9a-fA-F]{8,16})\s') {
            $start = [Convert]::ToInt64($Matches[1],16)
            if ($start -gt 0 -and $start -lt 0x2000000) {
                $duplicate = @($windows | Where-Object { $_.From -eq $start })
                if (-not $duplicate) {
                    $n = @($windows | Where-Object { $_.Name -like '09-*' }).Count
                    if ($n -ge 4) { break }
                    $windows += @{ Name=('09-pvr-symbol-' + $n); Bin='pvr'; From=$start; To=($start+0x500) }
                }
            }
        }
    }
}
foreach ($w in $windows) {
    if ($w.To -le $w.From -or ($w.To-$w.From) -gt 0x1200) { throw 'Invalid bounded disassembly region' }
    $out = @(& $objdump '-d' '--demangle' '--no-show-raw-insn' ("--start-address=0x{0:x}" -f $w.From) ("--stop-address=0x{0:x}" -f $w.To) $bins[$w.Bin])
    if ($LASTEXITCODE -ne 0 -or $out.Count -lt 7) { throw "Disassembly failed: $($w.Name)" }
    $dest = Join-Path $private ($w.Name + '.txt')
    $out | Set-Content -LiteralPath $dest -Encoding utf8
    $metadata.windows += @{ name=$w.Name; input=$w.Bin; start=$w.From; end=$w.To }
}
$manifest = Join-Path $private 'manifest.json'
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifest -Encoding utf8
$archive = Join-Path $private ($run + '.zip')
$contents = @(Get-ChildItem -LiteralPath $private -File -Filter '*.txt') + @(Get-Item -LiteralPath $manifest)
Compress-Archive -LiteralPath @($contents.FullName) -DestinationPath $archive -CompressionLevel Optimal
# Publish only disassembly excerpts and metadata, never proprietary ELF bytes.
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$files = @(
    @{ Local=$archive; Name=($run + '.zip') },
    @{ Local=$manifest; Name=($run + '.json') }
)
$lines = @()
foreach ($f in $files) {
    $expected = (Get-FileHash -LiteralPath $f.Local -Algorithm SHA256).Hash.ToLowerInvariant()
    $part = Join-Path $OutputRoot ($f.Name + '.part')
    $final = Join-Path $OutputRoot $f.Name
    Copy-Item -LiteralPath $f.Local -Destination $part -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'SMB .part integrity failed' }
    Move-Item -LiteralPath $part -Destination $final -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $final -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'SMB final integrity failed' }
    $lines += "$expected  $($f.Name)"
}
$markerPart = Join-Path $OutputRoot ($run + '.sha256.part')
$marker = Join-Path $OutputRoot ($run + '.sha256')
$lines | Set-Content -LiteralPath $markerPart -Encoding ascii
$before = (Get-FileHash -LiteralPath $markerPart -Algorithm SHA256).Hash
Move-Item -LiteralPath $markerPart -Destination $marker -ErrorAction Stop
if ((Get-FileHash -LiteralPath $marker -Algorithm SHA256).Hash -ne $before) { throw 'Final marker verification failed' }
[ordered]@{ status='TRACE_CAPTURED_NOT_PROVEN'; zip=(Join-Path $OutputRoot ($run + '.zip')); manifest=(Join-Path $OutputRoot ($run + '.json')); marker=$marker; windows=$windows.Count; pvr_symbol_hits=@($metadata.symbol_hits['pvr']).Count } | ConvertTo-Json -Compress
