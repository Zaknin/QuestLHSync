#requires -Version 7.0
<#
PICO 4 Pro / QuestLHSync targeted Lighthouse on/off study (manual Enter).
Two distinct viewpoints for channel 1, and one verification for channel 10.
Human-operated power controls; no automatic power switching or driver changes.
Each switch and RETURN TO IDENTICAL VIEWING POSE gets its own QPC timestamp.
#>
[CmdletBinding()]
param(
    [ValidateRange(8,60)][int]$HoldSeconds = 15,
    [ValidateRange(15,90)][int]$SpinupSeconds = 25,
    [string]$RecordingPath = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$plan = @(
    [pscustomobject]@{Channel=1;Serial='LHB-6E23CDDC';Room='FarRight-Top / дальняя справа, наверху';View='A: напротив базы, метка на полу'},
    [pscustomobject]@{Channel=1;Serial='LHB-6E23CDDC';Room='FarRight-Top / дальняя справа, наверху';View='B: на 0.5-1 м в сторону, новая метка'},
    [pscustomobject]@{Channel=10;Serial='LHB-60A737E1';Room='FrontRight-Mid / спереди справа, средняя высота';View='C: точка с прямой видимостью'}
)
$dir = Join-Path $env:LOCALAPPDATA 'QuestLHSync\recordings'
if (!(Test-Path -LiteralPath $dir -PathType Container)) {
    throw 'No QuestLHSync recordings folder. Start PICO Connect + SteamVR first, then click Record session.'
}
if ($RecordingPath) {
    $rec = Get-Item -LiteralPath $RecordingPath -ErrorAction Stop
} else {
    $rec = Get-ChildItem -LiteralPath $dir -File -Filter 'qlhs-*.txt' |
        Sort-Object CreationTime -Descending | Select-Object -First 1
}
if (!$rec -or $rec.Extension -ne '.txt') {
    throw 'No valid qlhs-*.txt recording. Press Record session before running this script.'
}
if ($rec.CreationTime -lt (Get-Date).AddMinutes(-15)) {
    throw "Latest recording is older than 15 min ($($rec.CreationTime)); start a NEW recording first."
}
$markerPath = Join-Path $dir ("{0}-targeted-switches-{1}.csv" -f $rec.BaseName,(Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:seq = 0
function Mark {
    param([string]$Action,[int]$Channel,[string]$Serial,[string]$View)
    # Stopwatch and the QuestLHSync driver both use Windows QPC.
    $tick=[System.Diagnostics.Stopwatch]::GetTimestamp()
    $stamp=[long][math]::Round(([double]$tick/[double][System.Diagnostics.Stopwatch]::Frequency)*1e9)
    $script:seq++
    [pscustomobject]@{
        Seq=$script:seq;Action=$Action;Channel=$Channel;Serial=$Serial;
        View=$View;QpcNs=$stamp;Utc=[DateTimeOffset]::UtcNow.ToString('O')
    } | Export-Csv -LiteralPath $markerPath -Append -NoTypeInformation -Encoding utf8
    Write-Host ("  [{0}] {1} channel {2} QPC={3}" -f $script:seq,$Action,$Channel,$stamp) -ForegroundColor Cyan
}
function Step {
    param([string]$Prompt,[string]$Action,[object]$Station)
    [void](Read-Host $Prompt)
    Mark -Action $Action -Channel $Station.Channel -Serial $Station.Serial -View $Station.View
}
Write-Host ''
Write-Host 'PICO 4 Pro / TARGETED Lighthouse identification' -ForegroundColor Green
Write-Host "Recording: $($rec.FullName)"
Write-Host "Markers:   $markerPath"
Write-Host 'All four stations ON at start; keep one continuous QuestLHSync Record session.'
Write-Host 'The headset must stay TRACKED and AWAKE. Do not put it down if that suspends SLAM.'
Write-Host 'Only switch the specified station; leave the other three ON.'
Write-Host 'ENTER after power changes AND after returning to the same marked viewing pose.'
Write-Host 'Try to keep the head orientation steady during each timed hold.'
[void](Read-Host 'When recording has started and all four stations are ON, press ENTER')
Mark -Action 'ALL_ON_START' -Channel 0 -Serial '' -View ''

for ($i=0; $i -lt $plan.Count; $i++) {
    $st=$plan[$i]
    Write-Host ''
    Write-Host ("PASS {0}/{1}: channel {2} ({3})" -f ($i+1),$plan.Count,$st.Channel,$st.Serial) -ForegroundColor Yellow
    Write-Host "PLACE: $($st.Room)"
    Write-Host "VIEW:  $($st.View)"
    Write-Host 'Choose an unobstructed viewpoint; mark feet and viewing direction.'
    Step -Prompt 'At YOUR viewing point, all bases ON? ENTER' -Action 'BASELINE_READY' -Station $st
    Write-Host "Stay steady for $HoldSeconds seconds (baseline ON) ..."
    Start-Sleep -Seconds $HoldSeconds

    Write-Host "Physically switch OFF ONLY channel $($st.Channel)" -ForegroundColor Yellow
    Step -Prompt 'Power OFF done? IMMEDIATELY ENTER' -Action 'OFF' -Station $st
    Step -Prompt 'BACK at the same viewing pose? ENTER' -Action 'OFF_READY' -Station $st
    Write-Host "Stay steady for $HoldSeconds seconds (OFF) ..."
    Start-Sleep -Seconds $HoldSeconds

    Write-Host "Physically switch channel $($st.Channel) ON again" -ForegroundColor Yellow
    Step -Prompt 'Power ON done? IMMEDIATELY ENTER' -Action 'ON' -Station $st
    Step -Prompt 'BACK at the same viewing pose? ENTER' -Action 'ON_READY' -Station $st
    Write-Host "Wait $SpinupSeconds seconds in the same pose (spinup) ..."
    Start-Sleep -Seconds $SpinupSeconds
    Write-Host "Stay steady for $HoldSeconds more seconds (stable ON) ..."
    Start-Sleep -Seconds $HoldSeconds
    Mark -Action 'PASS_DONE' -Channel $st.Channel -Serial $st.Serial -View $st.View
}
Mark -Action 'ALL_ON_END' -Channel 0 -Serial '' -View ''
Write-Host ''
Write-Host 'FINISHED. Confirm all four stations ON.' -ForegroundColor Green
Write-Host 'Click Record session again to STOP and save the QuestLHSync session.'
[void](Read-Host 'After STOPPING the recording, press ENTER')
Write-Host "TXT: $($rec.FullName)"
Write-Host "CSV: $markerPath"
Write-Host 'Send the two files; private factory calibration does not need sending again.'
