Set-StrictMode -Version Latest

$script:P3A6Action = 'read-only-inventory'
$script:P3A6MaxDurationSeconds = 60
$script:P3A6MaxRecords = 200
$script:P3A6MaxCommandOutputChars = 262144
$script:P3A6RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

function Get-P3A6UtcNow {
    return [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}

function New-P3A6Field {
    param([string]$Status = 'NOT_OBSERVED', [string]$Method = '', [string]$Reason = '')
    return [ordered]@{
        status = $Status
        value = $null
        method = $Method
        observed_at_utc = $null
        build_identity = $null
        reason = $(if ($Reason) { $Reason } else { $null })
    }
}

function Invoke-P3A6GateCli {
    param(
        [AllowNull()][object]$Approval,
        [string]$Action,
        [AllowNull()][string]$OwnerConfirmation
    )

    try {
        $python = @(Get-Command -Name 'python' -CommandType Application -ErrorAction Stop)[0]
        $payload = [ordered]@{
            approval = $Approval
            action = $Action
            owner_confirmation = $OwnerConfirmation
        } | ConvertTo-Json -Depth 12 -Compress

        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $python.Source
        $startInfo.WorkingDirectory = $script:P3A6RepoRoot
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardInput = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.ArgumentList.Add('-m')
        $startInfo.ArgumentList.Add('pico.tools.p3a6_execution_gate_cli')

        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            return [pscustomobject]@{ allowed = $false; status = 'BLOCKED_GATE_UNAVAILABLE'; reason = 'Gate process did not start' }
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write($payload)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(5000)) {
            try { $process.Kill($true) } catch { }
            return [pscustomobject]@{ allowed = $false; status = 'BLOCKED_GATE_TIMEOUT'; reason = 'Gate check timed out' }
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $null = $stderrTask.GetAwaiter().GetResult()
        if ($stdout.Length -gt 4096) {
            return [pscustomobject]@{ allowed = $false; status = 'BLOCKED_GATE_INVALID_RESPONSE'; reason = 'Gate response exceeded limit' }
        }
        $decision = $stdout | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        if ($decision -isnot [System.Collections.IDictionary] -or $decision.allowed -isnot [bool]) {
            return [pscustomobject]@{ allowed = $false; status = 'BLOCKED_GATE_INVALID_RESPONSE'; reason = 'Gate response was invalid' }
        }
        return [pscustomobject]$decision
    }
    catch {
        return [pscustomobject]@{ allowed = $false; status = 'BLOCKED_GATE_UNAVAILABLE'; reason = 'Shared execution gate could not be evaluated' }
    }
}

function Test-P3A6OutputPath {
    param([string]$OutputRoot)

    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return [pscustomobject]@{ allowed = $false; full_path = $null; reason = 'LOCALAPPDATA is unavailable' }
    }
    try {
        $local = [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        $full = [IO.Path]::GetFullPath($OutputRoot)
        $prefix = $local + [IO.Path]::DirectorySeparatorChar
        if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{ allowed = $false; full_path = $full; reason = 'Evidence root must be inside LOCALAPPDATA' }
        }
        if ($full.StartsWith($script:P3A6RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{ allowed = $false; full_path = $full; reason = 'Evidence root cannot be inside the repository' }
        }
        $cursor = $full
        while ($cursor.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            if (Test-Path -LiteralPath $cursor) {
                $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
                if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    return [pscustomobject]@{ allowed = $false; full_path = $full; reason = 'Evidence path cannot traverse a reparse point' }
                }
            }
            $parent = [IO.Directory]::GetParent($cursor)
            if ($null -eq $parent) { break }
            $cursor = $parent.FullName
        }
        return [pscustomobject]@{ allowed = $true; full_path = $full; reason = $null }
    }
    catch {
        return [pscustomobject]@{ allowed = $false; full_path = $null; reason = 'Evidence root path is invalid' }
    }
}

function New-P3A6PrivateRunDirectory {
    param([string]$OutputRoot, [string]$RunId)

    $rootCheck = Test-P3A6OutputPath -OutputRoot $OutputRoot
    if (-not $rootCheck.allowed) { throw 'Evidence root rejected' }
    $fullRoot = $rootCheck.full_path
    if (Test-Path -LiteralPath $fullRoot) {
        $rootItem = Get-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
        if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Evidence root cannot be a reparse point' }
        if (-not $rootItem.PSIsContainer) { throw 'Evidence root must be a directory' }
    }
    else {
        $null = [IO.Directory]::CreateDirectory($fullRoot)
    }

    $runPath = Join-Path $fullRoot $RunId
    $ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $ownerSid) { throw 'Current user SID is unavailable' }
    $systemSid = [Security.Principal.SecurityIdentifier]::new([Security.Principal.WellKnownSidType]::LocalSystemSid, $null)
    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($ownerSid)
    $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $ownerRule = [Security.AccessControl.FileSystemAccessRule]::new(
        $ownerSid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $systemRule = [Security.AccessControl.FileSystemAccessRule]::new(
        $systemSid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($ownerRule)
    $security.AddAccessRule($systemRule)
    $null = [IO.Directory]::CreateDirectory($runPath)
    try { Set-Acl -LiteralPath $runPath -AclObject $security -ErrorAction Stop }
    catch {
        try { [IO.Directory]::Delete($runPath, $false) } catch { }
        throw 'Private evidence ACL could not be established'
    }
    return $runPath
}

function ConvertTo-P3A6PosixShellArgument {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)

    # ADB shell joins argv into a remote command string. Quote this one word for
    # the remote POSIX shell; never interpret data as printf or shell escapes.
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Test-P3A6AllowedAdbArguments {
    param([string[]]$Arguments)

    $offset = 0
    if ($Arguments.Count -gt 0 -and $Arguments[0] -ceq '-t') {
        if ($Arguments.Count -lt 3 -or $Arguments[1] -notmatch '^[1-9]\d{0,9}$') { return $false }
        $offset = 2
    }
    elseif ($Arguments.Count -gt 0 -and $Arguments[0] -ceq '-s') { return $false }
    if ($Arguments.Count -eq ($offset + 1) -and $Arguments[$offset] -ceq 'get-state') { return $true }
    if ($Arguments.Count -lt ($offset + 3) -or $Arguments[$offset] -cne 'shell') { return $false }
    if ($Arguments.Count -eq ($offset + 3) -and $Arguments[$offset + 1] -ceq 'getprop' -and $Arguments[$offset + 2] -cin @('ro.product.model', 'ro.build.fingerprint', 'ro.build.version.release')) { return $true }
    if ($Arguments.Count -eq ($offset + 3) -and $Arguments[$offset + 1] -ceq 'uname' -and $Arguments[$offset + 2] -ceq '-r') { return $true }
    if ($Arguments.Count -ne ($offset + 4) -or $Arguments[$offset + 1] -cne 'sh' -or $Arguments[$offset + 2] -cne '-c') { return $false }

    $shellCommand = [string]$Arguments[$offset + 3]
    if ($shellCommand -match "(?s)^'# pico-p3a6-process-probe\r?\nlimit=(\d{1,4})\r?\n") {
        $limit = [int]$Matches[1]
        $expected = ConvertTo-P3A6PosixShellArgument -Value (Get-P3A6ProcessProbeScript -ProcessBudget $limit)
        return $shellCommand -ceq $expected
    }
    if ($shellCommand -match "(?s)^'# pico-p3a6-fd-probe\r?\npid=(\d+)\r?\nlimit=(\d+)\r?\n") {
        $processId = [int]$Matches[1]
        $limit = [int]$Matches[2]
        $expected = ConvertTo-P3A6PosixShellArgument -Value (Get-P3A6ProbeScript -ProcessId $processId -RecordBudget $limit)
        return $shellCommand -ceq $expected
    }
    return $false
}

function Get-P3A6ProcessProbeScript {
    param([int]$ProcessBudget)
    $template = @'
# pico-p3a6-process-probe
limit=__LIMIT__
process_output=$(ps -A -o PID,NAME)
ps_status=$?
if [ "$ps_status" -ne 0 ] || [ -z "$process_output" ]; then
  printf 'P3A6\tPROCESS_STATUS\tUNAVAILABLE\n'
  exit 0
fi
printf '%s\n' "$process_output" | awk -v max="$limit" 'NR==1 { if (toupper($1)!="PID" || toupper($2)!="NAME") exit 3; next } tolower($2) ~ /(quickcamera|pvr)/ { print $1, $2; n++; if (n >= max) exit }'
filter_status=$?
if [ "$filter_status" -eq 0 ]; then
  printf 'P3A6\tPROCESS_STATUS\tOBSERVED\n'
else
  printf 'P3A6\tPROCESS_STATUS\tUNAVAILABLE\n'
fi
'@
    return $template.Replace('__LIMIT__', [string][Math]::Max(1, [Math]::Min(200, $ProcessBudget))).TrimEnd([char[]]@("`r", "`n"))
}

function Get-P3A6PinnedAdbPath {
    $localAppData = [Environment]::GetEnvironmentVariable('LOCALAPPDATA', 'Process')
    if ([string]::IsNullOrWhiteSpace($localAppData) -or -not [IO.Path]::IsPathFullyQualified($localAppData)) {
        return $null
    }

    try {
        $localAppDataPath = [IO.Path]::GetFullPath($localAppData)
        $adbPath = [IO.Path]::GetFullPath((Join-Path $localAppDataPath 'Android\Sdk\platform-tools\adb.exe'))
        $platformToolsPath = [IO.Path]::GetFullPath((Join-Path $localAppDataPath 'Android\Sdk\platform-tools'))
        $expectedPrefix = $platformToolsPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if (-not $adbPath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($adbPath) -cne 'adb.exe' -or
            -not [IO.File]::Exists($adbPath)) {
            return $null
        }

        return $adbPath
    }
    catch {
        return $null
    }
}

function Invoke-P3A6NativeAdb {
    param([string[]]$Arguments, [int]$TimeoutMs)

    try {
        if (-not (Test-P3A6AllowedAdbArguments -Arguments $Arguments)) {
            return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = ''; TimedOut = $false; StartFailed = $true; Rejected = $true }
        }
        $adbPath = Get-P3A6PinnedAdbPath
        if ([string]::IsNullOrWhiteSpace($adbPath)) {
            return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = ''; TimedOut = $false; StartFailed = $true; Rejected = $false; ExecutableUnavailable = $true }
        }
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $adbPath
        $startInfo.WorkingDirectory = $script:P3A6RepoRoot
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        foreach ($argument in $Arguments) { $startInfo.ArgumentList.Add([string]$argument) }

        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = ''; TimedOut = $false; StartFailed = $true }
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit([Math]::Max(1, $TimeoutMs))) {
            try { $process.Kill($true) } catch { }
            $null = $process.WaitForExit(1000)
            return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = ''; TimedOut = $true; StartFailed = $false }
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($stdout.Length -gt $script:P3A6MaxCommandOutputChars -or $stderr.Length -gt $script:P3A6MaxCommandOutputChars) {
            return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = ''; TimedOut = $false; StartFailed = $false; OutputLimit = $true }
        }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr; TimedOut = $false; StartFailed = $false }
    }
    catch {
        return [pscustomobject]@{ ExitCode = -1; Stdout = ''; Stderr = ''; TimedOut = $false; StartFailed = $true }
    }
}

function Add-P3A6Record {
    param($State, [System.Collections.IDictionary]$Record)
    if ($State.records.Count -ge $State.max_records) {
        $State.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'
        $State.stop_reason = 'Maximum evidence record count reached'
        $State.partial = $true
        return $false
    }
    $State.records.Add($Record)
    return $true
}

function Invoke-P3A6DeviceCommand {
    param(
        $State,
        [object[]]$Arguments,
        [scriptblock]$AdbExecutor,
        [object]$Approval,
        [string]$OwnerConfirmation,
        [string]$Action
    )

    $elapsed = ([DateTime]::UtcNow - $State.started_at).TotalSeconds
    if ($elapsed -ge $State.max_duration_seconds) {
        $State.stop_code = 'PARTIAL_TIMEOUT'
        $State.stop_reason = 'Approved duration limit reached before the next ADB command'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'TIMEOUT' }
    }
    if ($State.adb_command_count -ge $State.max_records -or $State.records.Count -ge $State.max_records) {
        $State.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'
        $State.stop_reason = 'Approved command or evidence record limit reached'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'LIMIT' }
    }
    $decision = Invoke-P3A6GateCli -Approval $Approval -Action $Action -OwnerConfirmation $OwnerConfirmation
    if (-not $decision.allowed) {
        $State.stop_code = [string]$decision.status
        $State.stop_reason = 'Execution gate denied the next ADB command'
        $State.partial = ($State.adb_command_count -gt 0)
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'GATE' }
    }
    $elapsed = ([DateTime]::UtcNow - $State.started_at).TotalSeconds
    $remainingMs = [int][Math]::Floor(($State.max_duration_seconds - $elapsed) * 1000)
    if ($remainingMs -le 0) {
        $State.stop_code = 'PARTIAL_TIMEOUT'
        $State.stop_reason = 'Approved duration limit reached before the next ADB command'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'TIMEOUT' }
    }

    $State.adb_command_count++
    try { $response = & $AdbExecutor ([string[]]$Arguments) $remainingMs }
    catch {
        $response = $null
    }
    if ($null -eq $response -or $null -eq $response.PSObject.Properties['ExitCode'] -or $null -eq $response.PSObject.Properties['Stdout'] -or $null -eq $response.PSObject.Properties['TimedOut']) {
        $State.stop_code = 'PARTIAL_ADB_ERROR'
        $State.stop_reason = 'ADB executor failed or returned an invalid result'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'ADB_ERROR' }
    }
    if ($response.TimedOut) {
        $State.stop_code = 'PARTIAL_TIMEOUT'
        $State.stop_reason = 'ADB command exceeded the remaining approved duration'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'TIMEOUT' }
    }
    if ($response.PSObject.Properties['OutputLimit'] -and $response.OutputLimit) {
        $State.stop_code = 'PARTIAL_OUTPUT_LIMIT'
        $State.stop_reason = 'ADB command output exceeded the collector limit'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'OUTPUT_LIMIT' }
    }
    if ($response.PSObject.Properties['StartFailed'] -and $response.StartFailed) {
        $State.stop_code = 'PARTIAL_ADB_ERROR'
        $State.stop_reason = 'ADB executable could not be started'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'ADB_ERROR' }
    }
    if ([int]$response.ExitCode -ne 0) {
        $stderr = [string]$response.Stderr
        if ($stderr -match '(?i)more than one device(?:/emulator)?') { $kind = 'MULTIPLE_DEVICES' }
        elseif ($stderr -match '(?i)permission denied|not permitted|access denied') { $kind = 'PERMISSION_DENIED' }
        else { $kind = 'UNAVAILABLE' }
        $State.stop_code = 'PARTIAL_ADB_ERROR'
        $State.stop_reason = 'ADB command returned a nonzero result'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = $kind }
    }
    $stdout = [string]$response.Stdout
    if ($stdout.Length -gt $script:P3A6MaxCommandOutputChars) {
        $State.stop_code = 'PARTIAL_OUTPUT_LIMIT'
        $State.stop_reason = 'ADB command output exceeded the collector limit'
        $State.partial = $true
        return [pscustomobject]@{ ok = $false; stdout = ''; error_kind = 'OUTPUT_LIMIT' }
    }
    return [pscustomobject]@{ ok = $true; stdout = $stdout; error_kind = $null }
}

function Set-P3A6FieldResult {
    param(
        $State,
        [string]$Name,
        [string]$Status,
        [string]$Method,
        [AllowNull()][object]$Value = $null,
        [string]$Reason = ''
    )
    $field = $State.evidence.fields[$Name]
    $field.status = $Status
    $field.value = $Value
    $field.method = $Method
    $field.observed_at_utc = Get-P3A6UtcNow
    $field.build_identity = $State.evidence.target.build_fingerprint
    $field.reason = $(if ($Reason) { $Reason } else { $null })
    if ($Status -ne 'OBSERVED') { $State.partial = $true }
    if ($Status -eq 'PERMISSION_DENIED') { $State.access_limitations.Add("${Name}:PERMISSION_DENIED") }
    $record = [ordered]@{
        kind = 'field'
        field = $Name
        status = $Status
        value = $Value
        method = $Method
        observed_at_utc = $field.observed_at_utc
        build_identity = $field.build_identity
        reason = $field.reason
    }
    $null = Add-P3A6Record -State $State -Record $record
}

function Get-P3A6ProbeScript {
    param([int]$ProcessId, [int]$RecordBudget)
    $template = @'
# pico-p3a6-fd-probe
pid=__PID__
limit=__LIMIT__
records=0
access_failed=0
seen_video=0
emit_data() {
  if [ "$records" -ge "$limit" ]; then return 1; fi
  case "$1" in
    FD) printf 'P3A6\tFD\t%s\t%s\n' "$2" "$3" ;;
    FDINFO_STATUS) printf 'P3A6\tFDINFO_STATUS\t%s\t%s\n' "$2" "$3" ;;
    FDINFO) printf 'P3A6\tFDINFO\t%s\t%s\t%s\n' "$2" "$3" "$4" ;;
    *) return 1 ;;
  esac
  records=$((records + 1))
  return 0
}
if [ ! -d "/proc/$pid/fd" ]; then printf 'P3A6\tSTATUS\tPROCESS_DISAPPEARED\n'; exit 0; fi
if ! command -v readlink >/dev/null 2>&1; then printf 'P3A6\tSTATUS\tREADLINK_UNAVAILABLE\n'; exit 0; fi
if [ ! -r "/proc/$pid/fd" ]; then printf 'P3A6\tSTATUS\tPROC_ACCESS_DENIED\n'; exit 0; fi
for link in /proc/$pid/fd/*; do
  [ -e "$link" ] || continue
  fd=${link##*/}
  target=$(readlink "$link" 2>/dev/null)
  readlink_rc=$?
  if [ "$readlink_rc" -ne 0 ]; then access_failed=1; break; fi
  case "$target" in
    /dev/video*)
      case "$target" in /dev/video[0-9]*) ;; *) continue ;; esac
      seen_video=1
      if ! emit_data FD "$fd" "$target"; then break; fi
      info="/proc/$pid/fdinfo/$fd"
      if [ ! -e "$info" ]; then
        emit_data FDINFO_STATUS "$fd" UNAVAILABLE || break
        continue
      fi
      if [ ! -r "$info" ]; then
        access_failed=1
        emit_data FDINFO_STATUS "$fd" PERMISSION_DENIED || break
        break
      fi
      info_count=0
      while IFS=: read -r key value; do
        value=${value# }
        case "$key" in
          pos|flags|mnt_id|ino)
            case "$key:$value" in
              pos:[0-9]*|flags:0x[0-9a-fA-F]*|flags:[0-7]*|mnt_id:[0-9]*|ino:[0-9]*)
                if emit_data FDINFO "$fd" "$key" "$value"; then info_count=$((info_count + 1)); else break; fi
                ;;
          esac
          ;;
        esac
      done < "$info"
      if [ "$info_count" -gt 0 ]; then
        emit_data FDINFO_STATUS "$fd" OBSERVED || break
      else
        emit_data FDINFO_STATUS "$fd" UNAVAILABLE || break
      fi
      ;;
  esac
  if [ "$access_failed" -ne 0 ]; then break; fi
done
if [ "$records" -ge "$limit" ]; then
  printf 'P3A6\tSTATUS\tRECORD_LIMIT_REACHED\n'
elif [ "$access_failed" -ne 0 ]; then
  printf 'P3A6\tSTATUS\tPARTIAL_ACCESS\n'
elif [ "$seen_video" -eq 0 ]; then
  printf 'P3A6\tSTATUS\tNO_CAMERA_FD\n'
else
  printf 'P3A6\tSTATUS\tOBSERVED\n'
fi
'@
    return $template.Replace('__PID__', [string]$ProcessId).Replace('__LIMIT__', [string][Math]::Max(1, $RecordBudget))
}

function Convert-P3A6ProbeOutput {
    param([string]$ProbeText)

    $fds = [ordered]@{}
    $status = $null
    foreach ($line in ($ProbeText -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parts = $line -split "`t", 0, 'SimpleMatch'
        if ($parts.Count -lt 3 -or $parts[0] -ne 'P3A6') { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
        switch ($parts[1]) {
            'FD' {
                if ($parts.Count -ne 4 -or $parts[2] -notmatch '^\d{1,6}$' -or $parts[3] -notmatch '^/dev/video\d+$') { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
                $fds[$parts[2]] = [ordered]@{ fd = [int]$parts[2]; node = $parts[3]; info_status = 'UNAVAILABLE'; info = [ordered]@{} }
            }
            'FDINFO' {
                if ($parts.Count -ne 5 -or -not $fds.Contains($parts[2]) -or $parts[3] -notin @('pos', 'flags', 'mnt_id', 'ino')) { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
                $value = $parts[4]
                $validValue = switch ($parts[3]) {
                    'pos' { $value -match '^\d{1,20}$' }
                    'flags' { $value -match '^(?:0x[0-9a-fA-F]{1,16}|0?[0-7]{1,22})$' }
                    'mnt_id' { $value -match '^\d{1,20}$' }
                    'ino' { $value -match '^\d{1,20}$' }
                }
                if (-not $validValue) { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
                $fds[$parts[2]].info[$parts[3]] = $value
            }
            'FDINFO_STATUS' {
                if ($parts.Count -ne 4 -or -not $fds.Contains($parts[2]) -or $parts[3] -notin @('OBSERVED', 'PERMISSION_DENIED', 'UNAVAILABLE')) { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
                $fds[$parts[2]].info_status = $parts[3]
            }
            'STATUS' {
                if ($parts.Count -ne 3 -or $parts[2] -notin @('PROCESS_DISAPPEARED', 'READLINK_UNAVAILABLE', 'PROC_ACCESS_DENIED', 'PARTIAL_ACCESS', 'NO_CAMERA_FD', 'RECORD_LIMIT_REACHED', 'OBSERVED')) { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
                $status = $parts[2]
            }
            default { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
        }
    }
    if (-not $status) { return [pscustomobject]@{ valid = $false; status = 'PROBE_PROTOCOL_ERROR'; fds = @{} } }
    return [pscustomobject]@{ valid = $true; status = $status; fds = $fds }
}

function Write-P3A6EvidencePackage {
    param($State)

    $State.evidence.ended_at_utc = Get-P3A6UtcNow
    $State.evidence.elapsed_seconds = [Math]::Round(([DateTime]::UtcNow - $State.started_at).TotalSeconds, 3)
    if ($State.stop_code) {
        $State.evidence.collection_status = if ($State.stop_code -like 'BLOCKED_*' -and $State.adb_command_count -le 2) { 'BLOCKED' } else { 'PARTIAL' }
        $State.evidence.stop_reason = $State.stop_code
    }
    elseif ($State.partial) {
        $State.evidence.collection_status = 'PARTIAL'
        $State.evidence.stop_reason = 'LIMITATION_OR_UNAVAILABLE_FIELD'
    }
    else {
        $State.evidence.collection_status = 'COMPLETE'
        $State.evidence.stop_reason = 'REQUESTED_INVENTORY_COMPLETE'
    }
    $State.evidence.adb_command_count = $State.adb_command_count
    $State.evidence.record_count = $State.records.Count
    $State.evidence.limits.observed_records = $State.records.Count
    $State.evidence.limits.adb_commands = $State.adb_command_count
    $State.evidence.records = @($State.records.ToArray())
    $State.evidence.access_limitations = @($State.access_limitations.ToArray())

    $stage = Join-Path $State.evidence_directory '.payload'
    $null = [IO.Directory]::CreateDirectory($stage)
    $jsonPath = Join-Path $stage 'evidence.json'
    $json = $State.evidence | ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText($jsonPath, $json, [Text.UTF8Encoding]::new($false))
    $archivePath = Join-Path $State.evidence_directory 'evidence.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($stage, $archivePath, [IO.Compression.CompressionLevel]::Optimal, $false)
    Remove-Item -LiteralPath $stage -Recurse -Force
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $marker = [ordered]@{
        schema = 'p3a6.private_inventory_final_marker.v1'
        record_kind = 'p3a6_read_only_inventory'
        archive = 'evidence.zip'
        archive_sha256 = $hash
        collection_status = $State.evidence.collection_status
        finalized_at_utc = Get-P3A6UtcNow
    }
    $markerTemp = Join-Path $State.evidence_directory 'final.marker.tmp'
    $markerPath = Join-Path $State.evidence_directory 'final.marker.json'
    [IO.File]::WriteAllText($markerTemp, ($marker | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($markerTemp, $markerPath)
    return [pscustomobject]@{
        status = $(if ($State.stop_code) { $State.stop_code } elseif ($State.access_limitations.Count -gt 0) { 'PARTIAL_PERMISSION_LIMITATIONS' } elseif ($State.partial) { 'PARTIAL_LIMITATIONS' } else { 'COMPLETE' })
        collection_status = $State.evidence.collection_status
        adb_command_count = $State.adb_command_count
        record_count = $State.records.Count
        evidence_directory = $State.evidence_directory
        archive_path = $archivePath
        marker_path = $markerPath
    }
}

function Invoke-P3A6Inventory {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$Approval,
        [AllowNull()][string]$OwnerConfirmation,
        [Parameter(Mandatory)][scriptblock]$AdbExecutor,
        [string]$OutputRoot = '',
        [string]$TransportId = '',
        [string]$Action = $script:P3A6Action,
        [ValidateRange(1, 600)][int]$MaxDurationSeconds = $script:P3A6MaxDurationSeconds,
        [ValidateRange(1, 10000)][int]$MaxRecords = $script:P3A6MaxRecords,
        [switch]$DryRun
    )

    if ($Action -ne $script:P3A6Action) {
        return [pscustomobject]@{ status = 'BLOCKED_SCOPE_MISMATCH'; collection_status = 'BLOCKED'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null }
    }
    if ($DryRun) {
        return [pscustomobject]@{ status = 'DRY_RUN'; collection_status = 'NOT_RUN'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null }
    }
    if ($TransportId -and $TransportId -notmatch '^[1-9]\d{0,9}$') {
        return [pscustomobject]@{ status = 'BLOCKED_INVALID_TRANSPORT'; collection_status = 'BLOCKED'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null }
    }
    if (-not $OutputRoot) {
        if (-not $env:LOCALAPPDATA) { return [pscustomobject]@{ status = 'BLOCKED_INVALID_EVIDENCE_ROOT'; collection_status = 'BLOCKED'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null } }
        $OutputRoot = Join-Path $env:LOCALAPPDATA 'PicoLHSync\private-evidence'
    }

    $gate = Invoke-P3A6GateCli -Approval $Approval -Action $Action -OwnerConfirmation $OwnerConfirmation
    if (-not $gate.allowed) {
        return [pscustomobject]@{ status = [string]$gate.status; collection_status = 'BLOCKED'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null }
    }
    if ([string]$Approval.approval_id -notmatch '^[A-Za-z0-9._-]{1,64}$') {
        return [pscustomobject]@{ status = 'BLOCKED_INVALID_APPROVAL_ID'; collection_status = 'BLOCKED'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null }
    }

    $maxDuration = [Math]::Min($script:P3A6MaxDurationSeconds, $MaxDurationSeconds)
    $maxRecordsEffective = [Math]::Min($script:P3A6MaxRecords, $MaxRecords)
    if ($Approval.max_duration_seconds -is [int] -or $Approval.max_duration_seconds -is [long]) {
        $maxDuration = [Math]::Min($maxDuration, [int]$Approval.max_duration_seconds)
    }
    if ($Approval.max_observations -is [int] -or $Approval.max_observations -is [long]) {
        $maxRecordsEffective = [Math]::Min($maxRecordsEffective, [int]$Approval.max_observations)
    }

    $runId = 'p3a6-' + [guid]::NewGuid().ToString('N')
    try { $runDirectory = New-P3A6PrivateRunDirectory -OutputRoot $OutputRoot -RunId $runId }
    catch { return [pscustomobject]@{ status = 'BLOCKED_INVALID_EVIDENCE_ROOT'; collection_status = 'BLOCKED'; adb_command_count = 0; record_count = 0; evidence_directory = $null; archive_path = $null; marker_path = $null } }

    $started = [DateTime]::UtcNow
    $fields = [ordered]@{
        product_model = New-P3A6Field -Method 'adb [ -t <selected transport-id> ] shell getprop ro.product.model'
        build_fingerprint = New-P3A6Field -Method 'adb [ -t <selected transport-id> ] shell getprop ro.build.fingerprint'
        android_release = New-P3A6Field -Method 'adb [ -t <selected transport-id> ] shell getprop ro.build.version.release'
        kernel_release = New-P3A6Field -Method 'adb [ -t <selected transport-id> ] shell uname -r'
        process_inventory = New-P3A6Field -Method 'adb [ -t <selected transport-id> ] shell sh -c <ps PID,NAME filtered to QuickCamera/PVR>'
    }
    $evidence = [ordered]@{
        schema = 'p3a6.private_inventory_evidence.v1'
        record_kind = 'p3a6_read_only_inventory'
        collector = [ordered]@{
            version = 'P3-A6-M1-v1'
            powershell_version = $PSVersionTable.PSVersion.ToString()
            source_sha256 = [ordered]@{
                entry = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'collect_p3a6_inventory.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()
                module = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'P3A6Inventory.psm1') -Algorithm SHA256).Hash.ToLowerInvariant()
                gate_cli = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'p3a6_execution_gate_cli.py') -Algorithm SHA256).Hash.ToLowerInvariant()
                gate = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'p3a6_execution_gate.py') -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
        run_id = $runId
        approval_id = [string]$Approval.approval_id
        action = $script:P3A6Action
        target = [ordered]@{ product = 'Pico 4 Pro'; build_fingerprint = $null; android_release = $null; kernel_release = $null }
        device_selection = [ordered]@{
            method = $(if ($TransportId) { 'adb -t <selected transport-id> get-state' } else { 'adb get-state; ambiguous transports are rejected by ADB' })
            serial_requested = $false
            transport_id_persisted = $false
        }
        collection_status = 'IN_PROGRESS'
        stop_reason = $null
        started_at_utc = $started.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
        ended_at_utc = $null
        elapsed_seconds = $null
        limits = [ordered]@{ max_duration_seconds = $maxDuration; max_records = $maxRecordsEffective; observed_records = 0; adb_commands = 0 }
        fields = $fields
        records = @()
        access_limitations = @()
        privacy = [ordered]@{
            serial_collected = $false
            account_data_collected = $false
            wifi_or_bluetooth_identifiers_collected = $false
            image_collected = $false
            video_collected = $false
            full_system_logs_collected = $false
        }
        gates = [ordered]@{
            exact_time = $false
            mapping_verified = $false
            pose_verified = $false
            shared_buffer_identity_verified = $false
            frame_meta_bridge_verified = $false
            live_lighthouse_correction_allowed = $false
            physical_event_verified = $false
        }
    }
    $state = @{
        evidence = $evidence
        evidence_directory = $runDirectory
        started_at = $started
        max_duration_seconds = $maxDuration
        max_records = $maxRecordsEffective
        adb_command_count = 0
        records = [System.Collections.Generic.List[object]]::new()
        access_limitations = [System.Collections.Generic.List[string]]::new()
        partial = $false
        stop_code = $null
        stop_reason = $null
    }

    try {
        $prefix = if ($TransportId) { @('-t', $TransportId, 'shell') } else { @('shell') }
        $stateArgs = if ($TransportId) { @('-t', $TransportId, 'get-state') } else { @('get-state') }
        $deviceResult = Invoke-P3A6DeviceCommand -State $state -Arguments $stateArgs -AdbExecutor $AdbExecutor -Approval $Approval -OwnerConfirmation $OwnerConfirmation -Action $Action
        if (-not $deviceResult.ok) {
            if ($deviceResult.error_kind -ne 'GATE') {
                $state.stop_code = switch ($deviceResult.error_kind) {
                    'MULTIPLE_DEVICES' { 'BLOCKED_MULTIPLE_DEVICES' }
                    default { if ($TransportId) { 'BLOCKED_TRANSPORT_NOT_FOUND' } else { 'BLOCKED_ADB_DEVICE_STATE' } }
                }
            }
            $state.stop_reason = 'ADB did not resolve one ready transport; raw error output discarded'
            $state.partial = $true
        }
        else {
            $stateLines = @($deviceResult.stdout -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            $selected = if ($stateLines.Count -eq 1 -and $stateLines[0] -ceq 'device') {
                [pscustomobject]@{ status = 'SELECTED'; transport_id = $TransportId }
            } else {
                [pscustomobject]@{ status = 'BLOCKED_DEVICE_NOT_READY'; transport_id = $null }
            }
            if ($selected.status -ne 'SELECTED') {
                $state.stop_code = $selected.status
                $state.stop_reason = 'ADB transport state was not exactly device'
            }
            else {
                $modelCall = Invoke-P3A6DeviceCommand -State $state -Arguments ($prefix + @('getprop', 'ro.product.model')) -AdbExecutor $AdbExecutor -Approval $Approval -OwnerConfirmation $OwnerConfirmation -Action $Action
                $modelMethod = 'adb [ -t <selected transport-id> ] shell getprop ro.product.model'
                if (-not $modelCall.ok) {
                    $status = if ($modelCall.error_kind -eq 'PERMISSION_DENIED') { 'PERMISSION_DENIED' } else { 'UNAVAILABLE' }
                    Set-P3A6FieldResult -State $state -Name 'product_model' -Status $status -Method $modelMethod -Reason $modelCall.error_kind
                    $state.stop_code = if ($state.stop_code) { $state.stop_code } else { 'PARTIAL_ADB_ERROR' }
                }
                elseif ((($modelCall.stdout -split "`r?`n" | Where-Object { $_ -ne '' }) -join '') -ceq 'Pico 4 Pro') {
                    Set-P3A6FieldResult -State $state -Name 'product_model' -Status 'OBSERVED' -Method $modelMethod -Value 'Pico 4 Pro'
                }
                else {
                    Set-P3A6FieldResult -State $state -Name 'product_model' -Status 'UNAVAILABLE' -Method $modelMethod -Reason 'UNEXPECTED_DEVICE_MODEL'
                    $state.stop_code = 'BLOCKED_UNEXPECTED_DEVICE'
                    $state.stop_reason = 'Target model did not match Pico 4 Pro; returned value discarded'
                }

                if (-not $state.stop_code) {
                    $propertySpecs = @(
                        @{ name = 'build_fingerprint'; adb = @('getprop', 'ro.build.fingerprint'); method = 'adb -t <selected transport-id> shell getprop ro.build.fingerprint'; pattern = '^[A-Za-z0-9._/:+-]{1,256}$' },
                        @{ name = 'android_release'; adb = @('getprop', 'ro.build.version.release'); method = 'adb -t <selected transport-id> shell getprop ro.build.version.release'; pattern = '^[0-9]+(?:\.[0-9]+){0,3}[A-Za-z0-9._+-]{0,32}$' },
                        @{ name = 'kernel_release'; adb = @('uname', '-r'); method = 'adb -t <selected transport-id> shell uname -r'; pattern = '^[A-Za-z0-9._:+-]{1,128}$' }
                    )
                    foreach ($spec in $propertySpecs) {
                        if ($state.stop_code) { break }
                        $result = Invoke-P3A6DeviceCommand -State $state -Arguments ($prefix + $spec.adb) -AdbExecutor $AdbExecutor -Approval $Approval -OwnerConfirmation $OwnerConfirmation -Action $Action
                        if (-not $result.ok) {
                            $status = if ($result.error_kind -eq 'PERMISSION_DENIED') { 'PERMISSION_DENIED' } else { 'UNAVAILABLE' }
                            Set-P3A6FieldResult -State $state -Name $spec.name -Status $status -Method $spec.method -Reason $result.error_kind
                            if (-not $state.stop_code) { $state.stop_code = 'PARTIAL_ADB_ERROR' }
                            continue
                        }
                        $lines = @($result.stdout -split "`r?`n" | Where-Object { $_ -ne '' })
                        if ($lines.Count -ne 1 -or $lines[0] -notmatch $spec.pattern) {
                            Set-P3A6FieldResult -State $state -Name $spec.name -Status 'UNAVAILABLE' -Method $spec.method -Reason 'EMPTY_OR_INVALID_ALLOWLISTED_VALUE'
                            if ($lines.Count -gt 1) {
                                $state.stop_code = 'PARTIAL_UNEXPECTED_OUTPUT'
                                $state.stop_reason = 'Allowlisted field returned an unexpected multi-line value; output discarded'
                            }
                            continue
                        }
                        Set-P3A6FieldResult -State $state -Name $spec.name -Status 'OBSERVED' -Method $spec.method -Value $lines[0]
                        if ($spec.name -eq 'build_fingerprint') {
                            $state.evidence.target.build_fingerprint = $lines[0]
                            foreach ($knownField in $state.evidence.fields.Values) {
                                if ($knownField.observed_at_utc) { $knownField.build_identity = $lines[0] }
                            }
                            foreach ($knownRecord in $state.records) { $knownRecord.build_identity = $lines[0] }
                        }
                        if ($spec.name -eq 'android_release') { $state.evidence.target.android_release = $lines[0] }
                        if ($spec.name -eq 'kernel_release') { $state.evidence.target.kernel_release = $lines[0] }
                    }
                }

                if (-not $state.stop_code -and $state.records.Count -ge ($maxRecordsEffective - 1)) {
                    $state.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'
                    $state.stop_reason = 'No approved record budget remains for process inventory'
                    $state.partial = $true
                }

                if (-not $state.stop_code) {
                    $processCandidateLimit = [Math]::Min(200, $maxRecordsEffective - $state.records.Count - 1)
                    $processCommand = Get-P3A6ProcessProbeScript -ProcessBudget $processCandidateLimit
                    $processMethod = 'adb [ -t <selected transport-id> ] shell sh -c <ps PID,NAME filtered to QuickCamera/PVR>'
                    $quotedProcessCommand = ConvertTo-P3A6PosixShellArgument -Value $processCommand
                    $processCall = Invoke-P3A6DeviceCommand -State $state -Arguments ($prefix + @('sh', '-c', $quotedProcessCommand)) -AdbExecutor $AdbExecutor -Approval $Approval -OwnerConfirmation $OwnerConfirmation -Action $Action
                    if (-not $processCall.ok) {
                        $status = if ($processCall.error_kind -eq 'PERMISSION_DENIED') { 'PERMISSION_DENIED' } else { 'UNAVAILABLE' }
                        Set-P3A6FieldResult -State $state -Name 'process_inventory' -Status $status -Method $processMethod -Reason $processCall.error_kind
                        if (-not $state.stop_code) { $state.stop_code = 'PARTIAL_ADB_ERROR' }
                        if ($status -eq 'PERMISSION_DENIED') { $state.access_limitations.Add('process_inventory:PERMISSION_DENIED') }
                    }
                    else {
                        $processes = [System.Collections.Generic.List[object]]::new()
                        $parseFailed = $false
                        foreach ($line in ($processCall.stdout -split "`r?`n")) {
                            if ([string]::IsNullOrWhiteSpace($line)) { continue }
                            if ($line -ceq "P3A6`tPROCESS_STATUS`tOBSERVED") { continue }
                            if ($line -ceq "P3A6`tPROCESS_STATUS`tUNAVAILABLE") { $parseFailed = $true; continue }
                            if ($line -notmatch '^\s*(\d{1,10})\s+([A-Za-z0-9_.@-]{1,256})\s*$') { $parseFailed = $true; break }
                            $pidValue = [int64]$Matches[1]
                            $nameValue = $Matches[2]
                            if ($nameValue -match '(?i)quickcamera|pvr') { $processes.Add([pscustomobject]@{ pid = $pidValue; name = $nameValue }) }
                        }
                        if ($parseFailed -or $processCall.stdout -notmatch '(?m)^P3A6\tPROCESS_STATUS\tOBSERVED\r?$') {
                            Set-P3A6FieldResult -State $state -Name 'process_inventory' -Status 'UNAVAILABLE' -Method $processMethod -Reason 'UNEXPECTED_PROCESS_LIST_FORMAT'
                            $state.stop_code = 'PARTIAL_UNEXPECTED_OUTPUT'
                        }
                        else {
                            $processStatus = 'OBSERVED'
                            Set-P3A6FieldResult -State $state -Name 'process_inventory' -Status $processStatus -Method $processMethod -Value $processes.Count
                            foreach ($proc in $processes) {
                                if ($state.records.Count -ge $maxRecordsEffective) {
                                    $state.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'
                                    $state.partial = $true
                                    break
                                }
                                $processRecord = [ordered]@{
                                    kind = 'process'
                                    status = 'OBSERVED'
                                    process_name = $proc.name
                                    pid = $proc.pid
                                    method = $processMethod
                                    observed_at_utc = Get-P3A6UtcNow
                                    build_identity = $state.evidence.target.build_fingerprint
                                }
                                if (-not (Add-P3A6Record -State $state -Record $processRecord)) { break }

                                $remaining = $maxRecordsEffective - $state.records.Count
                                if ($remaining -le 0) { $state.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'; $state.partial = $true; break }
                                $probeScript = Get-P3A6ProbeScript -ProcessId ([int]$proc.pid) -RecordBudget $remaining
                                $probeMethod = 'adb [ -t <selected transport-id> ] shell sh -c <allowlisted /proc/<pid>/fd and fdinfo probe>'
                                $quotedProbeScript = ConvertTo-P3A6PosixShellArgument -Value $probeScript
                                $probeCall = Invoke-P3A6DeviceCommand -State $state -Arguments ($prefix + @('sh', '-c', $quotedProbeScript)) -AdbExecutor $AdbExecutor -Approval $Approval -OwnerConfirmation $OwnerConfirmation -Action $Action
                                if (-not $probeCall.ok) {
                                    $status = if ($probeCall.error_kind -eq 'PERMISSION_DENIED') { 'PERMISSION_DENIED' } else { 'UNAVAILABLE' }
                                    $fdRecord = [ordered]@{ kind = 'fd_inventory'; status = $status; reason = $probeCall.error_kind; process_name = $proc.name; pid = $proc.pid; method = $probeMethod; observed_at_utc = Get-P3A6UtcNow; build_identity = $state.evidence.target.build_fingerprint }
                                    $null = Add-P3A6Record -State $state -Record $fdRecord
                                    if ($status -eq 'PERMISSION_DENIED') {
                                        $state.access_limitations.Add("proc_fd:$($proc.pid):PERMISSION_DENIED")
                                        $state.stop_code = 'PARTIAL_PERMISSION_DENIED'
                                        $state.stop_reason = 'ADB reported a permission denial while reading process descriptors'
                                    }
                                    $state.partial = $true
                                    if ($state.stop_code) { break }
                                    continue
                                }
                                $parsedProbe = Convert-P3A6ProbeOutput -ProbeText $probeCall.stdout
                                if (-not $parsedProbe.valid) {
                                    $state.stop_code = 'PARTIAL_PROBE_PROTOCOL_ERROR'
                                    $state.partial = $true
                                    break
                                }
                                $fdStatus = switch ($parsedProbe.status) {
                                    'PROCESS_DISAPPEARED' { 'UNAVAILABLE' }
                                    'PROC_ACCESS_DENIED' { 'PERMISSION_DENIED' }
                                    'READLINK_UNAVAILABLE' { 'UNAVAILABLE' }
                                    'PARTIAL_ACCESS' { 'UNAVAILABLE' }
                                    default { 'OBSERVED' }
                                }
                                $fdRecord = [ordered]@{
                                    kind = 'fd_inventory'
                                    status = $fdStatus
                                    reason = $parsedProbe.status
                                    process_name = $proc.name
                                    pid = $proc.pid
                                    method = $probeMethod
                                    observed_at_utc = Get-P3A6UtcNow
                                    build_identity = $state.evidence.target.build_fingerprint
                                }
                                if (-not (Add-P3A6Record -State $state -Record $fdRecord)) { break }
                                if ($fdStatus -ne 'OBSERVED') { $state.partial = $true }
                                if ($parsedProbe.status -eq 'PROC_ACCESS_DENIED' -or $parsedProbe.status -eq 'PARTIAL_ACCESS') {
                                    $state.access_limitations.Add("proc_fd:$($proc.pid):$($parsedProbe.status)")
                                }
                                if ($parsedProbe.status -eq 'RECORD_LIMIT_REACHED') { $state.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'; $state.partial = $true }

                                foreach ($fdKey in @($parsedProbe.fds.Keys)) {
                                    if ($state.records.Count -ge $maxRecordsEffective) { $state.stop_code = 'PARTIAL_RECORD_LIMIT_REACHED'; $state.partial = $true; break }
                                    $parsedFd = $parsedProbe.fds[$fdKey]
                                    $fdinfoFields = [ordered]@{}
                                    foreach ($key in @('pos', 'flags', 'mnt_id', 'ino')) {
                                        $keyStatus = if ($parsedFd.info_status -eq 'PERMISSION_DENIED') { 'PERMISSION_DENIED' } elseif ($parsedFd.info.Contains($key)) { 'OBSERVED' } else { 'UNAVAILABLE' }
                                        $keyValue = if ($parsedFd.info.Contains($key)) { $parsedFd.info[$key] } else { $null }
                                        $fdinfoFields[$key] = [ordered]@{ status = $keyStatus; value = $keyValue }
                                    }
                                    $videoRecord = [ordered]@{
                                        kind = 'video_fd'
                                        status = 'OBSERVED'
                                        association = 'NOT_ATTRIBUTED_TO_VIDEOQUEUEUTIL_IOCTL'
                                        process_name = $proc.name
                                        pid = $proc.pid
                                        fd = $parsedFd.fd
                                        node = $parsedFd.node
                                        fdinfo = [ordered]@{ status = $parsedFd.info_status; fields = $fdinfoFields }
                                        method = $probeMethod
                                        observed_at_utc = Get-P3A6UtcNow
                                        build_identity = $state.evidence.target.build_fingerprint
                                    }
                                    $null = Add-P3A6Record -State $state -Record $videoRecord
                                    if ($parsedFd.info_status -eq 'PERMISSION_DENIED') {
                                        $state.partial = $true
                                        $state.access_limitations.Add("fdinfo:$($proc.pid):$($parsedFd.fd):PERMISSION_DENIED")
                                    }
                                    elseif ($parsedFd.info_status -ne 'OBSERVED') { $state.partial = $true }
                                }
                                $fdinfoDenied = @($parsedProbe.fds.Values | Where-Object { $_.info_status -eq 'PERMISSION_DENIED' }).Count -gt 0
                                if ($fdinfoDenied -or $parsedProbe.status -eq 'PROC_ACCESS_DENIED') {
                                    $state.stop_code = 'PARTIAL_PERMISSION_DENIED'
                                    $state.stop_reason = 'Access to process descriptors or camera fdinfo was denied'
                                }
                                elseif ($parsedProbe.status -eq 'PARTIAL_ACCESS') {
                                    $state.stop_code = 'PARTIAL_ACCESS_LIMITATION'
                                    $state.stop_reason = 'One or more descriptor links could not be read'
                                }
                                if ($state.stop_code) { break }
                            }
                        }
                    }
                }
            }
        }
    }
    catch {
        if (-not $state.stop_code) { $state.stop_code = 'PARTIAL_COLLECTOR_ERROR' }
        $state.stop_reason = 'Collector stopped after an internal error; raw exception was discarded'
        $state.partial = $true
    }

    try { return Write-P3A6EvidencePackage -State $state }
    catch {
        return [pscustomobject]@{ status = 'BLOCKED_EVIDENCE_WRITE_FAILED'; collection_status = 'BLOCKED'; adb_command_count = $state.adb_command_count; record_count = $state.records.Count; evidence_directory = $runDirectory; archive_path = $null; marker_path = $null }
    }
}

Export-ModuleMember -Function Invoke-P3A6Inventory, Invoke-P3A6NativeAdb
