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

$modulePath = Join-Path $PSScriptRoot 'P3A6Inventory.psm1'
Import-Module $modulePath -Force

if ($ExtraArguments.Count -gt 0) {
    if ($ExtraArguments.Count -eq 1 -and $ExtraArguments[0] -ceq '--dry-run') { $DryRun = $true }
    else {
        [Console]::Error.WriteLine('BLOCKED_INVALID_ARGUMENT: only --dry-run is accepted as an extra argument.')
        exit 4
    }
}

if ($DryRun) {
    $result = Invoke-P3A6Inventory -Approval $null -OwnerConfirmation $null -AdbExecutor { throw 'Dry-run executor must never run' } -OutputRoot $OutputRoot -TransportId $TransportId -DryRun
    Write-Output ($result | ConvertTo-Json -Depth 8 -Compress)
    exit 3
}

if (-not $ApprovalFile -or -not (Test-Path -LiteralPath $ApprovalFile -PathType Leaf)) {
    [Console]::Error.WriteLine('BLOCKED_NO_APPROVAL: provide the separate, run-specific approval JSON file.')
    exit 4
}
try {
    $approvalItem = Get-Item -LiteralPath $ApprovalFile -Force
    if (($approvalItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $approvalItem.Length -gt 65536) {
        throw 'Approval file rejected'
    }
    $approval = Get-Content -LiteralPath $ApprovalFile -Raw | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    if ($approval -isnot [System.Collections.IDictionary]) { throw 'Approval file rejected' }
}
catch {
    [Console]::Error.WriteLine('BLOCKED_INVALID_APPROVAL: approval JSON could not be read safely.')
    exit 4
}

$confirmation = Read-Host "Type the exact owner confirmation for approval '$($approval.approval_id)' and action 'read-only-inventory'"
$executor = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    return Invoke-P3A6NativeAdb -Arguments $Arguments -TimeoutMs $TimeoutMs
}.GetNewClosure()

$result = Invoke-P3A6Inventory -Approval $approval -OwnerConfirmation $confirmation -AdbExecutor $executor -OutputRoot $OutputRoot -TransportId $TransportId
Write-Output ($result | ConvertTo-Json -Depth 8 -Compress)
if ($result.status -eq 'COMPLETE') { exit 0 }
if ($result.status -like 'PARTIAL_*' -or $result.status -eq 'PARTIAL_LIMITATIONS') { exit 5 }
exit 4
