Set-StrictMode -Version Latest

$script:P3A6M2Action = 'read-only-camera-node-metadata'
$script:P3A6M2MaxDurationSeconds = 30
$script:P3A6M2MaxObservations = 40
$script:P3A6M2MaxNodesPerSource = 16
$script:P3A6M2MaxCommandOutputBytes = 65536
$script:P3A6M2RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$script:P3A6M2Identity = [ordered]@{
    'ro.product.model' = 'A8110'
    'ro.product.device' = 'PICOA8110'
    'ro.product.name' = 'Phoenix_ovs'
    'ro.product.manufacturer' = 'Pico'
}
$script:P3A6M2SafetyFlags = [ordered]@{
    exact_time = $false; mapping_verified = $false; pose_verified = $false
    shared_buffer_identity_verified = $false; frame_meta_bridge_verified = $false
    live_lighthouse_correction_allowed = $false; physical_event_verified = $false
}

$script:P3A6M2SysfsTemplate = @'
LC_ALL=C
export LC_ALL
root='/sys/class/video4linux'
limit=@@LIMIT@@
count=0
found=0
has_observed=0
has_denied=0
field_status=ATTRIBUTE_MISSING
field_value=''
if [ ! -d "$root" ]; then printf 'P3A6M2\tSYSFS_SOURCE\tUNAVAILABLE\n'; exit 0; fi
if [ ! -r "$root" ]; then printf 'P3A6M2\tSYSFS_SOURCE\tPERMISSION_DENIED\n'; exit 0; fi
read_field() {
  path=$1
  kind=$2
  field_status=ATTRIBUTE_MISSING
  field_value=''
  parent=${path%/*}
  if [ ! -d "$parent" ] || [ ! -r "$parent" ] || [ ! -x "$parent" ]; then field_status=PERMISSION_DENIED; return; fi
  case "$kind" in
    name) set -- "$parent"/[n]ame ;;
    index) set -- "$parent"/[i]ndex ;;
    dev) set -- "$parent"/[d]ev ;;
    *) field_status=INVALID; return ;;
  esac
  candidate=$1
  if [ "$candidate" != "$parent/$kind" ]; then field_status=ATTRIBUTE_MISSING; return; fi
  path=$candidate
  if [ ! -e "$path" ]; then
    if [ -L "$path" ]; then field_status=INVALID; else field_status=PERMISSION_DENIED; fi
    return
  fi
  if [ ! -r "$path" ]; then field_status=PERMISSION_DENIED; return; fi
  { exec 3<"$path"; } 2>/dev/null || { field_status=PERMISSION_DENIED; return; }
  IFS= read -r field_value <&3
  first_rc=$?
  extra=''
  IFS= read -r extra <&3
  second_rc=$?
  exec 3<&-
  if { [ "$first_rc" -ne 0 ] && [ -z "$field_value" ]; } || [ "$second_rc" -eq 0 ] || [ -n "$extra" ]; then
    field_status=INVALID; field_value=''; return
  fi
  case "$kind" in
    index)
      case "$field_value" in ''|*[!0-9]*) field_status=INVALID; field_value=''; return ;; esac
      [ "${#field_value}" -le 10 ] || { field_status=INVALID; field_value=''; return; }
      ;;
    dev)
      case "$field_value" in *:*) left=${field_value%%:*}; right=${field_value#*:} ;; *) field_status=INVALID; field_value=''; return ;; esac
      case "$left$right" in ''|*[!0-9]*) field_status=INVALID; field_value=''; return ;; esac
      [ "${#left}" -le 10 ] && [ "${#right}" -le 10 ] || { field_status=INVALID; field_value=''; return; }
      ;;
    name)
      [ "${#field_value}" -ge 1 ] && [ "${#field_value}" -le 96 ] || { field_status=INVALID; field_value=''; return; }
      case "$field_value" in *[!A-Za-z0-9_.:+\ -]*) field_status=INVALID; field_value=''; return ;; esac
      ;;
  esac
  field_status=OBSERVED
}
for entry in "$root"/video[0-9]*; do
  [ -e "$entry" ] || [ -L "$entry" ] || continue
  base=${entry##*/}
  suffix=${base#video}
  case "$suffix" in ''|*[!0-9]*) continue ;; esac
  found=1
  count=$((count + 1))
  if [ "$count" -gt "$limit" ]; then
    printf 'P3A6M2\tSYSFS_SOURCE\tLIMIT_REACHED\n'
    exit 0
  fi
  if [ ! -d "$entry" ]; then
    printf 'P3A6M2\tSYSFS_NODE\tvideo%s\tname\tINVALID\t\n' "$suffix"
    printf 'P3A6M2\tSYSFS_NODE\tvideo%s\tindex\tINVALID\t\n' "$suffix"
    printf 'P3A6M2\tSYSFS_NODE\tvideo%s\tdev\tINVALID\t\n' "$suffix"
    continue
  fi
  read_field "$entry/name" name
  [ "$field_status" = OBSERVED ] && has_observed=1
  [ "$field_status" = PERMISSION_DENIED ] && has_denied=1
  printf 'P3A6M2\tSYSFS_NODE\tvideo%s\tname\t%s\t%s\n' "$suffix" "$field_status" "$field_value"
  read_field "$entry/index" index
  [ "$field_status" = OBSERVED ] && has_observed=1
  [ "$field_status" = PERMISSION_DENIED ] && has_denied=1
  printf 'P3A6M2\tSYSFS_NODE\tvideo%s\tindex\t%s\t%s\n' "$suffix" "$field_status" "$field_value"
  read_field "$entry/dev" dev
  [ "$field_status" = OBSERVED ] && has_observed=1
  [ "$field_status" = PERMISSION_DENIED ] && has_denied=1
  printf 'P3A6M2\tSYSFS_NODE\tvideo%s\tdev\t%s\t%s\n' "$suffix" "$field_status" "$field_value"
done
if [ ! -d "$root" ]; then printf 'P3A6M2\tSYSFS_SOURCE\tUNAVAILABLE\n'; exit 0; fi
if [ ! -r "$root" ]; then printf 'P3A6M2\tSYSFS_SOURCE\tPERMISSION_DENIED\n'; exit 0; fi
if [ "$found" -eq 0 ]; then printf 'P3A6M2\tSYSFS_SOURCE\tNOT_OBSERVED\n'
elif [ "$has_observed" -eq 1 ]; then printf 'P3A6M2\tSYSFS_SOURCE\tOBSERVED\n'
elif [ "$has_denied" -eq 1 ]; then printf 'P3A6M2\tSYSFS_SOURCE\tPERMISSION_DENIED\n'
else printf 'P3A6M2\tSYSFS_SOURCE\tUNAVAILABLE\n'; fi
'@

$script:P3A6M2DevTemplate = @'
LC_ALL=C
export LC_ALL
root='/dev'
limit=@@LIMIT@@
count=0
found=0
has_observed=0
if [ ! -d "$root" ]; then printf 'P3A6M2\tDEV_SOURCE\tUNAVAILABLE\n'; exit 0; fi
if [ ! -r "$root" ]; then printf 'P3A6M2\tDEV_SOURCE\tPERMISSION_DENIED\n'; exit 0; fi
for entry in "$root"/video[0-9]*; do
  [ -e "$entry" ] || [ -L "$entry" ] || continue
  base=${entry##*/}
  suffix=${base#video}
  case "$suffix" in ''|*[!0-9]*) continue ;; esac
  found=1
  count=$((count + 1))
  if [ "$count" -gt "$limit" ]; then
    printf 'P3A6M2\tDEV_SOURCE\tLIMIT_REACHED\n'
    exit 0
  fi
  if [ -L "$entry" ]; then
    printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tSYMLINK_EXCLUDED\t\t\t\t\n' "$suffix"
    continue
  fi
  if [ ! -c "$entry" ]; then
    printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tUNEXPECTED_TYPE\t\t\t\t\n' "$suffix"
    continue
  fi
  listing=$(ls -ldn "$entry" 2>/dev/null) || {
    printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_FAILED\t\t\t\t\n' "$suffix"
    continue
  }
  case "$listing" in *'
'*)
    printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_MULTILINE\t\t\t\t\n' "$suffix"
    continue
    ;;
  esac
  case "$listing" in *" $entry") ;; *)
    printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"
    continue
    ;;
  esac
  set -f
  set -- $listing
  mode=${1-}
  links=${2-}
  uid=${3-}
  gid=${4-}
  major=${5-}
  minor=${6-}
  case "$mode" in c?????????) ;; *) printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"; continue ;; esac
  case "$mode" in c[rwxstST-][rwxstST-][rwxstST-][rwxstST-][rwxstST-][rwxstST-][rwxstST-][rwxstST-][rwxstST-]) ;; *) printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"; continue ;; esac
  case "$links$uid$gid" in ''|*[!0-9]*) printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"; continue ;; esac
  case "$major" in *,) major=${major%,} ;; *) printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"; continue ;; esac
  case "$major$minor" in ''|*[!0-9]*) printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"; continue ;; esac
  [ "${#uid}" -le 10 ] && [ "${#gid}" -le 10 ] && [ "${#major}" -le 10 ] && [ "${#minor}" -le 10 ] || {
    printf 'P3A6M2\tDEV_NODE\tvideo%s\tUNAVAILABLE\tLS_INCOMPATIBLE\t\t\t\t\n' "$suffix"
    continue
  }
  printf 'P3A6M2\tDEV_NODE\tvideo%s\tOBSERVED\tOK\t%s\t%s\t%s\t%s:%s\n' "$suffix" "$mode" "$uid" "$gid" "$major" "$minor"
  has_observed=1
done
if [ ! -d "$root" ]; then printf 'P3A6M2\tDEV_SOURCE\tUNAVAILABLE\n'; exit 0; fi
if [ ! -r "$root" ]; then printf 'P3A6M2\tDEV_SOURCE\tPERMISSION_DENIED\n'; exit 0; fi
if [ "$found" -eq 0 ]; then printf 'P3A6M2\tDEV_SOURCE\tNOT_OBSERVED\n'
elif [ "$has_observed" -eq 1 ]; then printf 'P3A6M2\tDEV_SOURCE\tOBSERVED\n'
else printf 'P3A6M2\tDEV_SOURCE\tUNAVAILABLE\n'; fi
'@

function Get-P3A6M2UtcNow { [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ') }

function Get-P3A6M2PinnedAdbPath {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { return $null }
    return [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'))
}

function Get-P3A6M2ProbeScript {
    [CmdletBinding()]
    param([ValidateSet('sysfs','dev')][string]$Source, [ValidateRange(1,16)][int]$NodeLimit = 16)
    $template = if ($Source -ceq 'sysfs') { $script:P3A6M2SysfsTemplate } else { $script:P3A6M2DevTemplate }
    $normalized = $template.Replace("`r`n", "`n").Replace("`r", "`n")
    return $normalized.Replace('@@LIMIT@@', [string]$NodeLimit).TrimStart("`r","`n").TrimEnd("`r","`n") + "`n"
}

function Get-P3A6M2TextSha256 {
    param([Parameter(Mandatory)][string]$Text)
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
    $hash = [Security.Cryptography.SHA256]::HashData($bytes)
    return [Convert]::ToHexString($hash).ToLowerInvariant()
}

function Get-P3A6M2NodeCorrelations {
    [CmdletBinding()]
    param([AllowEmptyCollection()][object[]]$SysfsNodes=@(),[AllowEmptyCollection()][object[]]$DevNodes=@())
    $majorMap=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    $deviceMap=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    $normalizeDecimal={
        param([string]$Value)
        $trimmed=$Value.TrimStart('0')
        if ($trimmed.Length -eq 0) { return '0' }
        return $trimmed
    }
    $ensureGroup={
        param([Collections.Generic.Dictionary[string,object]]$Map,[string]$Key,[string]$Major)
        if (-not $Map.ContainsKey($Key)) {
            $Map[$Key]=[pscustomobject]@{major=$Major;sysfs_node_ids=[Collections.Generic.List[string]]::new();dev_node_ids=[Collections.Generic.List[string]]::new()}
        }
        return $Map[$Key]
    }
    foreach ($node in $SysfsNodes) {
        if ([string]$node.node_id -cnotmatch '^video[0-9]{1,10}$' -or [string]$node.dev -cnotmatch '^([0-9]{1,10}):([0-9]{1,10})$') { continue }
        $parts=([string]$node.dev).Split(':')
        $major=& $normalizeDecimal $parts[0]; $minor=& $normalizeDecimal $parts[1]
        $majorGroup=& $ensureGroup $majorMap $major $major
        $majorGroup.sysfs_node_ids.Add([string]$node.node_id)
        $tuple="$major`:$minor"
        $deviceGroup=& $ensureGroup $deviceMap $tuple $major
        $deviceGroup.sysfs_node_ids.Add([string]$node.node_id)
    }
    foreach ($node in $DevNodes) {
        if ([string]$node.node_id -cnotmatch '^video[0-9]{1,10}$' -or [string]$node.status -cne 'OBSERVED' -or [string]$node.device_number -cnotmatch '^([0-9]{1,10}):([0-9]{1,10})$') { continue }
        $parts=([string]$node.device_number).Split(':')
        $major=& $normalizeDecimal $parts[0]; $minor=& $normalizeDecimal $parts[1]
        $majorGroup=& $ensureGroup $majorMap $major $major
        $majorGroup.dev_node_ids.Add([string]$node.node_id)
        $tuple="$major`:$minor"
        $deviceGroup=& $ensureGroup $deviceMap $tuple $major
        $deviceGroup.dev_node_ids.Add([string]$node.node_id)
    }
    $majorGroups=[Collections.Generic.List[object]]::new()
    foreach ($major in @($majorMap.Keys | Sort-Object -CaseSensitive)) {
        $group=$majorMap[$major]
        $status=if($group.sysfs_node_ids.Count -eq 0){'DEV_ONLY'}elseif($group.dev_node_ids.Count -eq 0){'SYSFS_ONLY'}elseif($group.sysfs_node_ids.Count -eq 1 -and $group.dev_node_ids.Count -eq 1){'UNIQUE_BY_MAJOR'}else{'AMBIGUOUS_BY_MAJOR'}
        $majorGroups.Add([pscustomobject]@{major=$major;status=$status;sysfs_node_ids=@($group.sysfs_node_ids.ToArray());dev_node_ids=@($group.dev_node_ids.ToArray())})
    }
    $exactMatches=[Collections.Generic.List[object]]::new(); $ambiguousTuples=[Collections.Generic.List[object]]::new()
    foreach ($tuple in @($deviceMap.Keys | Sort-Object -CaseSensitive)) {
        $group=$deviceMap[$tuple]
        if ($group.sysfs_node_ids.Count -eq 1 -and $group.dev_node_ids.Count -eq 1) {
            $exactMatches.Add([pscustomobject]@{device_number=$tuple;major=$group.major;sysfs_node_id=$group.sysfs_node_ids[0];dev_node_id=$group.dev_node_ids[0]})
        } elseif ($group.sysfs_node_ids.Count -gt 1 -or $group.dev_node_ids.Count -gt 1) {
            $ambiguousTuples.Add([pscustomobject]@{device_number=$tuple;sysfs_node_ids=@($group.sysfs_node_ids.ToArray());dev_node_ids=@($group.dev_node_ids.ToArray())})
        }
    }
    return [pscustomobject]@{
        major_groups=@($majorGroups.ToArray())
        exact_device_matches=@($exactMatches.ToArray())
        ambiguous_device_tuples=@($ambiguousTuples.ToArray())
        interpretation='Major groups are descriptive only; individual node matching requires a unique exact major:minor tuple. This does not establish process ownership, ioctl attribution, queue use or frame delivery.'
    }
}

function ConvertTo-P3A6M2PosixArgument {
    param([Parameter(Mandatory)][string]$Value)
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Get-P3A6M2BaseVectors {
    $vectors = [Collections.Generic.List[string[]]]::new()
    $null = $vectors.Add([string[]]@('get-state'))
    foreach ($property in @('ro.product.model','ro.product.device','ro.product.name','ro.product.manufacturer','ro.build.fingerprint','ro.build.version.release')) {
        $null = $vectors.Add([string[]]@('shell','getprop',$property))
    }
    $null = $vectors.Add([string[]]@('shell','uname','-r'))
    for ($limit = 1; $limit -le $script:P3A6M2MaxNodesPerSource; $limit++) {
        foreach ($source in @('sysfs','dev')) {
            $scriptText = Get-P3A6M2ProbeScript -Source $source -NodeLimit $limit
            $quoted = ConvertTo-P3A6M2PosixArgument -Value $scriptText
            $null = $vectors.Add([string[]]@('shell','sh','-c',$quoted))
        }
    }
    return ,$vectors.ToArray()
}

function Test-P3A6M2AllowedAdbArguments {
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Arguments)
    if ($Arguments.Count -gt 0 -and $Arguments[0] -ceq '-t') {
        if ($Arguments.Count -lt 3 -or $Arguments[1] -cnotmatch '^[1-9][0-9]{0,9}$') { return $false }
        $selectedTransport = $Arguments[1]
        $core = [string[]]$Arguments[2..($Arguments.Count - 1)]
    } else {
        $selectedTransport = ''
        $core = [string[]]$Arguments
    }
    foreach ($vector in (Get-P3A6M2BaseVectors)) {
        if ($core.Count -ne $vector.Count) { continue }
        $same = $true
        for ($i = 0; $i -lt $core.Count; $i++) {
            if ($core[$i] -cne $vector[$i]) { $same = $false; break }
        }
        if ($same) { return $true }
    }
    return $false
}

function Invoke-P3A6M2NativeAdb {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$Arguments, [ValidateRange(1,30000)][int]$TimeoutMs = 10000,
        [Parameter(Mandatory)][AllowNull()][object]$Approval, [Parameter(Mandatory)][AllowNull()][AllowEmptyString()][string]$OwnerConfirmation,
        [string]$Action=$script:P3A6M2Action)
    $nativeStarted=[Diagnostics.Stopwatch]::StartNew()
    if (-not (Test-P3A6M2AllowedAdbArguments -Arguments $Arguments)) { throw 'BLOCKED_NATIVE_ALLOWLIST' }
    if ($Action -cne $script:P3A6M2Action) { throw 'BLOCKED_SCOPE_MISMATCH' }
    $gate=Invoke-P3A6M2GateCli -Approval $Approval -Action $Action -OwnerConfirmation $OwnerConfirmation
    if (-not $gate.allowed) { throw ([string]$gate.status) }
    $adbPath = Get-P3A6M2PinnedAdbPath
    if (-not $adbPath -or -not (Test-Path -LiteralPath $adbPath -PathType Leaf)) { throw 'BLOCKED_PINNED_ADB_MISSING' }
    $resolved = (Resolve-Path -LiteralPath $adbPath -ErrorAction Stop).ProviderPath
    if ($resolved -cne $adbPath) { throw 'BLOCKED_PINNED_ADB_PATH_MISMATCH' }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $adbPath
    $start.WorkingDirectory = $script:P3A6M2RepoRoot
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { $start.ArgumentList.Add([string]$argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        $remainingMs=[int]$TimeoutMs-[int]$nativeStarted.ElapsedMilliseconds
        if ($remainingMs -le 0) { throw 'ADB_TIMEOUT' }
        if (-not $process.Start()) { throw 'BLOCKED_ADB_START_FAILED' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($remainingMs)) {
            try { $process.Kill($true) } catch { }
            throw 'ADB_TIMEOUT'
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $null = $stderrTask.GetAwaiter().GetResult()
        if ([Text.Encoding]::UTF8.GetByteCount($stdout) -gt $script:P3A6M2MaxCommandOutputBytes) { throw 'ADB_OUTPUT_LIMIT' }
        if ($process.ExitCode -ne 0) { throw 'ADB_COMMAND_FAILED' }
        return [pscustomobject]@{ exit_code = [int]$process.ExitCode; stdout = $stdout }
    } finally { $process.Dispose() }
}

function Invoke-P3A6M2GateCli {
    param([AllowNull()][object]$Approval,[string]$Action,[AllowNull()][string]$OwnerConfirmation)
    try {
        $python = @(Get-Command -Name python -CommandType Application -ErrorAction Stop)[0]
        $request = [ordered]@{ approval=$Approval; action=$Action; owner_confirmation=$OwnerConfirmation } | ConvertTo-Json -Depth 12 -Compress
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $python.Source
        $start.WorkingDirectory = $script:P3A6M2RepoRoot
        $start.UseShellExecute = $false; $start.CreateNoWindow = $true
        $start.RedirectStandardInput = $true; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
        $start.ArgumentList.Add('-m'); $start.ArgumentList.Add('pico.tools.p3a6_execution_gate_cli')
        $process = [Diagnostics.Process]::new(); $process.StartInfo = $start
        if (-not $process.Start()) { return [pscustomobject]@{allowed=$false;status='BLOCKED_GATE_UNAVAILABLE'} }
        $outTask = $process.StandardOutput.ReadToEndAsync(); $errTask = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write($request); $process.StandardInput.Close()
        if (-not $process.WaitForExit(5000)) { try {$process.Kill($true)} catch {}; return [pscustomobject]@{allowed=$false;status='BLOCKED_GATE_TIMEOUT'} }
        $out = $outTask.GetAwaiter().GetResult(); $null = $errTask.GetAwaiter().GetResult()
        if ($out.Length -gt 4096) { return [pscustomobject]@{allowed=$false;status='BLOCKED_GATE_INVALID_RESPONSE'} }
        $decision = $out | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        if ($decision -isnot [Collections.IDictionary] -or $decision.allowed -isnot [bool]) { return [pscustomobject]@{allowed=$false;status='BLOCKED_GATE_INVALID_RESPONSE'} }
        return [pscustomobject]$decision
    } catch { return [pscustomobject]@{allowed=$false;status='BLOCKED_GATE_UNAVAILABLE'} }
}

function Test-P3A6M2ApprovalPreflight {
    param([AllowNull()][object]$Approval,[string]$Action=$script:P3A6M2Action)
    if ($null -eq $Approval) { return [pscustomobject]@{allowed=$false;status='BLOCKED_NO_APPROVAL'} }
    $durationValue=$Approval.max_duration_seconds
    $observationValue=$Approval.max_observations
    $durationType=if($null -ne $durationValue){$durationValue.GetType()}else{$null}
    $observationType=if($null -ne $observationValue){$observationValue.GetType()}else{$null}
    if (($durationType -ne [int] -and $durationType -ne [long]) -or [int64]$durationValue -lt 1 -or
        ($observationType -ne [int] -and $observationType -ne [long]) -or [int64]$observationValue -lt 1) {
        return [pscustomobject]@{allowed=$false;status='BLOCKED_UNBOUNDED_APPROVAL'}
    }
    $decision = Invoke-P3A6M2GateCli -Approval $Approval -Action $Action -OwnerConfirmation $null
    if ($decision.status -ne 'BLOCKED_CONFIRMATION_REQUIRED') { return $decision }
    return [pscustomobject]@{allowed=$true;status='READY_FOR_INTERACTIVE_CONFIRMATION';approval_id=[string]$Approval.approval_id}
}

function Resolve-P3A6M2Confirmation {
    param([AllowNull()][object]$Approval,[AllowNull()][string]$Response,[bool]$Interactive,[string]$Action=$script:P3A6M2Action)
    if (-not $Interactive) { return [pscustomobject]@{accepted=$false;status='BLOCKED_NON_INTERACTIVE';token=$null} }
    if ($Action -cne $script:P3A6M2Action) { return [pscustomobject]@{accepted=$false;status='BLOCKED_SCOPE_MISMATCH';token=$null} }
    if ($Response -cne 'yes') { return [pscustomobject]@{accepted=$false;status='BLOCKED_CONFIRMATION_REQUIRED';token=$null} }
    if ([string]$Approval.approval_id -cnotmatch '^[A-Za-z0-9._-]{1,64}$') { return [pscustomobject]@{accepted=$false;status='BLOCKED_INVALID_APPROVAL_ID';token=$null} }
    return [pscustomobject]@{accepted=$true;status='CONFIRMED';token=('P3-A6 APPROVE {0} {1}' -f $Approval.approval_id,$Action)}
}

function ConvertFrom-P3A6M2ProbeOutput {
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowEmptyString()][string]$ProbeText,[ValidateSet('sysfs','dev')][string]$Source)
    $result = [ordered]@{valid=$false;source=$Source;source_status='UNAVAILABLE';nodes=[ordered]@{};line_ending_classification='NOT_ANALYZED';record_count=0;reason=$null}
    if ($ProbeText.Length -gt 65536) { $result.reason='OUTPUT_BOUNDARY'; return [pscustomobject]$result }
    $lfCount=0; $crlfCount=0; $invalidCr=$false; $invalidControl=$false
    for ($i=0;$i -lt $ProbeText.Length;$i++) {
        $character=$ProbeText[$i]
        if ($character -ceq [char]13) {
            if ($i+1 -lt $ProbeText.Length -and $ProbeText[$i+1] -ceq [char]10) { $crlfCount++; $i++ }
            else { $invalidCr=$true }
        } elseif ($character -ceq [char]10) { $lfCount++ }
        elseif ([char]::IsControl($character) -and $character -cne [char]9) { $invalidControl=$true }
    }
    if ($invalidCr) { $result.line_ending_classification='INVALID'; $result.reason='OUTPUT_FRAMING'; return [pscustomobject]$result }
    if ($lfCount -gt 0 -and $crlfCount -gt 0) { $result.line_ending_classification='MIXED' }
    elseif ($crlfCount -gt 0) { $result.line_ending_classification='CRLF' }
    elseif ($lfCount -gt 0) { $result.line_ending_classification='LF' }
    else { $result.line_ending_classification='NONE' }
    if ($invalidControl) { $result.reason='OUTPUT_CONTROL'; return [pscustomobject]$result }
    if (-not $ProbeText.EndsWith("`n",[StringComparison]::Ordinal)) { $result.reason='OUTPUT_FRAMING'; return [pscustomobject]$result }
    $normalizedText=$ProbeText.Replace("`r`n","`n")
    $lines = @($normalizedText.Split([char]10))
    if ($lines.Count -lt 2 -or $lines[-1] -cne '') { $result.reason='OUTPUT_FRAMING'; return [pscustomobject]$result }
    $sourceCount=0; $nodeCount=0
    $sourceRecordName=$Source.ToUpperInvariant() + '_SOURCE'
    foreach ($line in $lines[0..($lines.Count-2)]) {
        if ($sourceCount -gt 0) { $result.reason='RECORD_AFTER_SOURCE_STATUS'; return [pscustomobject]$result }
        $fields = $line.Split([char]9)
        if ($Source -ceq 'sysfs' -and $fields.Count -eq 6 -and $fields[0] -ceq 'P3A6M2' -and $fields[1] -ceq 'SYSFS_NODE') {
            if ($fields[2] -cnotmatch '^video[0-9]{1,10}$' -or $fields[3] -cnotin @('name','index','dev') -or $fields[4] -cnotin @('OBSERVED','ATTRIBUTE_MISSING','PERMISSION_DENIED','INVALID')) { $result.reason='SYSFS_RECORD'; return [pscustomobject]$result }
            $field=$fields[3]; $value=$fields[5]; $node=$fields[2]
            if (-not $result.nodes.Contains($node)) {
                if ($result.nodes.Count -ge $script:P3A6M2MaxNodesPerSource) { $result.reason='NODE_LIMIT'; return [pscustomobject]$result }
                $result.nodes[$node]=[ordered]@{node_id=$node;name=$null;index=$null;dev=$null;fields=[ordered]@{};metadata_fields_complete=$false}
            }
            if ($result.nodes[$node].fields.Contains($field)) { $result.reason='DUPLICATE_FIELD'; return [pscustomobject]$result }
            if ($fields[4] -ceq 'OBSERVED') {
                $validValue = switch ($field) {
                    name { $value.Length -ge 1 -and $value.Length -le 96 -and $value -cmatch '^[A-Za-z0-9_.:+ -]+$' }
                    index { $value -cmatch '^[0-9]{1,10}$' }
                    dev { $value -cmatch '^[0-9]{1,10}:[0-9]{1,10}$' }
                }
                if (-not $validValue) { $result.reason='SYSFS_VALUE'; return [pscustomobject]$result }
                $result.nodes[$node][$field]=$value
            } elseif ($value -cne '') { $result.reason='UNAVAILABLE_VALUE_PRESENT'; return [pscustomobject]$result }
            $result.nodes[$node].fields[$field]=[pscustomobject]@{status=$fields[4];value=$(if($fields[4] -ceq 'OBSERVED'){$value}else{$null})}
            $nodeCount++
        } elseif ($Source -ceq 'dev' -and $fields.Count -eq 9 -and $fields[0] -ceq 'P3A6M2' -and $fields[1] -ceq 'DEV_NODE') {
            if ($fields[2] -cnotmatch '^video[0-9]{1,10}$' -or $fields[3] -cnotin @('OBSERVED','UNAVAILABLE') -or $fields[4] -cnotin @('OK','SYMLINK_EXCLUDED','UNEXPECTED_TYPE','LS_FAILED','LS_MULTILINE','LS_INCOMPATIBLE')) { $result.reason='DEV_RECORD'; return [pscustomobject]$result }
            if ($result.nodes.Contains($fields[2])) { $result.reason='DUPLICATE_NODE'; return [pscustomobject]$result }
            if ($result.nodes.Count -ge $script:P3A6M2MaxNodesPerSource) { $result.reason='NODE_LIMIT'; return [pscustomobject]$result }
            if ($fields[3] -ceq 'OBSERVED') {
                if ($fields[4] -cne 'OK' -or $fields[5] -cnotmatch '^c[rwxstST-]{9}$' -or $fields[6] -cnotmatch '^[0-9]{1,10}$' -or $fields[7] -cnotmatch '^[0-9]{1,10}$' -or $fields[8] -cnotmatch '^[0-9]{1,10}:[0-9]{1,10}$') { $result.reason='DEV_VALUE'; return [pscustomobject]$result }
            } elseif (($fields[5..8] -join '') -cne '') { $result.reason='DEV_UNAVAILABLE_VALUE'; return [pscustomobject]$result }
            $result.nodes[$fields[2]]=[ordered]@{node_id=$fields[2];status=$fields[3];reason=$fields[4];mode=$(if($fields[3] -ceq 'OBSERVED'){$fields[5]}else{$null});uid=$(if($fields[3] -ceq 'OBSERVED'){$fields[6]}else{$null});gid=$(if($fields[3] -ceq 'OBSERVED'){$fields[7]}else{$null});device_number=$(if($fields[3] -ceq 'OBSERVED'){$fields[8]}else{$null})}
            $nodeCount++
        } elseif ($fields.Count -eq 3 -and $fields[0] -ceq 'P3A6M2' -and $fields[1] -ceq $sourceRecordName -and $fields[2] -cnotin @('OBSERVED','NOT_OBSERVED','UNAVAILABLE','PERMISSION_DENIED','LIMIT_REACHED')) {
            $result.reason='SOURCE_STATUS'; return [pscustomobject]$result
        } elseif ($fields.Count -eq 3 -and $fields[0] -ceq 'P3A6M2' -and $fields[1] -ceq $sourceRecordName) {
            $sourceCount++; $result.source_status=$fields[2]
        } else { $result.reason='UNEXPECTED_RECORD'; return [pscustomobject]$result }
        $result.record_count++
    }
    if ($sourceCount -ne 1 -or $nodeCount -gt 48) { $result.reason='RECORD_COUNT'; return [pscustomobject]$result }
    if ($result.source_status -ceq 'NOT_OBSERVED' -and $nodeCount -gt 0) { $result.reason='SOURCE_STATUS_CONFLICT'; return [pscustomobject]$result }
    if ($result.source_status -cin @('OBSERVED','LIMIT_REACHED') -and $nodeCount -eq 0) { $result.reason='EMPTY_SOURCE_MARKED_OBSERVED'; return [pscustomobject]$result }
    foreach ($node in $result.nodes.Keys) {
        if ($Source -ceq 'sysfs') {
            if ($result.nodes[$node].fields.Count -ne 3) { $result.reason='INCOMPLETE_NODE_RECORD'; return [pscustomobject]$result }
            $result.nodes[$node].metadata_fields_complete = ($result.nodes[$node].fields.name.status -ceq 'OBSERVED' -and $result.nodes[$node].fields.index.status -ceq 'OBSERVED' -and $result.nodes[$node].fields.dev.status -ceq 'OBSERVED')
        }
    }
    $observedCount=0; $deniedCount=0
    foreach ($node in $result.nodes.Values) {
        if ($Source -ceq 'sysfs') {
            foreach ($field in $node.fields.Values) {
                if ($field.status -ceq 'OBSERVED') { $observedCount++ }
                elseif ($field.status -ceq 'PERMISSION_DENIED') { $deniedCount++ }
            }
        } elseif ($node.status -ceq 'OBSERVED') { $observedCount++ }
    }
    if ($result.source_status -ceq 'OBSERVED' -and $observedCount -eq 0) { $result.reason='SOURCE_STATUS_CONFLICT'; return [pscustomobject]$result }
    if ($result.source_status -ceq 'UNAVAILABLE' -and $observedCount -gt 0) { $result.reason='SOURCE_STATUS_CONFLICT'; return [pscustomobject]$result }
    if ($result.source_status -ceq 'PERMISSION_DENIED' -and ($observedCount -gt 0 -or ($nodeCount -gt 0 -and $deniedCount -eq 0))) { $result.reason='SOURCE_STATUS_CONFLICT'; return [pscustomobject]$result }
    $result.valid=$true
    return [pscustomobject]$result
}

function Test-P3A6M2OutputRoot {
    param([string]$OutputRoot)
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { return $false }
    try {
        $local=[IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\','/')
        $full=[IO.Path]::GetFullPath($OutputRoot)
        $prefix=$local + [IO.Path]::DirectorySeparatorChar
        if (-not $full.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($script:P3A6M2RepoRoot,[StringComparison]::OrdinalIgnoreCase)) { return $false }
        $cursor=$full
        while ($cursor.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) {
            if (Test-Path -LiteralPath $cursor) {
                $item=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
                if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
            }
            $parent=[IO.Directory]::GetParent($cursor)
            if ($null -eq $parent) { break }
            $cursor=$parent.FullName
        }
        return $true
    } catch { return $false }
}

function Set-P3A6M2CommandUnavailable {
    param([System.Collections.IDictionary]$Observation,[string]$Key,[string]$Reason)
    $method=if($script:P3A6M2Identity.Contains($Key) -or $Key -like 'ro.build.*'){'adb shell getprop'}elseif($Key -ceq 'kernel_release'){'adb shell uname -r'}else{'adb get-state'}
    $field=[ordered]@{status='UNAVAILABLE';value=$null;method=$method;observed_at_utc=(Get-P3A6M2UtcNow);build_identity=$null;reason=$Reason}
    if ($script:P3A6M2Identity.Contains($Key)) { $Observation.software_identity[$Key]=$field }
    elseif ($Key -ceq 'ro.build.fingerprint') { $Observation.build.fingerprint=$field }
    elseif ($Key -ceq 'ro.build.version.release') { $Observation.build.android_release=$field }
    elseif ($Key -ceq 'kernel_release') { $Observation.kernel.release=$field }
    elseif ($Key -ceq 'state') { $Observation.device_state=$field }
}

function New-P3A6M2EvidenceDirectory {
    param([string]$OutputRoot,[string]$RunId)
    if (-not (Test-P3A6M2OutputRoot -OutputRoot $OutputRoot)) { throw 'Evidence path is outside LOCALAPPDATA' }
    $dir=Join-Path $OutputRoot $RunId
    $null=[IO.Directory]::CreateDirectory($dir)
    if ($IsWindows) {
        $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
        if ($null -eq $sid) { throw 'Owner SID unavailable' }
        $acl=[Security.AccessControl.DirectorySecurity]::new(); $acl.SetAccessRuleProtection($true,$false); $acl.SetOwner($sid)
        $system=[Security.Principal.SecurityIdentifier]::new([Security.Principal.WellKnownSidType]::LocalSystemSid,$null)
        foreach ($principal in @($sid,$system)) {
            $rule=[Security.AccessControl.FileSystemAccessRule]::new($principal,[Security.AccessControl.FileSystemRights]::FullControl,[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
            $acl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $dir -AclObject $acl
    }
    return $dir
}

function Invoke-P3A6M2Inventory {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$Approval,[AllowNull()][string]$OwnerConfirmation,
        [Parameter(Mandatory)][scriptblock]$AdbExecutor,[string]$OutputRoot='',[string]$TransportId='',
        [string]$Action=$script:P3A6M2Action,[ValidateRange(1,30)][int]$MaxDurationSeconds=30,
        [ValidateRange(1,40)][int]$MaxObservations=40
    )
    $started=[Diagnostics.Stopwatch]::StartNew(); $commandCount=0; $records=0
    $baseResult=[ordered]@{status='BLOCKED';collection_status='BLOCKED';adb_command_count=0;observation_count=0;record_count=0;evidence_directory=$null;archive_path=$null;marker_path=$null}
    if ($Action -cne $script:P3A6M2Action) { $baseResult.status='BLOCKED_SCOPE_MISMATCH'; return [pscustomobject]$baseResult }
    $preflight=Invoke-P3A6M2GateCli -Approval $Approval -Action $Action -OwnerConfirmation $null
    if ($preflight.status -ne 'BLOCKED_CONFIRMATION_REQUIRED') { $baseResult.status=[string]$preflight.status; return [pscustomobject]$baseResult }
    if ($OwnerConfirmation -cnotmatch '^P3-A6 APPROVE [A-Za-z0-9._-]{1,64} read-only-camera-node-metadata$') { $baseResult.status='BLOCKED_CONFIRMATION_REQUIRED'; return [pscustomobject]$baseResult }
    $effectiveDuration=[Math]::Min($MaxDurationSeconds,[int]$Approval.max_duration_seconds)
    $effectiveRecords=[Math]::Min($MaxObservations,[int]$Approval.max_observations)
    $deadline=[Math]::Min(30,$effectiveDuration)*1000
    $transportPrefix=[string[]]@()
    if ($TransportId) {
        if ($TransportId -cnotmatch '^[1-9][0-9]{0,9}$') { $baseResult.status='BLOCKED_INVALID_TRANSPORT'; return [pscustomobject]$baseResult }
        $transportPrefix=[string[]]@('-t',$TransportId)
    }
    $commands=[Collections.Generic.List[object]]::new()
    $null=$commands.Add([pscustomobject]@{vector=[string[]]@('get-state');key='state'})
    foreach ($property in $script:P3A6M2Identity.Keys) { $null=$commands.Add([pscustomobject]@{vector=[string[]]@('shell','getprop',$property);key=$property}) }
    foreach ($property in @('ro.build.fingerprint','ro.build.version.release')) { $null=$commands.Add([pscustomobject]@{vector=[string[]]@('shell','getprop',$property);key=$property}) }
    $null=$commands.Add([pscustomobject]@{vector=[string[]]@('shell','uname','-r');key='kernel_release'})
    $identityEvidence=[ordered]@{}
    foreach($key in $script:P3A6M2Identity.Keys){$identityEvidence[$key]=[ordered]@{status='NOT_OBSERVED';value=$null;method='adb shell getprop';observed_at_utc=$null;build_identity=$null;reason=$null}}
    $buildEvidence=[ordered]@{
        fingerprint=[ordered]@{status='NOT_OBSERVED';value=$null;method='adb shell getprop';observed_at_utc=$null;build_identity=$null;reason=$null}
        android_release=[ordered]@{status='NOT_OBSERVED';value=$null;method='adb shell getprop';observed_at_utc=$null;build_identity=$null;reason=$null}
    }
    $observation=[ordered]@{
        schema='p3a6.m2.node_inventory.v2';run_id=[guid]::NewGuid().ToString('N');action=$Action;approval_id=[string]$Approval.approval_id;device='Pico 4 Pro'
        collector_revision='P3-A6-M2-v3';started_at_utc=(Get-P3A6M2UtcNow);finished_at_utc=$null;elapsed_milliseconds=$null
        collection_status='PARTIAL';identity_status='NOT_OBSERVED';adb_command_count=0;observation_count=0
        device_state=[ordered]@{status='NOT_OBSERVED';value=$null;method='adb get-state';observed_at_utc=$null;reason=$null}
        software_identity=$identityEvidence;build=$buildEvidence
        kernel=[ordered]@{release=[ordered]@{status='NOT_OBSERVED';value=$null;method='adb shell uname -r';observed_at_utc=$null;build_identity=$null;reason=$null}}
        sources=[ordered]@{sysfs=[ordered]@{status='NOT_OBSERVED';method='fixed sysfs name/index/dev probe';script_sha256=$null;observed_at_utc=$null;build_identity=$null;normalized_line_ending_classification='NOT_OBSERVED';parsed_record_count=0;parser_error_code=$null;nodes=@()};dev=[ordered]@{status='NOT_OBSERVED';method='fixed /dev metadata probe; no node open';script_sha256=$null;observed_at_utc=$null;build_identity=$null;normalized_line_ending_classification='NOT_OBSERVED';parsed_record_count=0;parser_error_code=$null;nodes=@()}}
        parser_diagnostics=[ordered]@{failed_source=$null;normalized_line_ending_classification='NOT_OBSERVED';parsed_record_count=0;parser_error_code=$null}
        node_correlations=[ordered]@{major_groups=@();exact_device_matches=@();ambiguous_device_tuples=@();interpretation='No cross-source node correlation computed yet.'}
        limits=[ordered]@{duration_seconds=$effectiveDuration;observations=$effectiveRecords;nodes_per_source=$script:P3A6M2MaxNodesPerSource}
        methods=@('ADB get-state','fixed getprop keys','uname -r','POSIX shell sysfs attributes','ls -ldn metadata on /dev candidates')
        source_hashes=[ordered]@{collector_module_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();runner_sha256=(Get-FileHash -LiteralPath (Join-Path $script:P3A6M2RepoRoot 'pico/tools/collect_p3a6_camera_node_inventory.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()}
        safety_flags=$script:P3A6M2SafetyFlags
        identity_provenance='Exact Android property tuple is an owner-bound Phoenix-family software identity check; it is not cryptographic attestation and does not establish Pico 4 Pro hardware variant. Pico 4 Pro / international Pico OS remains owner-confirmed project fact.'
        owner_declared_hardware_variant='Pico 4 Pro'
        interpretation='Node metadata only. Does not establish process ownership, ioctl attribution, frame delivery, physical SOF or exposure timing.'
    }
    $runDir=$null
    try {
        if (-not $OutputRoot) { if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA unavailable' }; $OutputRoot=Join-Path $env:LOCALAPPDATA 'PicoLHSync\private-evidence\m2-camera-nodes' }
        $runDir=New-P3A6M2EvidenceDirectory -OutputRoot $OutputRoot -RunId $observation.run_id
        foreach ($item in $commands) {
            if ($started.ElapsedMilliseconds -ge $deadline) { throw 'M2_TIMEOUT' }
            $vector=[string[]]@($transportPrefix + $item.vector)
            $gate=Invoke-P3A6M2GateCli -Approval $Approval -Action $Action -OwnerConfirmation $OwnerConfirmation
            if (-not $gate.allowed) { throw ([string]$gate.status) }
            if (-not (Test-P3A6M2AllowedAdbArguments -Arguments $vector)) { throw 'BLOCKED_NATIVE_ALLOWLIST' }
            $remainingMs=$deadline-$started.ElapsedMilliseconds
            if ($remainingMs -le 0) { throw 'M2_TIMEOUT' }
            $remaining=[int][Math]::Min(10000,$remainingMs)
            $commandCount++
            $response=& $AdbExecutor $vector $remaining
            if ($null -eq $response -or $response.exit_code -ne 0) {
                Set-P3A6M2CommandUnavailable -Observation $observation -Key $item.key -Reason 'ADB_COMMAND_FAILED'
                throw 'ADB_COMMAND_FAILED'
            }
            $value=[string]$response.stdout
            if ([Text.Encoding]::UTF8.GetByteCount($value) -gt 4096 -or $value.Contains([char]0)) {
                Set-P3A6M2CommandUnavailable -Observation $observation -Key $item.key -Reason 'MALFORMED_OUTPUT'
                throw 'UNEXPECTED_IDENTITY_OUTPUT'
            }
            if ($value.EndsWith("`r`n")) { $value=$value.Substring(0,$value.Length-2) }
            elseif ($value.EndsWith("`n") -or $value.EndsWith("`r")) { $value=$value.Substring(0,$value.Length-1) }
            if ($value.Contains("`n") -or $value.Contains("`r")) {
                Set-P3A6M2CommandUnavailable -Observation $observation -Key $item.key -Reason 'MULTILINE_OUTPUT'
                throw 'UNEXPECTED_IDENTITY_OUTPUT'
            }
            if ($started.ElapsedMilliseconds -ge $deadline) { throw 'M2_TIMEOUT' }
            if ($item.key -ceq 'state') {
                $observation.device_state=[ordered]@{status=$(if($value.Length){'OBSERVED'}else{'UNAVAILABLE'});value=$(if($value.Length){$value}else{$null});method='adb get-state';observed_at_utc=(Get-P3A6M2UtcNow);reason=$(if($value.Length){$null}else{'EMPTY_RESPONSE'})}
                if ($value -cne 'device') { throw 'BLOCKED_ADB_DEVICE_STATE' }
                continue
            }
            if ($value.Length -eq 0) {
                Set-P3A6M2CommandUnavailable -Observation $observation -Key $item.key -Reason 'EMPTY_RESPONSE'
                if ($script:P3A6M2Identity.Contains($item.key)) { throw 'BLOCKED_INVALID_DEVICE_IDENTITY' }
                throw 'BLOCKED_BUILD_IDENTITY_UNAVAILABLE'
            }
            if ($script:P3A6M2Identity.Contains($item.key)) {
                $observation.software_identity[$item.key]=[ordered]@{status='OBSERVED';value=$value;method='adb shell getprop';observed_at_utc=(Get-P3A6M2UtcNow);build_identity=$null;reason=$null}
                $observedIdentityCount=@($script:P3A6M2Identity.Keys | Where-Object { $observation.software_identity[$_].status -ceq 'OBSERVED' }).Count
                if ($observedIdentityCount -eq 4) {
                    foreach ($identityKey in $script:P3A6M2Identity.Keys) {
                        if ([string]$observation.software_identity[$identityKey].value -cne $script:P3A6M2Identity[$identityKey]) { throw 'BLOCKED_UNEXPECTED_DEVICE' }
                    }
                }
                continue
            }
            if ($item.key -ceq 'ro.build.fingerprint') { $observation.build.fingerprint=[ordered]@{status='OBSERVED';value=$value;method='adb shell getprop';observed_at_utc=(Get-P3A6M2UtcNow);build_identity=$value;reason=$null}; continue }
            if ($item.key -ceq 'ro.build.version.release') { $observation.build.android_release=[ordered]@{status='OBSERVED';value=$value;method='adb shell getprop';observed_at_utc=(Get-P3A6M2UtcNow);build_identity=$null;reason=$null}; continue }
            if ($item.key -ceq 'kernel_release') { $observation.kernel.release=[ordered]@{status='OBSERVED';value=$value;method='adb shell uname -r';observed_at_utc=(Get-P3A6M2UtcNow);build_identity=$null;reason=$null} }
        }
        foreach ($key in $script:P3A6M2Identity.Keys) {
            if (-not $observation.software_identity.Contains($key) -or [string]$observation.software_identity[$key].value -cne $script:P3A6M2Identity[$key]) { throw 'BLOCKED_UNEXPECTED_DEVICE' }
        }
        $observation.identity_status='PHOENIX_SOFTWARE_IDENTITY_VERIFIED_OWNER_BOUND'
        foreach($key in $script:P3A6M2Identity.Keys){$observation.software_identity[$key].build_identity=[string]$observation.build.fingerprint.value}
        $observation.build.android_release.build_identity=[string]$observation.build.fingerprint.value
        $observation.kernel.release.build_identity=[string]$observation.build.fingerprint.value
        $remainingBudget=$effectiveRecords
        foreach ($source in @('sysfs','dev')) {
            if ($started.ElapsedMilliseconds -ge $deadline) { throw 'M2_TIMEOUT' }
            if ($remainingBudget -le 0) { $observation.sources[$source].status='LIMIT_REACHED'; continue }
            $sourceLimit=[Math]::Min(16,$remainingBudget)
            $probe=Get-P3A6M2ProbeScript -Source $source -NodeLimit $sourceLimit
            $observation.sources[$source].script_sha256=Get-P3A6M2TextSha256 -Text $probe
            $quoted=ConvertTo-P3A6M2PosixArgument -Value $probe
            $vector=[string[]]@($transportPrefix + @('shell','sh','-c',$quoted))
            $gate=Invoke-P3A6M2GateCli -Approval $Approval -Action $Action -OwnerConfirmation $OwnerConfirmation
            if (-not $gate.allowed) { throw ([string]$gate.status) }
            if (-not (Test-P3A6M2AllowedAdbArguments -Arguments $vector)) { throw 'BLOCKED_NATIVE_ALLOWLIST' }
            $remainingMs=$deadline-$started.ElapsedMilliseconds
            if ($remainingMs -le 0) { throw 'M2_TIMEOUT' }
            $remaining=[int][Math]::Min(10000,$remainingMs)
            $commandCount++
            $response=& $AdbExecutor $vector $remaining
            if ($null -eq $response -or $response.exit_code -ne 0) { throw 'ADB_COMMAND_FAILED' }
            if ($started.ElapsedMilliseconds -ge $deadline) { throw 'M2_TIMEOUT' }
            $parsed=ConvertFrom-P3A6M2ProbeOutput -ProbeText ([string]$response.stdout) -Source $source
            $observation.sources[$source].normalized_line_ending_classification=[string]$parsed.line_ending_classification
            $observation.sources[$source].parsed_record_count=[int]$parsed.record_count
            if (-not $parsed.valid) {
                $observation.sources[$source].status='UNAVAILABLE'
                $observation.sources[$source].parser_error_code=[string]$parsed.reason
                $observation.parser_diagnostics=[ordered]@{failed_source=$source;normalized_line_ending_classification=[string]$parsed.line_ending_classification;parsed_record_count=[int]$parsed.record_count;parser_error_code=[string]$parsed.reason}
                throw 'PARTIAL_UNEXPECTED_OUTPUT'
            }
            $observation.sources[$source].status=$parsed.source_status
            $observation.sources[$source].observed_at_utc=Get-P3A6M2UtcNow
            $observation.sources[$source].build_identity=[string]$observation.build.fingerprint.value
            $nodes=@($parsed.nodes.Values)
            $observation.sources[$source].nodes=$nodes
            $records += $nodes.Count
            $remainingBudget -= $nodes.Count
            if ($records -gt $effectiveRecords) { throw 'M2_RECORD_LIMIT' }
        }
        $observation.node_correlations=Get-P3A6M2NodeCorrelations -SysfsNodes $observation.sources.sysfs.nodes -DevNodes $observation.sources.dev.nodes
        $allMetadataObserved=($observation.sources.sysfs.status -ceq 'OBSERVED' -and $observation.sources.dev.status -ceq 'OBSERVED')
        foreach ($node in $observation.sources.sysfs.nodes) { if (-not $node.metadata_fields_complete) { $allMetadataObserved=$false } }
        foreach ($node in $observation.sources.dev.nodes) { if ($node.status -cne 'OBSERVED') { $allMetadataObserved=$false } }
        if ($allMetadataObserved) { $observation.collection_status='COMPLETE' }
        else { $observation.collection_status='PARTIAL_LIMITATIONS' }
        $baseResult.status=$observation.collection_status; $baseResult.collection_status=$observation.collection_status
    } catch {
        $failure=$_.Exception.Message
        $observation.collection_status=if ($failure -eq 'M2_TIMEOUT' -or $failure -eq 'ADB_TIMEOUT') {'PARTIAL_TIMEOUT'} elseif ($failure -in @('PARTIAL_UNEXPECTED_OUTPUT','UNEXPECTED_IDENTITY_OUTPUT')) {'PARTIAL_UNEXPECTED_OUTPUT'} elseif ($failure -eq 'BLOCKED_BUILD_IDENTITY_UNAVAILABLE') {'PARTIAL_LIMITATIONS'} elseif ($failure -in @('BLOCKED_UNEXPECTED_DEVICE','BLOCKED_INVALID_DEVICE_IDENTITY','BLOCKED_ADB_DEVICE_STATE')) {$failure} else {'PARTIAL_ADB_ERROR'}
        $baseResult.status=$observation.collection_status; $baseResult.collection_status=$observation.collection_status
        $observation.failure_status=$failure
    } finally {
        $observation.finished_at_utc=Get-P3A6M2UtcNow
        $observation.elapsed_milliseconds=[int64]$started.ElapsedMilliseconds
        $observation.adb_command_count=$commandCount
        $observation.observation_count=$records
        $baseResult.adb_command_count=$commandCount; $baseResult.observation_count=$records; $baseResult.record_count=$records
        if ($runDir) {
            try {
                $evidencePath=Join-Path $runDir 'evidence.json'
                [IO.File]::WriteAllText($evidencePath,($observation | ConvertTo-Json -Depth 16),[Text.UTF8Encoding]::new($false))
                $archivePath=Join-Path $runDir 'evidence.zip'
                if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
                Compress-Archive -LiteralPath $evidencePath -DestinationPath $archivePath -CompressionLevel Optimal
                $archiveHash=(Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
                $marker=[ordered]@{schema='p3a6.m2.final_marker.v1';run_id=$observation.run_id;archive='evidence.zip';archive_sha256=$archiveHash;finished_at_utc=$observation.finished_at_utc}
                $markerPath=Join-Path $runDir 'final.marker.json'
                [IO.File]::WriteAllText($markerPath,($marker | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
                $baseResult.evidence_directory=$runDir; $baseResult.archive_path=$archivePath; $baseResult.marker_path=$markerPath
            } catch { $baseResult.status='PARTIAL_EVIDENCE_ERROR'; $baseResult.collection_status='PARTIAL_EVIDENCE_ERROR' }
        }
    }
    return [pscustomobject]$baseResult
}

function Invoke-P3A6M2ConfirmedInventory {
    param([AllowNull()][object]$Approval,[AllowNull()][string]$Response,[bool]$Interactive,[Parameter(Mandatory)][scriptblock]$AdbExecutor,[string]$OutputRoot='',[string]$TransportId='',[string]$Action=$script:P3A6M2Action)
    $preflight=Test-P3A6M2ApprovalPreflight -Approval $Approval -Action $Action
    if (-not $preflight.allowed) { return [pscustomobject]@{status=[string]$preflight.status;collection_status='BLOCKED';adb_command_count=0;observation_count=0;record_count=0;evidence_directory=$null;archive_path=$null;marker_path=$null} }
    $confirmation=Resolve-P3A6M2Confirmation -Approval $Approval -Response $Response -Interactive $Interactive -Action $Action
    if (-not $confirmation.accepted) { return [pscustomobject]@{status=[string]$confirmation.status;collection_status='BLOCKED';adb_command_count=0;observation_count=0;record_count=0;evidence_directory=$null;archive_path=$null;marker_path=$null} }
    return Invoke-P3A6M2Inventory -Approval $Approval -OwnerConfirmation $confirmation.token -AdbExecutor $AdbExecutor -OutputRoot $OutputRoot -TransportId $TransportId -Action $Action
}

function Invoke-P3A6M2DryRun {
    [pscustomobject]@{status='DRY_RUN';collection_status='NOT_RUN';adb_command_count=0;observation_count=0;record_count=0;hardware_accessed=$false;safety_flags=$script:P3A6M2SafetyFlags}
}

Export-ModuleMember -Function Get-P3A6M2PinnedAdbPath,Get-P3A6M2ProbeScript,Get-P3A6M2TextSha256,Get-P3A6M2NodeCorrelations,ConvertTo-P3A6M2PosixArgument,Test-P3A6M2AllowedAdbArguments,Invoke-P3A6M2NativeAdb,Test-P3A6M2ApprovalPreflight,Resolve-P3A6M2Confirmation,ConvertFrom-P3A6M2ProbeOutput,Invoke-P3A6M2ConfirmedInventory,Invoke-P3A6M2DryRun
