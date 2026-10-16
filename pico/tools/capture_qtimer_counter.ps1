# Pico P2: READ-ONLY hardware CNTVCT clock vs PVR QTIMER diagnostics.
# Does not open a camera, mutate tracking services, or alter any driver.
[CmdletBinding()]
param([string] $Serial = '192.168.23.12:5555')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python .\pico\build_module.py --qtimer-counter-only
    if ($LASTEXITCODE -ne 0) { throw 'Standalone NDK qtimer probe build failed' }

    $bin = '/data/local/tmp/pico_qtimer_counter_probe'
    adb -s $Serial push .\pico\build\pico_qtimer_counter_probe $bin
    if ($LASTEXITCODE -ne 0) { throw 'ADB push failed' }
    adb -s $Serial shell su -c "chmod 700 $bin"
    if ($LASTEXITCODE -ne 0) { throw 'Unable to grant executable permissions' }

    function Read-PvrClocks {
        $raw = @(adb -s $Serial shell su -c 'dumpsys -t 10 pvrtracking')
        if ($LASTEXITCODE -ne 0) { throw 'PVR dumpsys failed' }
        $line = $raw |
            Select-String -Pattern '^time boottime\s+\d+,\s*monotime\s+\d+,\s*qtimer\s+\d+' |
            Select-Object -First 1
        if (-not $line) { throw 'PVR clock line missing' }
        return $line.Line
    }

    Write-Host '--- PVR BEFORE (same device clock) ---'
    Read-PvrClocks
    Write-Host '--- HARDWARE COUNTER vs POSIX CLOCKS (8 samples) ---'
    adb -s $Serial shell su -c $bin
    if ($LASTEXITCODE -ne 0) { throw 'Hardware counter probe failed' }
    Write-Host '--- PVR AFTER (same device clock) ---'
    Read-PvrClocks
    Write-Host 'OBSERVE ONLY: hardware counter origin not yet tied to camera exposure.'
}
finally {
    Pop-Location
}
