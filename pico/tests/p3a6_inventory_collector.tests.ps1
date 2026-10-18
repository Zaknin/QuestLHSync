param()

$ErrorActionPreference = 'Stop'
$script:CreatedOutputRoots = [System.Collections.Generic.List[string]]::new()
$modulePath = Join-Path $PSScriptRoot '..\tools\P3A6Inventory.psm1'
Import-Module $modulePath -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
}

function New-Approval([string[]]$Actions = @('read-only-inventory'), [string]$Device = 'Pico 4 Pro', [bool]$Expired = $false, [int]$ExpiresSeconds = 3600) {
    $now = [DateTime]::UtcNow
    $issued = $now.AddMinutes(-2)
    $expires = if ($Expired) { $now.AddMinutes(-1) } else { $now.AddSeconds($ExpiresSeconds) }
    return @{
        schema = 'p3a6.hardware_approval.v1'
        approval_id = 'test-run-01'
        device = $Device
        approved_actions = $Actions
        max_duration_seconds = 60
        max_observations = 200
        issued_at_utc = $issued.ToString('yyyy-MM-ddTHH:mm:ssZ')
        expires_at_utc = $expires.ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
}

function New-Response([int]$ExitCode = 0, [string]$Stdout = '', [string]$Stderr = '', [bool]$TimedOut = $false) {
    return [pscustomobject]@{ ExitCode = $ExitCode; Stdout = $Stdout; Stderr = $Stderr; TimedOut = $TimedOut }
}

function New-MockExecutor([scriptblock]$Responder, [System.Collections.Generic.List[object]]$Calls) {
    return {
        param([string[]]$Arguments, [int]$TimeoutMs)
        $Calls.Add([pscustomobject]@{ Arguments = @($Arguments); TimeoutMs = $TimeoutMs })
        return (& $Responder $Arguments $TimeoutMs)
    }.GetNewClosure()
}

function Get-StandardResponder {
    return {
        param([string[]]$Arguments, [int]$TimeoutMs)
        $line = $Arguments -join ' '
        if ($line -eq 'get-state' -or $line -eq '-t 42 get-state') { return New-Response -Stdout "device`n" }
        if ($line -match 'getprop ro\.product\.model') { return New-Response -Stdout "Pico 4 Pro`n" }
        if ($line -match 'getprop ro\.build\.fingerprint') { return New-Response -Stdout "pico/pico/pico:10/ABC123/456:user/release-keys`n" }
        if ($line -match 'getprop ro\.build\.version\.release') { return New-Response -Stdout "10`n" }
        if ($line -match 'uname -r') { return New-Response -Stdout "4.14.190-pico`n" }
        if ($line -match 'ps -A -o PID,NAME') { return New-Response -Stdout "123 com.picovr.quickcamera`n124 PVR`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
        if ($line -match 'pico-p3a6-fd-probe') {
            if ($line -match 'pid=123') { return New-Response -Stdout "P3A6`tFD`t8`t/dev/video3`nP3A6`tFDINFO`t8`tpos`t0`nP3A6`tFDINFO`t8`tflags`t02000002`nP3A6`tFDINFO`t8`tmnt_id`t22`nP3A6`tFDINFO`t8`tino`t1234`nP3A6`tFDINFO_STATUS`t8`tOBSERVED`nP3A6`tSTATUS`tOBSERVED`n" }
            return New-Response -Stdout "P3A6`tSTATUS`tPROCESS_DISAPPEARED`n"
        }
        throw "Unexpected mock command: $line"
    }.GetNewClosure()
}

function New-TestOutputRoot {
    $path = Join-Path ([IO.Path]::GetTempPath()) ('p3a6-inventory-tests-' + [guid]::NewGuid().ToString('N'))
    $script:CreatedOutputRoots.Add($path)
    return $path
}

function Invoke-TestRun([scriptblock]$Responder, [hashtable]$Approval, [string]$Confirmation, [string]$TransportId = $null, [string]$Action = 'read-only-inventory', [bool]$DryRun = $false) {
    $calls = [System.Collections.Generic.List[object]]::new()
    $executor = New-MockExecutor -Responder $Responder -Calls $calls
    $root = New-TestOutputRoot
    $arguments = @{
        Approval = $Approval
        OwnerConfirmation = $Confirmation
        AdbExecutor = $executor
        OutputRoot = $root
        Action = $Action
        DryRun = $DryRun
        MaxDurationSeconds = 60
        MaxRecords = 200
    }
    if ($TransportId) { $arguments.TransportId = $TransportId }
    $result = Invoke-P3A6Inventory @arguments
    return [pscustomobject]@{ Result = $result; Calls = $calls; Root = $root }
}

function Read-EvidenceText($Result) {
    $archive = [IO.Compression.ZipFile]::OpenRead($Result.archive_path)
    try {
        $entry = $archive.GetEntry('evidence.json')
        if (-not $entry) { throw 'evidence.json missing from archive' }
        $reader = [IO.StreamReader]::new($entry.Open())
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $archive.Dispose() }
}

$confirmation = 'P3-A6 APPROVE test-run-01 read-only-inventory'
$passCount = 0

# Missing approval blocks before the first device-facing call.
$case = Invoke-TestRun (Get-StandardResponder) $null $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_NO_APPROVAL') 'missing approval must be blocked'
Assert-True ($case.Calls.Count -eq 0) 'missing approval must make zero ADB calls'
$passCount++

# The shared gate rejects approval for the wrong model and expired approval.
$case = Invoke-TestRun (Get-StandardResponder) (New-Approval -Device 'Pico 4') $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_SCOPE_MISMATCH') 'wrong approval device must be blocked'
Assert-True ($case.Calls.Count -eq 0) 'wrong approval device must make zero ADB calls'
$passCount++
$case = Invoke-TestRun (Get-StandardResponder) (New-Approval -Expired $true) $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_EXPIRED') 'expired approval must be blocked'
Assert-True ($case.Calls.Count -eq 0) 'expired approval must make zero ADB calls'
$passCount++

# Approval expiry is rechecked between commands, after a slow device listing.
$expiresDuringRun = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if (($Arguments -join ' ') -eq 'get-state') {
        Start-Sleep -Milliseconds 2500
        return New-Response -Stdout "device`n"
    }
    throw 'expired approval must prevent the next command'
}.GetNewClosure()
$case = Invoke-TestRun $expiresDuringRun (New-Approval -ExpiresSeconds 2) $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_EXPIRED') 'approval must be rechecked before each ADB command'
Assert-True ($case.Calls.Count -eq 1) 'expired approval must stop before the second ADB command'
$passCount++

# The approved wall-clock limit is checked before a subsequent command.
$slowListing = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if (($Arguments -join ' ') -eq 'get-state') {
        Start-Sleep -Milliseconds 1500
        return New-Response -Stdout "device`n"
    }
    throw 'duration limit must stop before the next command'
}.GetNewClosure()
$shortDuration = New-Approval
$shortDuration.max_duration_seconds = 1
$case = Invoke-TestRun $slowListing $shortDuration $confirmation
Assert-True ($case.Result.status -eq 'PARTIAL_TIMEOUT' -and $case.Calls.Count -eq 1) 'duration limit must stop collection before another ADB call'
$passCount++

# Both ADB command count and persisted record count stay below the approval cap.
$limitedApproval = New-Approval
$limitedApproval.max_observations = 5
$case = Invoke-TestRun (Get-StandardResponder) $limitedApproval $confirmation
Assert-True ($case.Result.status -eq 'PARTIAL_RECORD_LIMIT_REACHED') 'record/command limit must stop the run explicitly'
Assert-True ($case.Result.adb_command_count -le 5 -and $case.Result.record_count -le 5) 'record and ADB command counts must not exceed approval'
$passCount++

# The collector API cannot escape its single supported action.
$case = Invoke-TestRun (Get-StandardResponder) (New-Approval) $confirmation -Action 'install'
Assert-True ($case.Result.status -eq 'BLOCKED_SCOPE_MISMATCH') 'unsupported action must be blocked'
Assert-True ($case.Calls.Count -eq 0) 'unsupported action must make zero ADB calls'
$passCount++

# Multiple transports without an explicit target must be rejected by ADB before shell commands.
$manyDevices = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if (($Arguments -join ' ') -eq 'get-state') {
        return New-Response -ExitCode 1 -Stderr 'adb: more than one device/emulator SERIAL-PRIVATE-MULTI'
    }
    throw 'collector issued a shell command after ADB rejected ambiguous transport'
}.GetNewClosure()
$case = Invoke-TestRun $manyDevices (New-Approval) $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_MULTIPLE_DEVICES') "multiple devices must be rejected without selected transport (got $($case.Result.status), calls=$($case.Calls.Count))"
Assert-True ($case.Calls.Count -eq 1) 'only adb get-state may run when transport is ambiguous'
Assert-True ((Read-EvidenceText $case.Result) -notmatch 'SERIAL-PRIVATE') 'device serials must not enter evidence'
$passCount++

# An ADB failure is a blocked partial artifact, never a successful empty result.
$adbFailure = { param([string[]]$Arguments, [int]$TimeoutMs) New-Response -ExitCode 1 -Stderr 'device offline' }.GetNewClosure()
$case = Invoke-TestRun $adbFailure (New-Approval) $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_ADB_DEVICE_STATE') 'ADB failure must be visible in the collector result'
$failedEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($failedEvidence.collection_status -eq 'BLOCKED' -and $failedEvidence.fields.build_fingerprint.status -eq 'NOT_OBSERVED') 'ADB failure must not become an empty successful collection'
$passCount++

# An unexpected physical model is discarded, and collection stops before build/process queries.
$unexpectedModel = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $line = $Arguments -join ' '
    if ($line -eq 'get-state') { return New-Response -Stdout "device`n" }
    if ($line -match 'getprop ro\.product\.model') { return New-Response -Stdout "Unexpected Headset`n" }
    throw 'collector continued after unexpected device identity'
}.GetNewClosure()
$case = Invoke-TestRun $unexpectedModel (New-Approval) $confirmation
Assert-True ($case.Result.status -eq 'BLOCKED_UNEXPECTED_DEVICE') 'unexpected model must be rejected'
Assert-True ($case.Calls.Count -eq 2) 'unexpected model must stop after identity check'
Assert-True ((Read-EvidenceText $case.Result) -notmatch 'Unexpected Headset|SERIAL-PRIVATE') 'unexpected identity and serial must not be persisted'
$passCount++

# Timeout retains explicitly partial results and must not mark unobserved fields as observed.
$timeoutResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $line = $Arguments -join ' '
    if ($line -eq 'get-state') { return New-Response -Stdout "device`n" }
    if ($line -match 'getprop ro\.product\.model') { return New-Response -Stdout "Pico 4 Pro`n" }
    if ($line -match 'getprop ro\.build\.fingerprint') { return New-Response -Stdout "pico/pico/pico:10/ABC123/456:user/release-keys`n" }
    if ($line -match 'getprop ro\.build\.version\.release') { return New-Response -TimedOut $true -Stdout 'partial output must be discarded' }
    throw 'collector continued after timeout'
}.GetNewClosure()
$case = Invoke-TestRun $timeoutResponder (New-Approval) $confirmation
Assert-True ($case.Result.status -eq 'PARTIAL_TIMEOUT') 'timeout must produce partial status'
$timeoutEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($timeoutEvidence.collection_status -eq 'PARTIAL') 'timeout evidence must be explicitly partial'
Assert-True ($timeoutEvidence.fields.android_release.status -eq 'UNAVAILABLE') 'timed-out field must be unavailable'
Assert-True ($timeoutEvidence.fields.kernel_release.status -eq 'NOT_OBSERVED') 'later field must remain not observed'
Assert-True (Test-Path -LiteralPath $case.Result.marker_path) 'partial collection must still have a final integrity marker'
$passCount++

# Permission-limited /proc is explicit and does not trigger privilege escalation.
$procDenied = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $line = $Arguments -join ' '
    if ($line -match 'pico-p3a6-fd-probe') { return New-Response -Stdout "P3A6`tSTATUS`tPROC_ACCESS_DENIED`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $procDenied (New-Approval) $confirmation
$procEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'PARTIAL_PERMISSION_DENIED') "proc access denial must stop as a partial result (got $($case.Result.status))"
Assert-True (($procEvidence.records | Where-Object { $_.kind -eq 'fd_inventory' } | Where-Object { $_.status -eq 'PERMISSION_DENIED' }).Count -gt 0) 'proc denial must be recorded explicitly'
Assert-True (@($case.Calls | Where-Object { ($_.Arguments -join ' ') -match 'pico-p3a6-fd-probe' }).Count -eq 1) 'collector must stop after the first proc permission denial'
Assert-True (-not (($case.Calls | ForEach-Object { $_.Arguments -join ' ' }) -match 'adb root|shell su|remount')) 'collector must not attempt privilege escalation'
$passCount++

# A readable fd but denied fdinfo is retained explicitly, then stops further device commands.
$fdinfoDenied = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $line = $Arguments -join ' '
    if ($line -match 'pid=123') { return New-Response -Stdout "P3A6`tFD`t8`t/dev/video3`nP3A6`tFDINFO_STATUS`t8`tPERMISSION_DENIED`nP3A6`tSTATUS`tPARTIAL_ACCESS`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $fdinfoDenied (New-Approval) $confirmation
$fdinfoEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
$deniedFd = @($fdinfoEvidence.records | Where-Object { $_.kind -eq 'video_fd' })[0]
Assert-True ($case.Result.status -eq 'PARTIAL_PERMISSION_DENIED') 'fdinfo access denial must stop collection'
Assert-True ($deniedFd.fdinfo.status -eq 'PERMISSION_DENIED') 'fdinfo access denial must remain explicit in evidence'
Assert-True (@($case.Calls | Where-Object { ($_.Arguments -join ' ') -match 'pico-p3a6-fd-probe' }).Count -eq 1) 'no later process probe may run after fdinfo denial'
$passCount++

# PID disappearance is retained as a status, not converted to an empty success.
$case = Invoke-TestRun (Get-StandardResponder) (New-Approval) $confirmation
$pidEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
$pidMatches = @($pidEvidence.records | Where-Object { $_.kind -eq 'fd_inventory' } | Where-Object { $_.status -eq 'UNAVAILABLE' -and $_.reason -eq 'PROCESS_DISAPPEARED' })
Assert-True ($pidMatches.Count -eq 1) "disappeared process must be explicit (count=$($pidMatches.Count))"
$passCount++

# A failing ps command is explicitly unavailable, never an observed empty process list.
$psFailure = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $line = $Arguments -join ' '
    if ($line -match 'pico-p3a6-process-probe') { return New-Response -Stdout "P3A6`tPROCESS_STATUS`tUNAVAILABLE`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $psFailure (New-Approval) $confirmation
$psEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'PARTIAL_UNEXPECTED_OUTPUT') 'failed process enumeration must stop as partial'
Assert-True ($psEvidence.fields.process_inventory.status -eq 'UNAVAILABLE') 'failed ps must not become an observed zero-process list'
Assert-True (@($psEvidence.records | Where-Object { $_.kind -eq 'video_fd' }).Count -eq 0) 'no fd probes may follow a failed process enumeration'
$passCount++

# Dry-run must never call the injected device executor, even with a valid approval.
$case = Invoke-TestRun (Get-StandardResponder) (New-Approval) $confirmation -DryRun $true
Assert-True ($case.Result.status -eq 'DRY_RUN') 'dry run should report its non-executing status'
Assert-True ($case.Calls.Count -eq 0) 'dry run must make zero device-facing executor calls'
$passCount++

# The native executor rejects all commands outside the fixed read-only allowlist before resolving ADB.
$rejectedNative = Invoke-P3A6NativeAdb -Arguments @('root') -TimeoutMs 1000
Assert-True ($rejectedNative.Rejected -eq $true -and $rejectedNative.StartFailed -eq $true) 'native executor must reject adb root without starting a process'
$module = Get-Module P3A6Inventory
$allowedDevices = & $module { Test-P3A6AllowedAdbArguments -Arguments @('get-state') }
$allowedProperty = & $module { Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'getprop', 'ro.build.fingerprint') }
$processCommand = & $module { Get-P3A6ProcessProbeScript -ProcessBudget 191 }
$quotedProcessCommand = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $processCommand
$allowedProcess = & $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $quotedProcessCommand
$rawProcessRejected = -not (& $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $processCommand)
$probeScript = & $module { Get-P3A6ProbeScript -ProcessId 321 -RecordBudget 17 }
$quotedProbeScript = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $probeScript
$allowedProbe = & $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $quotedProbeScript
$rawProbeRejected = -not (& $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $probeScript)
$rejectedShell = & $module { Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', 'ps -A -o PID,NAME | awk -v max=1 bad; adb root') }
Assert-True ($allowedDevices -and $allowedProperty -and $allowedProcess -and $allowedProbe -and $rawProcessRejected -and $rawProbeRejected -and -not $rejectedShell) 'native command allowlist must accept only exact POSIX-quoted inventory command shapes'
$passCount++

# Successful mock data is allowlisted; raw ADB output, serial and personal-looking stderr are not saved.
$privacyResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $response = & (Get-StandardResponder) $Arguments $TimeoutMs
    if (($Arguments -join ' ') -match 'ps -A -o PID,NAME') { $response.Stdout = "123 com.picovr.quickcamera`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
    $response.Stderr = 'private.user@example.invalid /data/user/0/private-account'
    return $response
}.GetNewClosure()
$case = Invoke-TestRun $privacyResponder (New-Approval) $confirmation -TransportId '42'
Assert-True ($case.Result.status -eq 'COMPLETE') 'standard mock collection should complete'
$evidenceText = Read-EvidenceText $case.Result
Assert-True ($evidenceText -notmatch 'SERIAL-PRIVATE|private\.user@example|private-account|PRIVATE-005') 'private identifiers must not be present in evidence'
$evidence = $evidenceText | ConvertFrom-Json -AsHashtable
foreach ($gateName in @('exact_time', 'mapping_verified', 'pose_verified', 'shared_buffer_identity_verified', 'frame_meta_bridge_verified', 'live_lighthouse_correction_allowed', 'physical_event_verified')) {
    Assert-True ($evidence.gates[$gateName] -eq $false) "safety gate $gateName must remain false"
}
Assert-True ($evidence.limits.observed_records -eq $evidence.record_count -and $evidence.limits.adb_commands -eq $evidence.adb_command_count) 'evidence limit counters must match persisted output'
Assert-True (@($evidence.records | Where-Object { $_.build_identity -ne $evidence.target.build_fingerprint }).Count -eq 0) 'every persisted record must bind to the observed build fingerprint'
$videoFd = @($evidence.records | Where-Object { $_.kind -eq 'video_fd' })[0]
Assert-True ($videoFd.node -eq '/dev/video3' -and $videoFd.fdinfo.fields.flags.value -eq '02000002') 'allowlisted fd and octal flags must be captured'
Assert-True ($videoFd.association -eq 'NOT_ATTRIBUTED_TO_VIDEOQUEUEUTIL_IOCTL') 'open node must not be claimed as ioctl-attributed'
$quotedProbeCalls = @($case.Calls | Where-Object { $_.Arguments[-1] -match "^'# pico-p3a6-(?:process|fd)-probe\r?\n" })
Assert-True ($quotedProbeCalls.Count -ge 2) 'collector must pass generated process and FD probes as POSIX-quoted single ADB shell arguments'
$marker = Get-Content -LiteralPath $case.Result.marker_path -Raw | ConvertFrom-Json -AsHashtable
$actualHash = (Get-FileHash -LiteralPath $case.Result.archive_path -Algorithm SHA256).Hash.ToLowerInvariant()
Assert-True ($marker.archive_sha256 -eq $actualHash) 'final marker must bind the archive SHA-256'
$acl = Get-Acl -LiteralPath $case.Result.evidence_directory
Assert-True ($acl.AreAccessRulesProtected) 'evidence run folder ACL must block inherited access'
$passCount++

$tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
foreach ($root in $script:CreatedOutputRoots) {
    $fullRoot = [IO.Path]::GetFullPath($root)
    if (-not $fullRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($fullRoot) -notmatch '^p3a6-inventory-tests-[0-9a-f]{32}$') {
        throw 'Refusing to clean an unexpected test output path'
    }
    if (Test-Path -LiteralPath $fullRoot) { [IO.Directory]::Delete($fullRoot, $true) }
}

Write-Output "P3-A6 M1 PowerShell mock collector checks: $passCount/18 PASS"
