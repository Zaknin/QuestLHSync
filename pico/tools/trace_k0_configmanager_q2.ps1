# P2 offline: trace ConfigManager and CameraManager literal ownership.
# Saved SHA-pinned private ELF only. No ADB, camera, or SteamVR.
[CmdletBinding()]
param([string]$EvidenceDir = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python -m unittest pico.tests.test_k0_literal_references pico.tests.test_k0_alternate_constants -v
    if ($LASTEXITCODE -ne 0) { throw 'Existing offline ELF tests failed' }

    if (-not $EvidenceDir) {
        $found = Get-ChildItem -LiteralPath (Join-Path $repo 'pico\build') -Directory -Filter 'p2-static-clock-private-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $found) { throw 'Private ELF folder not found' }
        $EvidenceDir = $found.FullName
    }
    $dir = (Resolve-Path $EvidenceDir).Path
    $svc = Join-Path $dir 'libpvrtrackingservice.so'
    $expected = '45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de'
    if (-not (Test-Path -LiteralPath $svc -PathType Leaf)) { throw "Missing ELF $svc" }
    if ((Get-FileHash -LiteralPath $svc -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'PVR ELF SHA256 does not match pinned firmware'
    }
    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) {
        $env:ANDROID_SDK_ROOT
    } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $objdump = Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe'
    if (-not (Test-Path -LiteralPath $objdump -PathType Leaf)) { throw "Missing LLVM objdump: $objdump" }

    $windows = @(
        @{ Name='01-ConfigManager-getInstance-q2'; First='0xa2420'; Last='0xa2510' },
        @{ Name='02-ConfigManager-ctor-q2'; First='0xa2550'; Last='0xa2660' },
        @{ Name='03-CameraManager-ctor-load'; First='0xa7174'; Last='0xa71a8' },
        @{ Name='04-CameraManager-ctor-store'; First='0xa72c4'; Last='0xa7304' }
    )
    foreach ($win in $windows) {
        $args = @('-d','--demangle','--no-show-raw-insn',"--start-address=$($win.First)","--stop-address=$($win.Last)",$svc)
        $lines = @(& $objdump @args)
        if ($LASTEXITCODE -ne 0 -or $lines.Count -lt 8) { throw "Disassembly failed: $($win.Name)" }
        $lines | Set-Content -LiteralPath (Join-Path $dir ($win.Name+'.txt')) -Encoding utf8
        Write-Host "=== $($win.Name) ==="
        $lines | Select-Object -Skip 3 -First 75
    }

    Write-Host '=== ConfigManager and time-related ELF symbols ==='
    $sym = @(& $objdump '--syms' '--demangle' $svc)
    if ($LASTEXITCODE -ne 0) { throw 'ELF symbols read failed' }
    $hits = @($sym | Select-String -Pattern 'pvr::ConfigManager::|pvr::CameraManager::|exposure|Exposure|Timestamp|timestamp' | ForEach-Object { $_.Line })
    $hits | Set-Content -LiteralPath (Join-Path $dir '05-configmanager-camera-symbols.txt') -Encoding utf8
    $hits | Where-Object { $_ -match 'ConfigManager::|exposure|Exposure|Timestamp|timestamp' } | Select-Object -First 50 | ForEach-Object {
        if ($_.Length -gt 220) { Write-Host ($_.Substring(0,220)) } else { Write-Host $_ }
    }
    Write-Host "Saved $($hits.Count) matching ELF symbol lines privately."
    Write-Host 'Do NOT infer ConfigManager coefficients are used by active K0 without setter/assignment proof.'
    Write-Host "Private traces: $dir"
    Write-Host 'OBSERVE ONLY; exact_time=false; no tracking change.'
}
finally { Pop-Location }
