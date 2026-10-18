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
    schema='p3a4.offline.bridge.v3'
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
# Only exact SHA-pinned PVR helper symbols can enter this evidence set.
# The earlier "first four QuickCameraClient hits" sampled unrelated functions.
# Resolve full function extent using the ELF dynamic symbol table rather
# than guessing end addresses. Fail closed if the expected ABI differs.
$pvrTargets = @(
    @{ Name='09-pvr-DeQueue-native-pointer-and-frame'; Pattern='QuickCameraClient::DeQueueFrame\(native_handle\*\*, void\*\*,' },
    @{ Name='10-pvr-DeQueue-native-pointer'; Pattern='QuickCameraClient::DeQueueFrame\(native_handle\*\*, pico::' },
    @{ Name='11-pvr-DeQueue-void-pointer'; Pattern='QuickCameraClient::DeQueueFrame\(void\*\*, pico::' },
    @{ Name='12-pvr-ConfigAndAllocBuffers'; Pattern='QuickCameraClient::ConfigAndAllocBuffers\(' },
    @{ Name='13-pvr-PrepareStreamOn'; Pattern='QuickCameraClient::PrepareStreamOn\(' },
    @{ Name='14-pvr-Constructor'; Pattern='QuickCameraClient::QuickCameraClient\(' },
    @{ Name='15-pvr-OnBufferReady'; Pattern='PvrCameraDeviceCallback::OnBufferReady\(' }
)
$metadata['pvr_exact_targets'] = @()
foreach ($target in $pvrTargets) {
    $hits = @($metadata.symbol_hits['pvr'] | Where-Object { $_ -match $target.Pattern } | Select-Object -Unique)
    if ($hits.Count -ne 1) { throw "PVR exact symbol resolution failed for $($target.Name); hits=$($hits.Count)" }
    $parsed = [regex]::Match($hits[0], '^\s*([0-9a-fA-F]{8,16})\s+g\s+DF\s+\.text\s+([0-9a-fA-F]{8,16})\s')
    if (-not $parsed.Success) { throw "PVR .text symbol location invalid for $($target.Name)" }
    $start = [Convert]::ToInt64($parsed.Groups[1].Value, 16)
    $size = [Convert]::ToInt64($parsed.Groups[2].Value, 16)
    if ($start -le 0 -or $size -le 0 -or $size -gt 0x1200) {
        throw "PVR symbol size/address unsafe for $($target.Name)"
    }
    $windows += @{ Name=$target.Name; Bin='pvr'; From=$start; To=($start+$size) }
    $metadata['pvr_exact_targets'] += @{
        name=$target.Name; symbol=$hits[0]; address=$start; size=$size
    }
}
# P3-A4D: inspect relocation entries for the native HIDL callback functor
# vtable, constructed in QuickCameraClient::ConfigAndAllocBuffers.
$readelf = Join-Path (Split-Path -Parent $objdump) 'llvm-readelf.exe'
if (-not (Test-Path -LiteralPath $readelf)) { throw 'llvm-readelf.exe missing from same NDK' }
$relocs = @(& $readelf '--relocs' $pvr)
if ($LASTEXITCODE -ne 0) { throw 'PVR ELF relocation extraction failed' }
$metadata['callback_relocations'] = @()
$metadata['callback_candidates'] = @()
$metadata['callback_vtable_identity_verified'] = $false
$metadata['shared_buffer_identity_verified'] = $false
$callbackTargets = [System.Collections.Generic.HashSet[long]]::new()

foreach ($line in $relocs) {
    $m = [regex]::Match($line, '^\s*([0-9a-fA-F]{8,16})\s+[0-9a-fA-F]+\s+(R_AARCH64_\S+)\s+(.*)$')
    if (-not $m.Success) { continue }
    $slot = [Convert]::ToInt64($m.Groups[1].Value, 16)
    if ($slot -lt 0x752b0 -or $slot -ge 0x75330) { continue }
    $kind = $m.Groups[2].Value
    $metadata['callback_relocations'] += @{
        slot = ('0x{0:x}' -f $slot)
        type = $kind
        text = $line.Trim()
    }
    if ($kind -ne 'R_AARCH64_RELATIVE') { continue }
    # Example RELA addend: 0000000000061234 (literal hex).
    $tail = $m.Groups[3].Value.Trim()
    $candidateMatch = [regex]::Match($tail, '^(?:0x)?([0-9a-fA-F]{4,16})(?:\s|$)')
    if (-not $candidateMatch.Success) { continue }
    $candidate = [Convert]::ToInt64($candidateMatch.Groups[1].Value, 16)
    if ($candidate -ge 0x30000 -and $candidate -lt 0x74000 -and (($candidate % 4) -eq 0)) {
        [void]$callbackTargets.Add($candidate)
    }
}
$metadata['callback_vtable_relocation_seen'] = @($metadata['callback_relocations']).Count -gt 0
foreach ($target in @($callbackTargets | Sort-Object | Select-Object -First 8)) {
    $n = @($metadata['callback_candidates']).Count
    $metadata['callback_candidates'] += ('0x{0:x}' -f $target)
    $windows += @{
        Name = ('16-pvr-hidl-callback-candidate-' + $n)
        Bin = 'pvr'
        From = $target
        To = ($target + 0x600)
    }
}
# Presence of a candidate is NOT evidence of shared-buffer identity.
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
