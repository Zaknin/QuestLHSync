$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repoRoot

function Invoke-LocalWsl {
    param([string]$Text)
    $Text = $Text.Replace("`r`n", "`n")
    $wsl = Get-Command wsl.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $wsl.Source
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($arg in @('--exec', '/bin/sh', '-s')) { $startInfo.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw 'Could not start local WSL /bin/sh' }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.Write($Text)
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(15000)) {
        try { $process.Kill($true) } catch { }
        throw 'Local POSIX M2.8D fixture exceeded its 15-second bound'
    }
    try {
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdoutTask.GetAwaiter().GetResult()
            Stderr = $stderrTask.GetAwaiter().GetResult()
        }
    }
    finally { $process.Dispose() }
}

function Get-Base64Script([string]$Name) {
    $code = "import base64; from pico.tools import p3a_m28d_callback_logs as m; print(base64.b64encode(getattr(m, '$Name').decode('ascii').encode()).decode())"
    $value = & python -c $code
    if ($LASTEXITCODE -ne 0) { throw "Could not load fixed $Name bytes" }
    return [string]$value
}

function Invoke-ScriptFixture {
    param([string]$Fixture, [string]$Case, [string]$ScriptB64)
    $wrapper = @'
set +e
fixture='__FIXTURE__'
case_name='__CASE__'
script_b64='__SCRIPT_B64__'
printf '%s' "$script_b64" | base64 -d | PATH="$fixture/bin:/usr/bin:/bin" M28D_FIXTURE="$fixture" M28D_CASE="$case_name" /bin/sh -s
exit $?
'@
    $wrapper = $wrapper.Replace('__FIXTURE__', $Fixture).Replace('__CASE__', $Case).Replace('__SCRIPT_B64__', $ScriptB64)
    return Invoke-LocalWsl $wrapper
}

function Get-ParsedProbe($Run) {
    $stdout64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Run.Stdout))
    $python = "import base64,json; from pico.tools import p3a_m28d_callback_logs as m; print(json.dumps(m.parse_probe_result(base64.b64decode('$stdout64'), returncode=$($Run.ExitCode), stderr_byte_count=$([Text.Encoding]::UTF8.GetByteCount($Run.Stderr)))))"
    $json = & python -c $python
    if ($LASTEXITCODE -ne 0) { throw 'Python parser failed unexpectedly for WSL probe bytes' }
    return ($json | ConvertFrom-Json)
}

function Get-ParsedCapability($Run) {
    $stdout64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Run.Stdout))
    $python = "import base64; from pico.tools import p3a_m28d_callback_logs as m; print(m.parse_logcat_capability(base64.b64decode('$stdout64'), $($Run.ExitCode)))"
    $value = & python -c $python
    if ($LASTEXITCODE -ne 0) { throw 'Python capability parser failed unexpectedly' }
    return [string]$value
}

$fixture = '/tmp/p3a-m28d-' + [guid]::NewGuid().ToString('N')
$probeB64 = Get-Base64Script 'PROBE_SCRIPT_BYTES'
$capabilityB64 = Get-Base64Script 'CAPABILITY_SCRIPT_BYTES'
$shellV2B64 = Get-Base64Script 'SHELL_V2_SCRIPT_BYTES'

$setup = @'
set -eu
fixture='__FIXTURE__'
mkdir -p "$fixture/bin"
cat > "$fixture/bin/ps" <<'PS'
#!/bin/sh
[ "$#" -eq 3 ] && [ "$1" = '-A' ] && [ "$2" = '-o' ] && [ "$3" = 'PID,NAME' ] || { printf 'PRIVATE_PS_ARGS\n' >&2; exit 90; }
case "$M28D_CASE" in
  ps-denied) printf 'PRIVATE_PS_ERROR\n' >&2; exit 3 ;;
  no-process) printf 'PID NAME\n' ;;
  malformed-process) printf 'PID NAME\n412 com.pico.quickcamera extra\n' ;;
  many-processes)
    printf 'PID NAME\n'; i=0
    while [ "$i" -lt 17 ]; do printf '%s com.pico.quickcamera:service%s\n' "$((500+i))" "$i"; i=$((i+1)); done
    ;;
  exact-40|over-40)
    printf 'PID NAME\n'; i=0
    while [ "$i" -lt 16 ]; do printf '%s com.pico.quickcamera:service%s\n' "$((500+i))" "$i"; i=$((i+1)); done
    ;;
  *) printf 'PID NAME\n412 com.pico.quickcamera:service\n413 vendor.pvrtrackingservice\n' ;;
esac
PS
cat > "$fixture/bin/logcat" <<'LOGCAT'
#!/bin/sh
if [ "$7" = '1' ]; then
  [ "$#" -eq 7 ] && [ "$1" = '-b' ] && [ "$2" = 'main' ] && [ "$3" = '-d' ] && [ "$4" = '-v' ] && [ "$5" = 'threadtime' ] && [ "$7" = '1' ] || { printf 'PRIVATE_CAP_ARGS\n' >&2; exit 90; }
  printf 'called-capability\n' >> "$M28D_FIXTURE/logcat-called"
  case "$M28D_CASE" in cap-unsupported) printf 'logcat: unrecognized option\n' >&2; exit 2 ;; esac
  printf 'PRIVATE_CAP_STDOUT\n'
  printf 'PRIVATE_CAP_STDERR\n' >&2
  exit 0
fi
[ "$#" -eq 7 ] && [ "$1" = '-b' ] && [ "$2" = 'main' ] && [ "$3" = '-d' ] && [ "$4" = '-v' ] && [ "$5" = 'threadtime' ] && [ "$6" = '-t' ] && [ "$7" = '256' ] || { printf 'PRIVATE_SNAPSHOT_ARGS\n' >&2; exit 90; }
printf 'called-snapshot\n' >> "$M28D_FIXTURE/logcat-called"
case "$M28D_CASE" in
  snapshot-failure)
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc, frameCount=25, timestamp=123, monoTimestamp=123\n'
    printf 'PRIVATE_RAW_LOGCAT_STDERR\n' >&2
    exit 7
    ;;
  injected)
    printf 'P3A28D\tEVENT\t412\t10-19\t18:52:31.754\t17\t25\t123\t123\tCSLTimestampTypeQtimer\n'
    printf 'unrelated PRIVATE_LOG_RECORD\n'
    ;;
  large-noise)
    awk 'BEGIN { s="private-noise"; while (length(s) < 3540) s=s "x"; print s }'
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc, frameCount=25, timestamp=123, monoTimestamp=123\r\n'
    ;;
  frame-max)
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc, frameCount=9223372036854775807, timestamp=123, monoTimestamp=123\n'
    ;;
  frame-over)
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc, frameCount=9223372036854775808, timestamp=123, monoTimestamp=123\n'
    ;;
  exact-40|over-40)
    count=21; [ "$M28D_CASE" = exact-40 ] || count=22
    i=0; while [ "$i" -lt "$count" ]; do
      pid=$((500 + i % 16))
      printf '10-19 18:52:31.754 %s 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=%s, linkhdl:0xabc, frameCount=%s, timestamp=%s, monoTimestamp=%s\n' "$pid" "$i" "$i" "$i" "$i"
      i=$((i+1))
    done
    ;;
  *)
    printf '10-19 18:52:31.754 412 555 I CamX: [ INFO] CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc, frameCount=25, timestamp=1234567890123, monoTimestamp=1234567890123\r\n'
    ;;
esac
LOGCAT
cat > "$fixture/bin/awk" <<'AWK'
#!/bin/sh
if [ "$M28D_CASE" = awk-failure ]; then printf 'PRIVATE_AWK_STDOUT\n'; printf 'PRIVATE_AWK_STDERR\n' >&2; exit 4; fi
if [ "$M28D_CASE" = awk-incompatible ]; then
  n=0; [ -f "$M28D_FIXTURE/awk-count" ] && n=$(cat "$M28D_FIXTURE/awk-count")
  n=$((n+1)); printf '%s\n' "$n" > "$M28D_FIXTURE/awk-count"
  if [ "$n" -eq 3 ]; then printf 'PRIVATE_RAW_INCOMPATIBLE_AWK_OUTPUT\n'; exit 0; fi
fi
exec /usr/bin/awk "$@"
AWK
chmod 700 "$fixture/bin/ps" "$fixture/bin/logcat" "$fixture/bin/awk"
'@
$setup = $setup.Replace('__FIXTURE__', $fixture)
$setupRun = Invoke-LocalWsl $setup
if ($setupRun.ExitCode -ne 0) { throw 'Could not prepare synthetic POSIX fixtures' }

try {
    foreach ($entry in @(@('PROBE_SCRIPT_BYTES', $probeB64), @('CAPABILITY_SCRIPT_BYTES', $capabilityB64), @('SHELL_V2_SCRIPT_BYTES', $shellV2B64))) {
        $content64 = $entry[1]
        $script = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($content64))
        $syntax = Invoke-LocalWsl ("/bin/sh -n <<'P3A28D_SCRIPT'`n" + $script + "`nP3A28D_SCRIPT`n")
        if ($syntax.ExitCode -ne 0) { throw "Fixed POSIX script $($entry[0]) failed /bin/sh -n" }
    }

    $v2 = Invoke-ScriptFixture $fixture 'success' $shellV2B64
    if ($v2.ExitCode -ne 23 -or $v2.Stdout -ne "P3A28D`tSHELL_V2`tOK`n" -or $v2.Stderr.Length -ne 0) { throw 'POSIX shell-v2 status probe failed' }

    $cap = Invoke-ScriptFixture $fixture 'success' $capabilityB64
    if ((Get-ParsedCapability $cap) -ne 'READY' -or $cap.Stdout -ne "P3A28D`tCAPABILITY`tLOGCAT`tOPTIONS_OK`n" -or $cap.Stderr.Length -ne 0) { throw 'Fixed logcat option capability result did not round-trip cleanly' }
    if ($cap.Stdout.Contains('PRIVATE') -or $cap.Stderr.Contains('PRIVATE')) { throw 'Capability probe leaked logcat bytes' }
    $unsupported = Invoke-ScriptFixture $fixture 'cap-unsupported' $capabilityB64
    if ((Get-ParsedCapability $unsupported) -ne 'LOGCAT_CAPABILITY_BLOCKED' -or $unsupported.Stdout.Contains('unrecognized') -or $unsupported.Stderr.Length -ne 0) { throw 'Unsupported logcat output was not safely classified' }

    $success = Invoke-ScriptFixture $fixture 'success' $probeB64
    $parsed = Get-ParsedProbe $success
    if ($success.ExitCode -ne 0 -or $success.Stderr.Length -ne 0 -or $parsed.status -ne 'CALLBACK_LOG_OBSERVED') { throw 'Synthetic callback did not pass shell-to-parser round-trip' }
    if ($success.Stdout.Contains('0xabc') -or $success.Stdout.Contains('CamX') -or $success.Stdout.Contains('PRIVATE')) { throw 'Filtered probe leaked pointer, tag, or unrelated log text' }
    if (-not $success.Stdout.Contains("P3A28D`tEVENT`t412")) { throw 'Probe did not emit real tab-delimited protocol' }

    $noise = Invoke-ScriptFixture $fixture 'large-noise' $probeB64
    $noiseParsed = Get-ParsedProbe $noise
    if ($noiseParsed.status -ne 'CALLBACK_LOG_OBSERVED' -or $noise.Stdout.Contains('private-noise') -or $noise.Stdout.Length -gt 4096) { throw '3,540-byte source fixture was not filtered before host output' }
    $injected = Invoke-ScriptFixture $fixture 'injected' $probeB64
    $injectedParsed = Get-ParsedProbe $injected
    if ($injectedParsed.status -ne 'NO_MATCHING_LOG_RECORDS_OBSERVED' -or $injected.Stdout.Contains('P3A28D`tEVENT') -or $injected.Stdout.Contains('PRIVATE')) { throw 'Log-injected protocol text bypassed the fixed event filter' }

    $frameMax = Get-ParsedProbe (Invoke-ScriptFixture $fixture 'frame-max' $probeB64)
    if ($frameMax.status -ne 'CALLBACK_LOG_OBSERVED' -or $frameMax.records[-1].frame_count_label -ne '9223372036854775807') { throw '64-bit frameCount boundary was not retained' }
    $frameOverRun = Invoke-ScriptFixture $fixture 'frame-over' $probeB64
    $frameOver = Get-ParsedProbe $frameOverRun
    if ($frameOver.error_code -ne 'MALFORMED_PROTOCOL_RECORD' -or $frameOverRun.Stdout.Contains('9223372036854775808')) { throw 'Out-of-range frameCount escaped remote filter' }

    $exact = Get-ParsedProbe (Invoke-ScriptFixture $fixture 'exact-40' $probeB64)
    if ($exact.status -ne 'CALLBACK_LOG_OBSERVED' -or $exact.record_count -ne 40) { throw '40-record cap boundary failed' }
    $over = Get-ParsedProbe (Invoke-ScriptFixture $fixture 'over-40' $probeB64)
    if ($over.error_code -ne 'OUTPUT_LINE_LIMIT') { throw '41st protocol record did not fail closed' }
    $many = Get-ParsedProbe (Invoke-ScriptFixture $fixture 'many-processes' $probeB64)
    if ($many.error_code -ne 'OUTPUT_LINE_LIMIT') { throw '17th process candidate did not fail closed' }

    $failure = Invoke-ScriptFixture $fixture 'snapshot-failure' $probeB64
    $failureParsed = Get-ParsedProbe $failure
    if ($failure.ExitCode -eq 0 -or $failureParsed.error_code -ne 'REMOTE_COMMAND_FAILURE') { throw 'Remote logcat nonzero status was lost' }
    if ($failure.Stdout.Contains('PRIVATE_RAW') -or $failure.Stdout.Contains('requestID=') -or $failure.Stderr.Length -ne 0) { throw 'Raw stdout/stderr escaped a failed remote logcat command' }

    $null = Invoke-LocalWsl "rm -f '$fixture/logcat-called'`n"
    $noProcess = Invoke-ScriptFixture $fixture 'no-process' $probeB64
    if ((Get-ParsedProbe $noProcess).reason -ne 'NO_TARGET_PROCESSES') { throw 'Empty process inventory was not distinct' }
    if (Test-Path -LiteralPath "$fixture/logcat-called") { throw 'Snapshot probe ran logcat with no attributable target process' }
    foreach ($case in @('ps-denied', 'malformed-process', 'awk-failure')) {
        $result = Invoke-ScriptFixture $fixture $case $probeB64
        $safe = Get-ParsedProbe $result
        if ($safe.status -notin @('REMOTE_FILTER_BLOCKED', 'OUTPUT_FRAMING_BLOCKED') -or $result.Stdout -match 'PRIVATE|com\.pico' -or $result.Stderr.Length -ne 0) { throw "$case did not fail closed with safe metadata" }
    }
    $incompatibleAwk = Invoke-ScriptFixture $fixture 'awk-incompatible' $probeB64
    $incompatibleParsed = Get-ParsedProbe $incompatibleAwk
    if ($incompatibleAwk.Stdout -match 'PRIVATE_RAW|CSLTimestampTypeQtimer|requestID=' -or
        $incompatibleAwk.Stderr.Length -ne 0 -or $incompatibleParsed.status -ne 'REMOTE_FILTER_BLOCKED') {
        throw 'Incompatible AWK stdout crossed the remote filter boundary'
    }

    Write-Output 'P3-A M2.8D WSL POSIX integration: fixed stdin scripts, shell-v2 exit 23, CRLF, PID filtering, no raw stdout/stderr, injection, 64-bit frameCount, capability block, 40/41 records, 16/17 processes, nonzero status, empty process and malformed/denied source PASS'
}
finally {
    $null = Invoke-LocalWsl "rm -rf '$fixture'`n"
    Pop-Location
}
