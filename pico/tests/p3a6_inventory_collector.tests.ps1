param()

$ErrorActionPreference = 'Stop'
$script:CreatedOutputRoots = [System.Collections.Generic.List[string]]::new()
$modulePath = Join-Path $PSScriptRoot '..\tools\P3A6Inventory.psm1'
Import-Module $modulePath -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
}

function Assert-CallVector([System.Collections.Generic.List[object]]$Calls, [int]$Index, [string[]]$Expected, [string]$Message) {
    Assert-True ($Index -lt $Calls.Count) "$Message (call $Index is absent)"
    Assert-True ($Calls[$Index].AllowedByNative -eq $true) "$Message must pass the actual native allowlist"
    Assert-True (Test-ExactArgumentVector -Actual $Calls[$Index].Arguments -Expected $Expected) $Message
}

function Assert-StandardRunArgumentVectors([System.Collections.Generic.List[object]]$Calls, [AllowNull()][string]$TransportId = $null) {
    [string[]]$prefix = @('shell')
    [string[]]$stateVector = @('get-state')
    if ($TransportId) {
        $prefix = [string[]]@('-t', $TransportId, 'shell')
        $stateVector = [string[]]@('-t', $TransportId, 'get-state')
    }
    Assert-CallVector $Calls 0 $stateVector 'get-state vector must match exactly'
    Assert-CallVector $Calls 1 ([string[]]($prefix + @('getprop', 'ro.product.model'))) 'product model vector must match exactly'
    Assert-CallVector $Calls 2 ([string[]]($prefix + @('getprop', 'ro.product.device'))) 'product device vector must match exactly'
    Assert-CallVector $Calls 3 ([string[]]($prefix + @('getprop', 'ro.product.name'))) 'product name vector must match exactly'
    Assert-CallVector $Calls 4 ([string[]]($prefix + @('getprop', 'ro.product.manufacturer'))) 'product manufacturer vector must match exactly'
    Assert-CallVector $Calls 5 ([string[]]($prefix + @('getprop', 'ro.build.fingerprint'))) 'build fingerprint vector must match exactly'
    Assert-CallVector $Calls 6 ([string[]]($prefix + @('getprop', 'ro.build.version.release'))) 'Android release vector must match exactly'
    Assert-CallVector $Calls 7 ([string[]]($prefix + @('uname', '-r'))) 'kernel release vector must match exactly'

    $module = Get-Module -Name 'P3A6Inventory'
    $processScript = & $module { param($budget) Get-P3A6ProcessProbeScript -ProcessBudget $budget } 192
    $quotedProcessScript = & $module { param($probe) ConvertTo-P3A6PosixShellArgument -Value $probe } $processScript
    Assert-CallVector $Calls 8 ([string[]]($prefix + @('sh', '-c', $quotedProcessScript))) 'process probe vector must match the generated allowlisted command exactly'

    $fdScript = & $module { param($processId, $budget) Get-P3A6ProbeScript -ProcessId $processId -RecordBudget $budget } 123 191
    $quotedFdScript = & $module { param($probe) ConvertTo-P3A6PosixShellArgument -Value $probe } $fdScript
    Assert-CallVector $Calls 9 ([string[]]($prefix + @('sh', '-c', $quotedFdScript))) 'FD probe vector must match the generated allowlisted command exactly'
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

function Test-ExactArgumentVector([string[]]$Actual, [string[]]$Expected) {
    if ($Actual.Count -ne $Expected.Count) { return $false }
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        if ($Actual[$index] -cne $Expected[$index]) { return $false }
    }
    return $true
}

function Get-TestCommandKind([string[]]$Arguments) {
    $offset = 0
    if ($Arguments.Count -gt 0 -and $Arguments[0] -ceq '-t') {
        if ($Arguments.Count -lt 3 -or $Arguments[1] -notmatch '^[1-9]\d{0,9}$') { return 'UNSUPPORTED' }
        if ($Arguments.Count -eq 3 -and $Arguments[2] -ceq 'get-state') { return 'GET_STATE' }
        if ($Arguments[2] -cne 'shell') { return 'UNSUPPORTED' }
        $offset = 2
    }

    if ($Arguments.Count -eq ($offset + 1) -and $Arguments[$offset] -ceq 'get-state') { return 'GET_STATE' }
    if ($Arguments.Count -eq ($offset + 3) -and $Arguments[$offset] -ceq 'shell') {
        if ($Arguments[$offset + 1] -ceq 'getprop') {
            switch -CaseSensitive ($Arguments[$offset + 2]) {
                'ro.product.model' { return 'PRODUCT_MODEL' }
                'ro.product.device' { return 'PRODUCT_DEVICE' }
                'ro.product.name' { return 'PRODUCT_NAME' }
                'ro.product.manufacturer' { return 'PRODUCT_MANUFACTURER' }
                'ro.build.fingerprint' { return 'BUILD_FINGERPRINT' }
                'ro.build.version.release' { return 'ANDROID_RELEASE' }
            }
        }
        if ($Arguments[$offset + 1] -ceq 'uname' -and $Arguments[$offset + 2] -ceq '-r') { return 'KERNEL_RELEASE' }
    }
    if ($Arguments.Count -eq ($offset + 4) -and $Arguments[$offset] -ceq 'shell' -and $Arguments[$offset + 1] -ceq 'sh' -and $Arguments[$offset + 2] -ceq '-c') {
        if ($Arguments[$offset + 3] -match "(?s)^'# pico-p3a6-process-probe\r?\nlimit=\d{1,4}\r?\n") { return 'PROCESS_PROBE' }
        if ($Arguments[$offset + 3] -match "(?s)^'# pico-p3a6-fd-probe\r?\npid=\d+\r?\nlimit=\d+\r?\n") { return 'FD_PROBE' }
    }
    return 'UNSUPPORTED'
}

function New-MockExecutor([scriptblock]$Responder, [System.Collections.Generic.List[object]]$Calls) {
    return {
        param([string[]]$Arguments, [int]$TimeoutMs)
        $module = Get-Module -Name 'P3A6Inventory'
        $allowedByNative = [bool](& $module { param($vector) Test-P3A6AllowedAdbArguments -Arguments ([string[]]$vector) } ([string[]]$Arguments))
        $Calls.Add([pscustomobject]@{ Arguments = [string[]]$Arguments; TimeoutMs = $TimeoutMs; AllowedByNative = $allowedByNative })
        if (-not $allowedByNative) { throw 'The actual native ADB allowlist rejected the mock argument vector' }
        return (& $Responder $Arguments $TimeoutMs)
    }.GetNewClosure()
}

function Get-StandardResponder {
    return {
        param([string[]]$Arguments, [int]$TimeoutMs)
        switch -CaseSensitive (Get-TestCommandKind -Arguments $Arguments) {
            'GET_STATE' { return New-Response -Stdout "device`n" }
            'PRODUCT_MODEL' { return New-Response -Stdout "A8110`n" }
            'PRODUCT_DEVICE' { return New-Response -Stdout "PICOA8110`n" }
            'PRODUCT_NAME' { return New-Response -Stdout "Phoenix_ovs`n" }
            'PRODUCT_MANUFACTURER' { return New-Response -Stdout "Pico`n" }
            'BUILD_FINGERPRINT' { return New-Response -Stdout "pico/pico/pico:10/ABC123/456:user/release-keys`n" }
            'ANDROID_RELEASE' { return New-Response -Stdout "10`n" }
            'KERNEL_RELEASE' { return New-Response -Stdout "4.14.190-pico`n" }
            'PROCESS_PROBE' { return New-Response -Stdout "123 com.picovr.quickcamera`n124 PVR`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
            'FD_PROBE' {
                if ($Arguments[-1] -match "(?s)^'# pico-p3a6-fd-probe\r?\npid=(\d+)\r?\n") {
                    if ([int]$Matches[1] -eq 123) { return New-Response -Stdout "P3A6`tFD`t8`t/dev/video3`nP3A6`tFDINFO`t8`tpos`t0`nP3A6`tFDINFO`t8`tflags`t02000002`nP3A6`tFDINFO`t8`tmnt_id`t22`nP3A6`tFDINFO`t8`tino`t1234`nP3A6`tFDINFO_STATUS`t8`tOBSERVED`nP3A6`tSTATUS`tOBSERVED`n" }
                }
            return New-Response -Stdout "P3A6`tSTATUS`tPROCESS_DISAPPEARED`n"
            }
        }
        throw 'Unexpected or malformed mock ADB argument vector'
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
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'GET_STATE') {
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
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'GET_STATE') {
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
Assert-CallVector $case.Calls 1 @('shell', 'getprop', 'ro.product.model') 'product model query must use the exact no-transport argument vector'
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
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'GET_STATE') {
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

# The owner's exact observed tuple is retained with per-property provenance, while
# the Phoenix-family software identity stays distinct from Pro hardware attestation.
$exactTupleResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $response = & (Get-StandardResponder) $Arguments $TimeoutMs
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PROCESS_PROBE') { $response.Stdout = "123 com.picovr.quickcamera`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
    return $response
}.GetNewClosure()
$case = Invoke-TestRun $exactTupleResponder (New-Approval) $confirmation
$tupleEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'COMPLETE') "the exact observed A8110 property tuple must be accepted (status=$($case.Result.status), calls=$($case.Result.adb_command_count), records=$($case.Result.record_count))"
Assert-True ($tupleEvidence.fields.product_model.value -ceq 'A8110' -and $tupleEvidence.fields.product_device.value -ceq 'PICOA8110' -and $tupleEvidence.fields.product_name.value -ceq 'Phoenix_ovs' -and $tupleEvidence.fields.product_manufacturer.value -ceq 'Pico') 'all four actual Android properties must be retained'
foreach ($fieldName in @('product_model', 'product_device', 'product_name', 'product_manufacturer')) {
    Assert-True ($tupleEvidence.fields[$fieldName].status -eq 'OBSERVED' -and $tupleEvidence.fields[$fieldName].method -match 'getprop' -and $tupleEvidence.fields[$fieldName].observed_at_utc -and $tupleEvidence.fields[$fieldName].build_identity -eq $tupleEvidence.target.build_fingerprint) "identity field $fieldName must have provenance, time and build identity"
}
Assert-True ($tupleEvidence.identity.owner_declared_target -eq 'Pico 4 Pro' -and $tupleEvidence.identity.android_property_tuple_status -eq 'VERIFIED' -and $tupleEvidence.identity.phoenix_family_status -eq 'VERIFIED') 'exact tuple must verify only the owner-bound Phoenix-family software identity'
Assert-True ($tupleEvidence.identity.pico_4_pro_hardware_variant_status -eq 'NOT_VERIFIED' -and $tupleEvidence.identity.cryptographic_attestation -eq $false) 'Android properties must not be represented as Pro hardware attestation'
Assert-True ($tupleEvidence.collector.version -eq 'P3-A6-M1.5-v1' -and $tupleEvidence.collector.source_sha256.module -match '^[0-9a-f]{64}$') 'identity evidence must identify the collector revision and module digest'
Assert-StandardRunArgumentVectors $case.Calls
$passCount++

# A8110 alone, or any wrong member of the exact tuple, fails closed before build/process inventory.
$tupleMismatches = @(
    @{ kind = 'PRODUCT_MODEL'; field = 'product_model'; value = 'Unexpected Headset' },
    @{ kind = 'PRODUCT_DEVICE'; field = 'product_device'; value = 'PICOA8100' },
    @{ kind = 'PRODUCT_DEVICE'; field = 'product_device'; value = 'PICOA81-other' },
    @{ kind = 'PRODUCT_NAME'; field = 'product_name'; value = 'Phoenix_other' },
    @{ kind = 'PRODUCT_MANUFACTURER'; field = 'product_manufacturer'; value = 'OtherBrand' },
    @{ kind = 'PRODUCT_MANUFACTURER'; field = 'product_manufacturer'; value = 'pico' }
)
foreach ($variant in $tupleMismatches) {
    $mismatchResponder = {
        param([string[]]$Arguments, [int]$TimeoutMs)
        $kind = Get-TestCommandKind -Arguments $Arguments
        if ($kind -eq $variant.kind) { return New-Response -Stdout ($variant.value + "`n") }
        return & (Get-StandardResponder) $Arguments $TimeoutMs
    }.GetNewClosure()
    $case = Invoke-TestRun $mismatchResponder (New-Approval) $confirmation
    $mismatchEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
    Assert-True ($case.Result.status -eq 'BLOCKED_UNEXPECTED_DEVICE' -and $mismatchEvidence.collection_status -eq 'BLOCKED') "mismatched $($variant.field) must block the run"
    Assert-True ($mismatchEvidence.fields[$variant.field].status -eq 'OBSERVED' -and $mismatchEvidence.fields[$variant.field].value -ceq $variant.value) "allowlisted mismatched $($variant.field) must be retained as observed evidence"
    if ($variant.field -ne 'product_model') { Assert-True ($mismatchEvidence.fields.product_model.value -ceq 'A8110') 'A8110 by itself must not accept a mismatched device/name/manufacturer tuple' }
    Assert-True ($mismatchEvidence.identity.android_property_tuple_status -eq 'MISMATCH' -and $mismatchEvidence.identity.phoenix_family_status -eq 'UNVERIFIED') 'partial or mismatched tuple must not verify the Phoenix family'
    Assert-True ($case.Calls.Count -eq 5) 'all four identity properties may be read, but no build or process probe may follow a mismatch'
}
$passCount++

# Missing identity properties block at the missing field and leave later fields NOT_OBSERVED.
$identityFieldKinds = @(
    @{ kind = 'PRODUCT_MODEL'; field = 'product_model' },
    @{ kind = 'PRODUCT_DEVICE'; field = 'product_device' },
    @{ kind = 'PRODUCT_NAME'; field = 'product_name' },
    @{ kind = 'PRODUCT_MANUFACTURER'; field = 'product_manufacturer' }
)
for ($missingIndex = 0; $missingIndex -lt $identityFieldKinds.Count; $missingIndex++) {
    $missingSpec = $identityFieldKinds[$missingIndex]
    $missingResponder = {
        param([string[]]$Arguments, [int]$TimeoutMs)
        if ((Get-TestCommandKind -Arguments $Arguments) -eq $missingSpec.kind) { return New-Response -Stdout '' }
        return & (Get-StandardResponder) $Arguments $TimeoutMs
    }.GetNewClosure()
    $case = Invoke-TestRun $missingResponder (New-Approval) $confirmation
    $missingEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
    Assert-True ($case.Result.status -eq 'BLOCKED_INVALID_DEVICE_IDENTITY') "missing $($missingSpec.field) must block identity validation"
    Assert-True ($missingEvidence.fields[$missingSpec.field].status -eq 'UNAVAILABLE' -and $missingEvidence.fields[$missingSpec.field].reason -eq 'EMPTY_IDENTITY_PROPERTY') "missing $($missingSpec.field) must be explicitly unavailable"
    Assert-True ($missingEvidence.identity.android_property_tuple_status -eq 'INCOMPLETE' -and $missingEvidence.identity.phoenix_family_status -eq 'UNVERIFIED') 'missing tuple member must not pass family identity'
    Assert-True ($case.Calls.Count -eq (2 + $missingIndex)) 'collection must stop on the first missing tuple member'
    for ($laterIndex = $missingIndex + 1; $laterIndex -lt $identityFieldKinds.Count; $laterIndex++) {
        $laterField = $identityFieldKinds[$laterIndex].field
        Assert-True ($missingEvidence.fields[$laterField].status -eq 'NOT_OBSERVED') "later field $laterField must remain NOT_OBSERVED after missing $($missingSpec.field)"
    }
}
$passCount++

# Multiline identity output is rejected without preserving its raw contents or continuing collection.
for ($multiIndex = 0; $multiIndex -lt $identityFieldKinds.Count; $multiIndex++) {
    $multiSpec = $identityFieldKinds[$multiIndex]
    $multiResponder = {
        param([string[]]$Arguments, [int]$TimeoutMs)
        if ((Get-TestCommandKind -Arguments $Arguments) -eq $multiSpec.kind) { return New-Response -Stdout "A8110`nPICOA8110`n" }
        return & (Get-StandardResponder) $Arguments $TimeoutMs
    }.GetNewClosure()
    $case = Invoke-TestRun $multiResponder (New-Approval) $confirmation
    $multiEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
    Assert-True ($case.Result.status -eq 'BLOCKED_INVALID_DEVICE_IDENTITY') "multiline $($multiSpec.field) must block identity validation"
    Assert-True ($multiEvidence.fields[$multiSpec.field].status -eq 'UNAVAILABLE' -and $multiEvidence.fields[$multiSpec.field].value -eq $null -and $multiEvidence.fields[$multiSpec.field].reason -eq 'UNEXPECTED_MULTILINE_VALUE' -and $multiEvidence.identity.phoenix_family_status -eq 'UNVERIFIED') "multiline $($multiSpec.field) must have an explicit safe reason and no raw value"
    Assert-True ($case.Calls.Count -eq (2 + $multiIndex)) 'no later identity, build or process query may run after multiline output'
}
$passCount++

# A single-line value outside the bounded character allowlist is discarded and blocks collection.
$malformedIdentityResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PRODUCT_DEVICE') { return New-Response -Stdout "PICOA8110;adb root`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $malformedIdentityResponder (New-Approval) $confirmation
$malformedIdentityEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'BLOCKED_INVALID_DEVICE_IDENTITY' -and $malformedIdentityEvidence.fields.product_device.status -eq 'UNAVAILABLE' -and $malformedIdentityEvidence.fields.product_device.reason -eq 'INVALID_IDENTITY_PROPERTY' -and $malformedIdentityEvidence.fields.product_device.value -eq $null) 'single-line malformed identity value must be discarded and block'
Assert-True ($case.Calls.Count -eq 3) 'no further identity or inventory command may follow malformed identity value'
$passCount++

# An identity property ADB failure stops immediately and remains explicit, without raw stderr.
$identityAdbFailure = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PRODUCT_NAME') { return New-Response -ExitCode 1 -Stderr 'permission denied /private.user@example.invalid' }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $identityAdbFailure (New-Approval) $confirmation
$identityFailureText = Read-EvidenceText $case.Result
$identityFailureEvidence = $identityFailureText | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'PARTIAL_ADB_ERROR' -and $identityFailureEvidence.fields.product_name.status -eq 'PERMISSION_DENIED' -and $identityFailureEvidence.identity.android_property_tuple_status -eq 'INCOMPLETE') 'identity command failure must remain partial and unverified'
Assert-True ($case.Calls.Count -eq 4 -and $identityFailureEvidence.fields.product_manufacturer.status -eq 'NOT_OBSERVED') 'identity command failure must stop later calls and leave fields unobserved'
Assert-True ($identityFailureText -notmatch 'permission denied|private.user@example') 'identity ADB stderr must not be persisted'
$passCount++

# Timeout retains explicitly partial results and must not mark unobserved fields as observed.
$timeoutResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $kind = Get-TestCommandKind -Arguments $Arguments
    if ($kind -eq 'GET_STATE') { return New-Response -Stdout "device`n" }
    if ($kind -eq 'BUILD_FINGERPRINT') { return New-Response -Stdout "pico/pico/pico:10/ABC123/456:user/release-keys`n" }
    if ($kind -eq 'ANDROID_RELEASE') { return New-Response -TimedOut $true -Stdout 'partial output must be discarded' }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
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
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'FD_PROBE') { return New-Response -Stdout "P3A6`tSTATUS`tPROC_ACCESS_DENIED`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $procDenied (New-Approval) $confirmation
$procEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'PARTIAL_PERMISSION_DENIED') "proc access denial must stop as a partial result (got $($case.Result.status))"
Assert-True (($procEvidence.records | Where-Object { $_.kind -eq 'fd_inventory' } | Where-Object { $_.status -eq 'PERMISSION_DENIED' }).Count -gt 0) 'proc denial must be recorded explicitly'
Assert-True (@($case.Calls | Where-Object { (Get-TestCommandKind -Arguments $_.Arguments) -eq 'FD_PROBE' }).Count -eq 1) 'collector must stop after the first proc permission denial'
Assert-True (@($case.Calls | Where-Object { -not $_.AllowedByNative }).Count -eq 0) 'every synthetic ADB response must pass the native allowlist first'
$passCount++

# A readable fd but denied fdinfo is retained explicitly, then stops further device commands.
$fdinfoDenied = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'FD_PROBE' -and $Arguments[-1] -match "(?s)^'# pico-p3a6-fd-probe\r?\npid=123\r?\n") { return New-Response -Stdout "P3A6`tFD`t8`t/dev/video3`nP3A6`tFDINFO_STATUS`t8`tPERMISSION_DENIED`nP3A6`tSTATUS`tPARTIAL_ACCESS`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $fdinfoDenied (New-Approval) $confirmation
$fdinfoEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
$deniedFd = @($fdinfoEvidence.records | Where-Object { $_.kind -eq 'video_fd' })[0]
Assert-True ($case.Result.status -eq 'PARTIAL_PERMISSION_DENIED') 'fdinfo access denial must stop collection'
Assert-True ($deniedFd.fdinfo.status -eq 'PERMISSION_DENIED') 'fdinfo access denial must remain explicit in evidence'
Assert-True (@($case.Calls | Where-Object { (Get-TestCommandKind -Arguments $_.Arguments) -eq 'FD_PROBE' }).Count -eq 1) 'no later process probe may run after fdinfo denial'
$passCount++

# PID disappearance is retained as a status, not converted to an empty success.
$case = Invoke-TestRun (Get-StandardResponder) (New-Approval) $confirmation
$pidEvidence = Read-EvidenceText $case.Result | ConvertFrom-Json -AsHashtable
$pidMatches = @($pidEvidence.records | Where-Object { $_.kind -eq 'fd_inventory' } | Where-Object { $_.status -eq 'UNAVAILABLE' -and $_.reason -eq 'PROCESS_DISAPPEARED' })
Assert-True ($pidMatches.Count -eq 1) "disappeared process must be explicit (count=$($pidMatches.Count))"
$passCount++

# Android process names may contain a literal colon; all 13 matching entries must parse and reach /proc FD inventory.
$colonProcessLines = [System.Collections.Generic.List[string]]::new()
for ($processIndex = 1; $processIndex -le 12; $processIndex++) {
    $colonProcessLines.Add("$($processIndex + 122) com.picovr.quickcamera.$processIndex")
}
$colonProcessLines.Add('135 com.picovr.quickcamera:service')
$colonProcessOutput = ($colonProcessLines -join "`n") + "`nP3A6`tPROCESS_STATUS`tOBSERVED`n"
$colonResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $kind = Get-TestCommandKind -Arguments $Arguments
    if ($kind -eq 'PROCESS_PROBE') { return New-Response -Stdout $colonProcessOutput }
    if ($kind -eq 'FD_PROBE') { return New-Response -Stdout "P3A6`tSTATUS`tPROCESS_DISAPPEARED`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$module = Get-Module -Name 'P3A6Inventory'
foreach ($colonTransport in @($null, '42')) {
    if ($colonTransport) { $case = Invoke-TestRun $colonResponder (New-Approval) $confirmation -TransportId $colonTransport }
    else { $case = Invoke-TestRun $colonResponder (New-Approval) $confirmation }
    $colonEvidenceText = Read-EvidenceText $case.Result
    $colonEvidence = $colonEvidenceText | ConvertFrom-Json -AsHashtable
    Assert-True ($case.Result.status -ne 'PARTIAL_UNEXPECTED_OUTPUT' -and $colonEvidence.fields.process_inventory.status -eq 'OBSERVED' -and $colonEvidence.fields.process_inventory.value -eq 13) '13 matching Android processes including index 13 with colon must parse as observed'
    $colonRecord = @($colonEvidence.records | Where-Object { $_.kind -eq 'process' -and $_.pid -eq 135 })[0]
    Assert-True ($colonRecord.process_name -ceq 'com.picovr.quickcamera:service') 'colon process name must be preserved exactly in private evidence'
    $fdCalls = @($case.Calls | Where-Object { (Get-TestCommandKind -Arguments $_.Arguments) -eq 'FD_PROBE' })
    Assert-True ($fdCalls.Count -eq 13) 'every matching process, including the colon process, must reach the read-only FD probe'
    Assert-StandardRunArgumentVectors $case.Calls $colonTransport
    $fdProcessIds = [System.Collections.Generic.List[int]]::new()
    foreach ($fdCall in $fdCalls) {
        Assert-True ($fdCall.AllowedByNative -eq $true) 'every synthetic FD response must pass the actual native allowlist first'
        $fdScript = $fdCall.Arguments[-1]
        Assert-True ($fdScript -match "(?s)^'# pico-p3a6-fd-probe\r?\npid=(\d+)\r?\nlimit=(\d+)\r?\n") 'FD vector must contain the generated protocol script'
        $fdPid = [int]$Matches[1]
        $fdBudget = [int]$Matches[2]
        $fdProcessIds.Add($fdPid)
        $expectedFdScript = & $module { param($processId, $budget) Get-P3A6ProbeScript -ProcessId $processId -RecordBudget $budget } $fdPid $fdBudget
        $expectedQuotedFdScript = & $module { param($probe) ConvertTo-P3A6PosixShellArgument -Value $probe } $expectedFdScript
        [string[]]$expectedFdVector = if ($colonTransport) { @('-t', $colonTransport, 'shell', 'sh', '-c', $expectedQuotedFdScript) } else { @('shell', 'sh', '-c', $expectedQuotedFdScript) }
        Assert-True (Test-ExactArgumentVector -Actual $fdCall.Arguments -Expected $expectedFdVector) 'each FD probe must retain an exact native argument vector'
    }
    Assert-True (($fdProcessIds -join ',') -ceq '123,124,125,126,127,128,129,130,131,132,133,134,135') 'FD probes must include PID 135 for the colon process and preserve enumeration order'
}
$passCount++

# A process name outside the literal bounded character allowlist fails closed and is not persisted.
$malformedProcessName = 'com.picovr/quickcamera'
$malformedProcessResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PROCESS_PROBE') { return New-Response -Stdout "123 $malformedProcessName`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $malformedProcessResponder (New-Approval) $confirmation
$malformedProcessEvidenceText = Read-EvidenceText $case.Result
$malformedProcessEvidence = $malformedProcessEvidenceText | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'PARTIAL_UNEXPECTED_OUTPUT' -and $malformedProcessEvidence.fields.process_inventory.status -eq 'UNAVAILABLE') 'slash in process name must fail closed as unexpected output'
Assert-True (@($case.Calls | Where-Object { (Get-TestCommandKind -Arguments $_.Arguments) -eq 'FD_PROBE' }).Count -eq 0 -and $malformedProcessEvidenceText -notmatch [regex]::Escape($malformedProcessName)) 'malformed process names must not reach FD probes or be persisted'
$passCount++

# Unexpected process protocol records fail closed instead of being skipped.
$unexpectedProcessRecord = "P3A6`tPROCESS_EXTRA`tOBSERVED"
$unexpectedProcessResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PROCESS_PROBE') { return New-Response -Stdout "123 com.picovr.quickcamera`n$unexpectedProcessRecord`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
    return & (Get-StandardResponder) $Arguments $TimeoutMs
}.GetNewClosure()
$case = Invoke-TestRun $unexpectedProcessResponder (New-Approval) $confirmation
$unexpectedProcessEvidenceText = Read-EvidenceText $case.Result
$unexpectedProcessEvidence = $unexpectedProcessEvidenceText | ConvertFrom-Json -AsHashtable
Assert-True ($case.Result.status -eq 'PARTIAL_UNEXPECTED_OUTPUT' -and $unexpectedProcessEvidence.fields.process_inventory.status -eq 'UNAVAILABLE') 'unexpected process protocol record must fail closed'
Assert-True (@($case.Calls | Where-Object { (Get-TestCommandKind -Arguments $_.Arguments) -eq 'FD_PROBE' }).Count -eq 0 -and $unexpectedProcessEvidenceText -notmatch 'PROCESS_EXTRA') 'unexpected process protocol record must stop before FD probes and remain private'
$passCount++

# A failing ps command is explicitly unavailable, never an observed empty process list.
$psFailure = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PROCESS_PROBE') { return New-Response -Stdout "P3A6`tPROCESS_STATUS`tUNAVAILABLE`n" }
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
$allowedPropertyVectors = @(
    @('shell', 'getprop', 'ro.product.model'),
    @('-t', '42', 'shell', 'getprop', 'ro.product.device'),
    @('shell', 'getprop', 'ro.product.name'),
    @('-t', '42', 'shell', 'getprop', 'ro.product.manufacturer'),
    @('-t', '42', 'shell', 'getprop', 'ro.build.fingerprint'),
    @('shell', 'getprop', 'ro.build.version.release')
)
$allowedProperty = @($allowedPropertyVectors | Where-Object { & $module { param($vector) Test-P3A6AllowedAdbArguments -Arguments ([string[]]$vector) } $_ }).Count -eq $allowedPropertyVectors.Count
$unlistedPropertyRejected = -not (& $module { Test-P3A6AllowedAdbArguments -Arguments @('shell', 'getprop', 'ro.serialno') })
$caseVariantPropertyRejected = -not (& $module { Test-P3A6AllowedAdbArguments -Arguments @('shell', 'getprop', 'RO.PRODUCT.MODEL') })
$processCommand = & $module { Get-P3A6ProcessProbeScript -ProcessBudget 191 }
$quotedProcessCommand = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $processCommand
$allowedProcess = & $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $quotedProcessCommand
$rawProcessRejected = -not (& $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $processCommand)
$probeScript = & $module { Get-P3A6ProbeScript -ProcessId 321 -RecordBudget 17 }
$quotedProbeScript = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $probeScript
$allowedProbe = & $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $quotedProbeScript
$rawProbeRejected = -not (& $module { param($text) Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', $text) } $probeScript)
$rejectedShell = & $module { Test-P3A6AllowedAdbArguments -Arguments @('-t', '42', 'shell', 'sh', '-c', 'ps -A -o PID,NAME | awk -v max=1 bad; adb root') }
Assert-True ($allowedDevices -and $allowedProperty -and $unlistedPropertyRejected -and $caseVariantPropertyRejected -and $allowedProcess -and $allowedProbe -and $rawProcessRejected -and $rawProbeRejected -and -not $rejectedShell) 'native command allowlist must accept only exact-case identity/property and POSIX-quoted inventory shapes'
$passCount++

# ADB resolution is pinned to the SDK under LOCALAPPDATA, regardless of other PATH copies.
$adbResolutionRoot = New-TestOutputRoot
$sdkAdbPath = Join-Path $adbResolutionRoot 'Android\Sdk\platform-tools\adb.exe'
$pathAdbDirectories = @(
    (Join-Path $adbResolutionRoot 'path-copy-one'),
    (Join-Path $adbResolutionRoot 'path-copy-two')
)
New-Item -ItemType Directory -Path (Split-Path -Parent $sdkAdbPath) -Force | Out-Null
[IO.File]::WriteAllText($sdkAdbPath, 'synthetic non-executable adb placeholder')
foreach ($directory in $pathAdbDirectories) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $directory 'adb.exe'), 'synthetic PATH-only adb placeholder')
}
$originalLocalAppData = $env:LOCALAPPDATA
$originalPath = $env:PATH
try {
    $env:LOCALAPPDATA = $adbResolutionRoot
    $env:PATH = ($pathAdbDirectories -join [IO.Path]::PathSeparator) + [IO.Path]::PathSeparator + $originalPath
    $pathAdbCommands = @(Get-Command -Name 'adb' -CommandType Application -ErrorAction SilentlyContinue)
    Assert-True ($pathAdbCommands.Count -ge 2) 'regression fixture must expose multiple ADB executables through PATH'

    $multiplePathResult = Invoke-P3A6NativeAdb -Arguments @('get-state') -TimeoutMs 1000
    Assert-True ($multiplePathResult.StartFailed -eq $true -and $multiplePathResult.Rejected -ne $true) 'synthetic placeholder must not execute and unrelated PATH ADB copies must not cause allowlist rejection'
    $resolvedSdkAdbPath = & $module { Get-P3A6PinnedAdbPath }
    Assert-True ($resolvedSdkAdbPath -eq [IO.Path]::GetFullPath($sdkAdbPath)) 'native executor resolver must return the exact LOCALAPPDATA SDK adb.exe path'

    $missingSdkRoot = New-TestOutputRoot
    $env:LOCALAPPDATA = $missingSdkRoot
    $missingSdkResult = Invoke-P3A6NativeAdb -Arguments @('get-state') -TimeoutMs 1000
    Assert-True ($missingSdkResult.StartFailed -eq $true -and $missingSdkResult.ExecutableUnavailable -eq $true -and $missingSdkResult.Rejected -ne $true) 'missing pinned SDK adb.exe must fail closed without PATH fallback'
}
finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    $env:PATH = $originalPath
}
$passCount++

# Successful mock data is allowlisted; raw ADB output, serial and personal-looking stderr are not saved.
$privacyResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $response = & (Get-StandardResponder) $Arguments $TimeoutMs
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PROCESS_PROBE') { $response.Stdout = "123 com.picovr.quickcamera`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
    $response.Stderr = 'private.user@example.invalid /data/user/0/private-account'
    return $response
}.GetNewClosure()
$case = Invoke-TestRun $privacyResponder (New-Approval) $confirmation -TransportId '42'
Assert-True ($case.Result.status -eq 'COMPLETE') 'standard mock collection should complete'
Assert-StandardRunArgumentVectors $case.Calls '42'
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
$quotedProbeCalls = @($case.Calls | Where-Object { (Get-TestCommandKind -Arguments $_.Arguments) -in @('PROCESS_PROBE', 'FD_PROBE') })
Assert-True ($quotedProbeCalls.Count -ge 2) 'collector must pass generated process and FD probes as POSIX-quoted single ADB shell arguments'
Assert-True (@($case.Calls | Where-Object { -not $_.AllowedByNative }).Count -eq 0) 'mock responders must never return synthetic output for a vector rejected by the native allowlist'
$marker = Get-Content -LiteralPath $case.Result.marker_path -Raw | ConvertFrom-Json -AsHashtable
$actualHash = (Get-FileHash -LiteralPath $case.Result.archive_path -Algorithm SHA256).Hash.ToLowerInvariant()
Assert-True ($marker.archive_sha256 -eq $actualHash) 'final marker must bind the archive SHA-256'
$acl = Get-Acl -LiteralPath $case.Result.evidence_directory
Assert-True ($acl.AreAccessRulesProtected) 'evidence run folder ACL must block inherited access'
$passCount++

# The no-transport variant must retain one-element prefixes as arrays across every command construction.
$singleProcessResponder = {
    param([string[]]$Arguments, [int]$TimeoutMs)
    $response = & (Get-StandardResponder) $Arguments $TimeoutMs
    if ((Get-TestCommandKind -Arguments $Arguments) -eq 'PROCESS_PROBE') { $response.Stdout = "123 com.picovr.quickcamera`nP3A6`tPROCESS_STATUS`tOBSERVED`n" }
    return $response
}.GetNewClosure()
$case = Invoke-TestRun $singleProcessResponder (New-Approval) $confirmation
Assert-True ($case.Result.status -eq 'COMPLETE') "no-transport collection must pass every native allowlist vector (got $($case.Result.status))"
Assert-StandardRunArgumentVectors $case.Calls
$passCount++

$tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
foreach ($root in $script:CreatedOutputRoots) {
    $fullRoot = [IO.Path]::GetFullPath($root)
    if (-not $fullRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($fullRoot) -notmatch '^p3a6-inventory-tests-[0-9a-f]{32}$') {
        throw 'Refusing to clean an unexpected test output path'
    }
    if (Test-Path -LiteralPath $fullRoot) { [IO.Directory]::Delete($fullRoot, $true) }
}

Write-Output "P3-A6 M1 PowerShell mock collector checks: $passCount/28 PASS"
