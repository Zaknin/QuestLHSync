#requires -Version 7.0
<#
Pico 4 Pro P2: mark manual Lighthouse power changes with ENTER.
Start QuestLHSync's "Record session" BEFORE launching this script.
Each ENTER means the requested physical power action has ALREADY been performed.
All timestamps are Windows QPC nanoseconds (Stopwatch/QueryPerformanceCounter),
same timebase as the first column of QuestLHSync's qlhs-*.txt recording.
This does not control Lighthouse power, SteamVR, Pico or the live solver.
#>
[CmdletBinding()]
param(
    [ValidateRange(5, 120)][int]$BeforeOffSeconds = 12,
    [ValidateRange(10, 120)][int]$OffSeconds = 25,
    [ValidateRange(10, 120)][int]$AfterOnSeconds = 30,
    [string]$RecordingPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Room labels verified physically by the user on 2026-10-15, following the
# marked four-base power-toggle recording. Four positions are confirmed.
$stations = @(
    [pscustomobject]@{ Channel = 13; Serial = 'LHB-2BB29CAB'; Room = 'FrontLeft-Low / спереди слева, низко'; Confidence = 'CONFIRMED' }
    [pscustomobject]@{ Channel = 10; Serial = 'LHB-60A737E1'; Room = 'FrontRight-Mid / спереди справа, средняя высота'; Confidence = 'CONFIRMED' }
    [pscustomobject]@{ Channel = 1;  Serial = 'LHB-6E23CDDC'; Room = 'FarRight-Top / дальняя справа, наверху'; Confidence = 'CONFIRMED' }
    [pscustomobject]@{ Channel = 7;  Serial = 'LHB-22CEE79A'; Room = 'Rear / сзади'; Confidence = 'CONFIRMED' }
)

$dir = Join-Path $env:LOCALAPPDATA 'QuestLHSync\recordings'
if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
    throw 'Recordings folder missing: first start SteamVR, QuestLHSync and click Record session.'
}
if ($RecordingPath) {
    $rec = Get-Item -LiteralPath $RecordingPath -ErrorAction Stop
    if ($rec.Extension -ne '.txt') { throw 'Recording must be a qlhs-*.txt file.' }
} else {
    $rec = Get-ChildItem -LiteralPath $dir -File -Filter 'qlhs-*.txt' |
        Sort-Object CreationTime -Descending |
        Select-Object -First 1
}
if ($null -eq $rec) {
    throw 'No qlhs recording found. Click Record session in QuestLHSync.'
}
if ($rec.CreationTime -lt (Get-Date).AddMinutes(-15)) {
    throw ("Newest recording is old ({0}). Start a NEW Record session first." -f $rec.CreationTime)
}
if ($rec.Length -eq 0) {
    Write-Warning 'Recording is 0 bytes so far; buffered output may not be flushed until stopping.'
}

$markerPath = Join-Path $dir ("{0}-switches-{1}.csv" -f $rec.BaseName, (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:seq = 0

function Add-Marker {
    param(
        [Parameter(Mandatory)][string]$Action,
        [int]$Channel = 0,
        [string]$Serial = ''
    )
    # .NET Stopwatch on Windows uses QueryPerformanceCounter, also used by QpcNow().
    $tick = [System.Diagnostics.Stopwatch]::GetTimestamp()
    $freq = [System.Diagnostics.Stopwatch]::Frequency
    $stampNs = [long][math]::Round(([double]$tick / [double]$freq) * 1e9)
    $utc = [DateTimeOffset]::UtcNow.ToString('O')
    $script:seq++
    $row = [pscustomobject]@{
        Seq      = $script:seq
        Action   = $Action
        Channel  = $Channel
        Serial   = $Serial
        QpcNs    = $stampNs
        Utc      = $utc
    }
    $row | Export-Csv -LiteralPath $markerPath -Append -NoTypeInformation -Encoding utf8
    Write-Host ("  MARK {0,-12} ch={1,-2} QPC={2}" -f $Action, $Channel, $stampNs) -ForegroundColor Cyan
}

Write-Host ''
Write-Host 'PICO P2 / Lighthouse switch-marker session' -ForegroundColor Green
Write-Host "QuestLHSync recording: $($rec.FullName)"
Write-Host "Switch markers CSV:    $markerPath"
Write-Host ''
Write-Host 'IMPORTANT: All four stations must be ON now.'
Write-Host 'Keep Pico worn, awake and tracking. Leave QuestLHSync recording continuously.'
Write-Host 'Perform each requested OFF or ON action FIRST, then immediately press ENTER.'
Write-Host 'The marker measures ENTER time; it cannot confirm when the laser actually stopped/started.'
[void](Read-Host 'After clicking Record session and confirming four stations ON, press ENTER')
Add-Marker -Action 'ALL_ON_START'

foreach ($station in $stations) {
    $channel = $station.Channel
    $serial = $station.Serial
    $room = $station.Room
    Write-Host ''
    Write-Host ("STATION CHANNEL {0}: {1}" -f $channel, $serial) -ForegroundColor Yellow
    Write-Host ("  PLACE: {0} [{1}]" -f $room, $station.Confidence) -ForegroundColor Yellow
    if ($station.Confidence -ne 'CONFIRMED') {
        Write-Warning 'The serial-to-room assignment is not fully verified. Do not guess if unsure which base station this is.'
    }
    Write-Host ("Face this station and keep the headset tracking. All four are ON: observe for {0} s." -f $BeforeOffSeconds)
    Start-Sleep -Seconds $BeforeOffSeconds

    Write-Host ("Now turn OFF ONLY channel {0} ({1}, {2})." -f $channel, $serial, $room) -ForegroundColor Yellow
    [void](Read-Host 'After switching it OFF, immediately press ENTER')
    Add-Marker -Action 'OFF' -Channel $channel -Serial $serial
    Write-Host ("Wait {0} s while this station stays OFF..." -f $OffSeconds)
    Start-Sleep -Seconds $OffSeconds

    Write-Host ("Now turn ON channel {0} ({1}, {2}) again." -f $channel, $serial, $room) -ForegroundColor Yellow
    [void](Read-Host 'After switching it ON, immediately press ENTER')
    Add-Marker -Action 'ON' -Channel $channel -Serial $serial
    Write-Host ("Wait {0} s for full spin-up (all four ON)..." -f $AfterOnSeconds)
    Start-Sleep -Seconds $AfterOnSeconds
}
Add-Marker -Action 'ALL_ON_END'
Write-Host ''
Write-Host 'All 4 cycles done. Ensure all four Lighthouse stations are now ON.' -ForegroundColor Green
Write-Host 'STOP the recording with Record session in the QuestLHSync dashboard.'
[void](Read-Host 'After stopping the QuestLHSync recording, press ENTER')
Write-Host ''
Write-Host "Recording: $($rec.FullName)"
Write-Host "Markers:   $markerPath"
Write-Host 'Send both files together. They share the same monotonic QPC clock.'
