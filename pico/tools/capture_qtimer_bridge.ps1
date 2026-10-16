# Pico P2 / QTIMER hypothesis capture. READ-ONLY on-device.
# Builds a diagnostics-only Java reader, captures PVR clock snapshots
# surrounding K0 clock metadata scan. No camera open/SLAM/driver changes.
[CmdletBinding()]
param(
    [string] $Serial = '192.168.23.12:5555',
    [ValidateRange(5, 60)][int] $Seconds = 12
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    python -m unittest pico.tests.test_qtimer_bridge -v
    if ($LASTEXITCODE -ne 0) { throw 'Offline regression tests failed' }

    python .\pico\build_module.py --reader-only
    if ($LASTEXITCODE -ne 0) { throw 'Reader-only build failed' }

    $remoteJar = '/data/local/tmp/PicoFrameReader.jar'
    adb -s $Serial push .\pico\build\PicoFrameReader.jar $remoteJar
    if ($LASTEXITCODE -ne 0) { throw 'ADB push failed' }

    $evidenceDir = Join-Path $repo ('pico\build\qtimer-p2-private-' +
        (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

    function Read-PvrClock {
        $raw = @(& adb -s $Serial shell su -c 'dumpsys -t 10 pvrtracking')
        if ($LASTEXITCODE -ne 0) { throw 'PVR dumpsys failed' }
        $line = $raw |
            Select-String -Pattern '^time boottime\s+\d+,\s*monotime\s+\d+,\s*qtimer\s+\d+' |
            Select-Object -First 1
        if (-not $line) { throw 'PVR clock line unavailable' }
        return $line.Line
    }

    Read-PvrClock | Set-Content -Encoding utf8 (Join-Path $evidenceDir 'before.txt')

    $scan = @(& adb -s $Serial shell su -c (
        "CLASSPATH=$remoteJar /system/bin/app_process /system/bin PicoFrameReader --clock-scan $Seconds"))
    if ($LASTEXITCODE -ne 0) { throw 'Pico K0 scan failed; capture incomplete' }
    if ($scan.Count -lt 100 -or $scan[0] -notmatch '^sample,cam,seq,') {
        throw 'K0 scan did not return a valid CSV header/record count'
    }
    $scan | Set-Content -Encoding utf8 (Join-Path $evidenceDir 'k0.csv')
    Read-PvrClock | Set-Content -Encoding utf8 (Join-Path $evidenceDir 'after.txt')

    python .\pico\tools\audit_qtimer_bridge.py `
        --before (Join-Path $evidenceDir 'before.txt') `
        --csv (Join-Path $evidenceDir 'k0.csv') `
        --after (Join-Path $evidenceDir 'after.txt') `
        --output (Join-Path $evidenceDir 'audit.json')
    if ($LASTEXITCODE -ne 0) { throw 'Offline QTIMER audit failed' }
    Write-Host "Private diagnostic files: $evidenceDir"
    Write-Host 'OBSERVE ONLY: no timestamp or tracking corrections were applied.'
}
finally {
    Pop-Location
}
