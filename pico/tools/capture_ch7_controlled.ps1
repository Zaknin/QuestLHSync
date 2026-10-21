#requires -Version 7.0
<#
P3-K guided single-channel Lighthouse capture. This script records local QPC
markers only. It never changes station power, tracking, SteamVR, or the device.
#>
[CmdletBinding()]
param(
    [string]$RecordingPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$recordingDir = Join-Path $env:LOCALAPPDATA 'QuestLHSync\recordings'
if (-not (Test-Path -LiteralPath $recordingDir -PathType Container)) {
    throw 'QuestLHSync recordings directory is missing. Start a Record session first.'
}

$recordingRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $recordingDir).Path)
if ($RecordingPath) {
    $recordingItem = Get-Item -LiteralPath $RecordingPath -ErrorAction Stop
} else {
    $recordingItem = Get-ChildItem -LiteralPath $recordingRoot -File -Filter 'qlhs-*.txt' |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
}
if ($null -eq $recordingItem -or $recordingItem.PSIsContainer) {
    throw 'No QuestLHSync qlhs-*.txt recording was found.'
}
$recordingFullPath = [System.IO.Path]::GetFullPath($recordingItem.FullName)
$relativePath = [System.IO.Path]::GetRelativePath($recordingRoot, $recordingFullPath)
if ($relativePath -eq '..' -or $relativePath.StartsWith("..$([System.IO.Path]::DirectorySeparatorChar)") -or
    $recordingItem.Name -notlike 'qlhs-*.txt' -or
    ($recordingItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
    throw 'Recording must be a regular qlhs-*.txt file inside the QuestLHSync recordings directory.'
}

$markerPath = Join-Path $recordingRoot ("{0}-ch7-markers-{1}.csv" -f $recordingItem.BaseName, (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $markerPath) {
    throw 'Marker output already exists; wait for a new filename or move the existing local result.'
}
$script:markerSequence = 0
$script:lastLength = [long]$recordingItem.Length
$script:lastGrowthUtc = [DateTime]::UtcNow
$script:recordingPathResolved = $recordingFullPath

function Get-P3KRecordingItem {
    $item = Get-Item -LiteralPath $script:recordingPathResolved -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw 'Recording path changed or is no longer a regular file.'
    }
    return $item
}

function Assert-P3KRecordingActive {
    $item = Get-P3KRecordingItem
    $age = [DateTime]::UtcNow - $item.LastWriteTimeUtc
    if ($item.Length -le 0 -or $age.TotalSeconds -gt 10) {
        throw 'QuestLHSync recording is not actively advancing; stop before collecting markers.'
    }
    if ($item.Length -gt $script:lastLength) {
        $script:lastLength = [long]$item.Length
        $script:lastGrowthUtc = [DateTime]::UtcNow
    } elseif (([DateTime]::UtcNow - $script:lastGrowthUtc).TotalSeconds -gt 10) {
        throw 'QuestLHSync recording stopped growing; capture aborted without changing station power.'
    }
}

function Write-P3KMarker {
    param([Parameter(Mandatory)][ValidateSet('BASELINE_READY','OFF','OFF_READY','ON','ON_READY','SPINUP_DONE','PASS_DONE','CAPTURE_ABORTED')][string]$Action)
    Assert-P3KRecordingActive
    $tick = [System.Diagnostics.Stopwatch]::GetTimestamp()
    $frequency = [System.Diagnostics.Stopwatch]::Frequency
    $qpcNs = [long][Math]::Round(([double]$tick / [double]$frequency) * 1e9)
    $script:markerSequence++
    [pscustomobject]@{
        Seq = $script:markerSequence
        Action = $Action
        Channel = 7
        QpcNs = $qpcNs
        Utc = [DateTimeOffset]::UtcNow.ToString('O')
    } | Export-Csv -LiteralPath $markerPath -Append -NoTypeInformation -Encoding utf8
    Write-Host ("MARK {0,-16} ch7 QPC-ns={1}" -f $Action, $qpcNs) -ForegroundColor Cyan
}

function Wait-P3KActiveSeconds {
    param([Parameter(Mandatory)][ValidateRange(1, 60)][int]$Seconds)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        Start-Sleep -Milliseconds 500
        Assert-P3KRecordingActive
    }
}

function Read-P3KStep {
    param([Parameter(Mandatory)][string]$Prompt)
    [void](Read-Host $Prompt)
    Assert-P3KRecordingActive
}

Write-Host ''
Write-Host 'P3-K: controlled ch7 ON / OFF / ON capture' -ForegroundColor Green
Write-Host "Recording: $recordingFullPath"
Write-Host "Markers:   $markerPath"
Write-Host 'This script will not switch Lighthouse power.'
Write-Host 'Keep ch1, ch10 and ch13 ON throughout. Keep the headset worn, awake and tracked.'
Write-Host 'Use one fixed marked viewpoint and restore the same head position/orientation in both return phases.'
Write-Host 'Marker times are operator-confirmation QPC times, not measured laser transition instants.'

# Require evidence of active file growth before creating the marker CSV.
$initialLength = (Get-P3KRecordingItem).Length
Start-Sleep -Seconds 2
Assert-P3KRecordingActive
if ($script:lastLength -le $initialLength) {
    throw 'Recording size did not grow during the active-recording preflight.'
}

try {
    Read-P3KStep 'Confirm all stations ON, fixed view established, and QuestLHSync recording active; press ENTER'
    Write-P3KMarker 'BASELINE_READY'
    Write-Host 'Hold this view with ch7 ON for 20 seconds.'
    Wait-P3KActiveSeconds 20

    Read-P3KStep 'Power ch7 OFF now; press ENTER immediately after the physical action'
    Write-P3KMarker 'OFF'
    Read-P3KStep 'Restore the original marked viewpoint while ch7 remains OFF; press ENTER when ready'
    Write-P3KMarker 'OFF_READY'
    Write-Host 'Hold this view with ch7 OFF for 20 seconds.'
    Wait-P3KActiveSeconds 20

    Read-P3KStep 'Power ch7 ON now; press ENTER immediately after the physical action'
    Write-P3KMarker 'ON'
    Read-P3KStep 'Restore the original marked viewpoint with ch7 ON; press ENTER when ready'
    Write-P3KMarker 'ON_READY'
    Write-Host 'Wait 25 seconds for station spin-up in the same view.'
    Wait-P3KActiveSeconds 25
    Write-P3KMarker 'SPINUP_DONE'
    Write-Host 'Hold this view with ch7 ON for 20 seconds.'
    Wait-P3KActiveSeconds 20
    Write-P3KMarker 'PASS_DONE'

    Write-Host ''
    Write-Host 'Capture sequence marked. Confirm every station is ON, then stop the QuestLHSync recording.' -ForegroundColor Green
    [void](Read-Host 'After stopping the recording, press ENTER to print file hashes')
    $recordingHash = (Get-FileHash -LiteralPath $recordingFullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $markerHash = (Get-FileHash -LiteralPath $markerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "TXT: $recordingFullPath"
    Write-Host "TXT SHA-256: $recordingHash"
    Write-Host "CSV: $markerPath"
    Write-Host "CSV SHA-256: $markerHash"
    Write-Host 'Run the local analyzer only after recording has stopped and file size is stable.'
} catch {
    try {
        if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
            Write-P3KMarker 'CAPTURE_ABORTED'
        }
    } catch { }
    throw
}
