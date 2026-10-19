[CmdletBinding()]
param(
    [string]$ApprovalFile = '',
    [string]$TransportId = '',
    [string]$OutputRoot = '',
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArguments = @()
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    [Console]::Error.WriteLine('PowerShell 7 or later is required.')
    exit 4
}
$modulePath = Join-Path $PSScriptRoot 'P3A6CameraNodes.psm1'
Import-Module $modulePath -Force
if ($ExtraArguments.Count -gt 0) {
    if ($ExtraArguments.Count -eq 1 -and $ExtraArguments[0] -ceq '--dry-run') { $DryRun = $true }
    else { [Console]::Error.WriteLine('BLOCKED_INVALID_ARGUMENT: only --dry-run is accepted as an extra argument.'); exit 4 }
}
if ($DryRun) {
    $result = Invoke-P3A6M2DryRun
    Write-Output ($result | ConvertTo-Json -Depth 8 -Compress)
    exit 3
}
if (-not $ApprovalFile -or -not (Test-Path -LiteralPath $ApprovalFile -PathType Leaf)) {
    [Console]::Error.WriteLine('BLOCKED_NO_APPROVAL: provide a fresh, run-specific M2 approval JSON file.')
    exit 4
}
try {
    $item = Get-Item -LiteralPath $ApprovalFile -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.Length -gt 65536) { throw 'approval file rejected' }
    $approval = Get-Content -LiteralPath $ApprovalFile -Raw | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    if ($approval -isnot [Collections.IDictionary]) { throw 'approval object required' }
} catch {
    [Console]::Error.WriteLine('BLOCKED_INVALID_APPROVAL: approval JSON could not be read safely.')
    exit 4
}
$preflight = Test-P3A6M2ApprovalPreflight -Approval $approval -Action 'read-only-camera-node-metadata'
if (-not $preflight.allowed) {
    [Console]::Error.WriteLine("$($preflight.status): approval is invalid, expired or outside M2 scope.")
    exit 4
}
$maximumDuration = [Math]::Min(30,[int]$approval.max_duration_seconds)
$maximumObservations = [Math]::Min(40,[int]$approval.max_observations)
Write-Host 'Device: Pico 4 Pro'
Write-Host 'Action: read-only-camera-node-metadata'
Write-Host "Maximum duration: $maximumDuration seconds"
Write-Host "Maximum observations: $maximumObservations"
$interactive = -not [Console]::IsInputRedirected
$response = $null
if ($interactive) { try { $response = Read-Host 'Confirm operation (yes/no)' } catch { $response = $null } }
$typedConfirmation = Resolve-P3A6M2Confirmation -Approval $approval -Response $response -Interactive $interactive -Action 'read-only-camera-node-metadata'
$executor = {
    param([string[]]$Arguments,[int]$TimeoutMs)
    return Invoke-P3A6M2NativeAdb -Arguments $Arguments -TimeoutMs $TimeoutMs -Approval $approval -OwnerConfirmation $typedConfirmation.token -Action 'read-only-camera-node-metadata'
}.GetNewClosure()
$result = Invoke-P3A6M2ConfirmedInventory -Approval $approval -Response $response -Interactive $interactive -AdbExecutor $executor -OutputRoot $OutputRoot -TransportId $TransportId
Write-Output ($result | ConvertTo-Json -Depth 16 -Compress)
if ($result.collection_status -eq 'COMPLETE') { exit 0 }
if ($result.collection_status -like 'PARTIAL*') { exit 5 }
exit 4
