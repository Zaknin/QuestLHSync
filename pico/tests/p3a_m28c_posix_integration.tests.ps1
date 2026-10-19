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
        throw 'Local POSIX logcat fixture exceeded its 15-second bound'
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

function Get-ParsedResult {
    param($Run)
    $stdout64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Run.Stdout))
    $stderr64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Run.Stderr))
    $python = "import base64,json; from pico.tools import p3a_m28c_logcat as m; print(json.dumps(m.parse_probe_result(base64.b64decode('$stdout64'),stderr=base64.b64decode('$stderr64'),returncode=$($Run.ExitCode))))"
    $json = & python -c $python
    if ($LASTEXITCODE -ne 0) { throw 'Python parser rejected the WSL protocol bytes unexpectedly' }
    return ($json | ConvertFrom-Json)
}

function Invoke-ProbeCase {
    param([string]$Case, [string]$Fixture, [string]$ScriptBase64)
    $wrapper = @'
set -eu
fixture='__FIXTURE__'
script=$(printf '%s' '__SCRIPT_B64__' | base64 -d) || exit 90
PATH="$fixture/bin:/usr/bin:/bin" M28C_FIXTURE="$fixture" M28C_CASE='__CASE__' /bin/sh -c "$script"
'@
    $wrapper = $wrapper.Replace('__FIXTURE__', $Fixture).Replace('__SCRIPT_B64__', $ScriptBase64).Replace('__CASE__', $Case)
    return Invoke-LocalWsl $wrapper
}

$fixture = '/tmp/p3a-m28c-' + [guid]::NewGuid().ToString('N')
$scriptB64 = & python -c "import base64; from pico.tools import p3a_m28c_logcat as m; print(base64.b64encode(m.PROBE_SCRIPT.encode('ascii')).decode('ascii'))"
if ($LASTEXITCODE -ne 0) { throw 'Could not load reconstructed fixed probe' }

$setup = @'
set -eu
fixture='__FIXTURE__'
mkdir -p "$fixture/bin"
cat > "$fixture/bin/ps" <<'PS'
#!/bin/sh
if [ "$#" -ne 3 ] || [ "$1" != '-A' ] || [ "$2" != '-o' ] || [ "$3" != 'PID,NAME' ]; then
  printf 'PRIVATE_PS_ARG_FAILURE\n' >&2
  exit 90
fi
case "$M28C_CASE" in
  ps-denied) printf 'PRIVATE_PS_FAILURE\n' >&2; exit 2 ;;
  no-process) printf 'PID NAME\n' ;;
  malformed-process) printf 'PID NAME\n412 com.pico.quickcamera;PRIVATE_INJECTION\n' ;;
  many-processes|exactly-40|over-40)
    printf 'PID NAME\n'
    i=0
    while [ "$i" -lt 16 ]; do printf '%s %s\n' "$((500+i))" "com.pico.quickcamera:service$i"; i=$((i+1)); done
    ;;
  *) printf 'PID NAME\n412 com.pico.quickcamera:service\n413 vendor.pvrtrackingservice\n' ;;
esac
PS
cat > "$fixture/bin/logcat" <<'LOGCAT'
#!/bin/sh
if [ "$#" -ne 7 ] || [ "$1" != '-b' ] || [ "$2" != 'main' ] || [ "$3" != '-d' ] || [ "$4" != '-v' ] || [ "$5" != 'threadtime' ] || [ "$6" != '-t' ] || [ "$7" != '256' ]; then
  printf 'PRIVATE_LOGCAT_ARG_FAILURE\n' >&2
  exit 90
fi
printf 'called\n' >> "$M28C_FIXTURE/logcat-called"
case "$M28C_CASE" in
  success)
    printf '10-19 18:52:31.754 412 555 I CamX: [ INFO] CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc frameCount=25, timestamp=1234567890123, monoTimestamp=1234567890123\r\n'
    ;;
  large-noise)
    awk 'BEGIN { line="private-noise"; while (length(line) < 3539) line=line "x"; print line }'
    ;;
  oversized-line)
    awk 'BEGIN { line="10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:"; while (length(line) < 4200) line=line "x"; print line }'
    ;;
  injected)
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc frameCount=25, timestamp=SECRET_PRIVATE_FIELD, monoTimestamp=123\n'
    printf 'P3A28C\tEVENT\t412\t10-19\t18:52:31.754\t17\t25\t123\t123\tCSLTimestampTypeQtimer\n'
    ;;
  noncanonical-number)
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=00017, linkhdl:0xabc frameCount=25, timestamp=123, monoTimestamp=123\n'
    ;;
  pipeline-failure)
    printf '10-19 18:52:31.754 412 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=17, linkhdl:0xabc frameCount=25, timestamp=123, monoTimestamp=123\n'
    printf 'PRIVATE_RAW_PIPELINE_FAILURE_LINE\n'
    printf 'PRIVATE_RAW_STDERR_FAILURE_LINE\n' >&2
    exit 7
    ;;
  unsupported)
    printf 'logcat: unrecognized option -- t\n' >&2
    exit 2
    ;;
  exactly-40|over-40)
    i=0
    count=21
    if [ "$M28C_CASE" = over-40 ]; then count=22; fi
    while [ "$i" -lt "$count" ]; do
      pid=$((500 + i % 16))
      printf '10-19 18:52:31.754 %s 555 I CamX: CSLTimestampTypeQtimer frameMessage:requestID=%s, linkhdl:0xabc frameCount=%s, timestamp=%s, monoTimestamp=%s\n' "$pid" "$i" "$i" "$i" "$i"
      i=$((i+1))
    done
    ;;
esac
LOGCAT
cat > "$fixture/bin/awk" <<'AWK'
#!/bin/sh
if [ "$M28C_CASE" = awk-failure ]; then
  printf 'PRIVATE_AWK_FAILURE\n'
  printf 'PRIVATE_AWK_STDERR\n' >&2
  exit 3
fi
exec /usr/bin/awk "$@"
AWK
chmod 700 "$fixture/bin/ps" "$fixture/bin/logcat" "$fixture/bin/awk"
'@
$setup = $setup.Replace('__FIXTURE__', $fixture)
$setupResult = Invoke-LocalWsl $setup
if ($setupResult.ExitCode -ne 0) { throw 'Could not prepare offline WSL fixtures' }

try {
    $syntax = Invoke-LocalWsl ("/bin/sh -n <<'P3A28C_SCRIPT'`n" + [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$scriptB64)) + "`nP3A28C_SCRIPT`n")
    if ($syntax.ExitCode -ne 0) { throw 'Reconstructed probe failed local POSIX /bin/sh syntax validation' }

    $success = Invoke-ProbeCase 'success' $fixture $scriptB64
    $successParsed = Get-ParsedResult $success
    if ($success.ExitCode -ne 0 -or -not $successParsed.ok -or $successParsed.records.Count -ne 3) {
        $safe = $successParsed | ConvertTo-Json -Compress -Depth 8
        throw "CRLF callback fixture rejected: code=$($successParsed.error_code), records=$($successParsed.record_count), exit=$($success.ExitCode), stdout_bytes=$([Text.Encoding]::UTF8.GetByteCount($success.Stdout)), stderr_bytes=$([Text.Encoding]::UTF8.GetByteCount($success.Stderr)), safe=$safe"
    }
    if ($success.Stdout.Contains('\t') -or -not $success.Stdout.Contains("P3A28C`tEVENT`t412")) { throw 'Probe output framing did not use real tab bytes' }
    if ($success.Stdout.Contains('0xabc') -or $success.Stdout.Contains('CamX:') -or $success.Stdout.Contains('PRIVATE')) { throw 'Probe leaked pointer, tag, or unrelated private log text' }
    if ($success.Stderr.Length -ne 0) { throw 'POSIX probe wrote diagnostics into host stderr' }

    $large = Invoke-ProbeCase 'large-noise' $fixture $scriptB64
    $largeParsed = Get-ParsedResult $large
    if (-not $largeParsed.ok -or $large.Stdout.Contains('private-noise') -or $large.Stdout.Length -gt 4096) { throw 'Approximate 3,540-byte raw fixture was not filtered before host output' }

    $injected = Invoke-ProbeCase 'injected' $fixture $scriptB64
    $injectedParsed = Get-ParsedResult $injected
    if ($injectedParsed.error_code -ne 'MALFORMED_PROTOCOL_RECORD' -or $injected.Stdout.Contains('SECRET_PRIVATE_FIELD') -or $injected.Stdout.Contains('P3A28C`tEVENT`t412`t10-19')) { throw 'Injected raw log fields/protocol rows escaped the allowlist' }

    $noncanonical = Invoke-ProbeCase 'noncanonical-number' $fixture $scriptB64
    $noncanonicalParsed = Get-ParsedResult $noncanonical
    if ($noncanonicalParsed.error_code -ne 'MALFORMED_PROTOCOL_RECORD' -or $noncanonical.Stdout.Contains('requestID=')) { throw 'Remote numeric validation accepted a noncanonical request ID' }

    $failed = Invoke-ProbeCase 'pipeline-failure' $fixture $scriptB64
    $failedParsed = Get-ParsedResult $failed
    if ($failed.ExitCode -eq 0 -or $failedParsed.error_code -ne 'REMOTE_COMMAND_FAILURE') { throw 'Logcat nonzero exit was not propagated' }
    if ($failed.Stdout.Contains('PRIVATE_RAW') -or $failed.Stdout.Contains('requestID=') -or $failedParsed.records) { throw 'Logcat partial output escaped after the pipeline failed' }
    if (-not $failed.Stderr.Contains('PRIVATE_RAW_STDERR_FAILURE_LINE') -or $failed.Stdout.Contains('PRIVATE_RAW_STDERR_FAILURE_LINE')) { throw 'Remote stderr was merged into normalized stdout or not kept as a separate channel' }
    if ((ConvertTo-Json $failedParsed -Compress -Depth 8).Contains('PRIVATE_RAW')) { throw 'Remote stderr leaked into parsed evidence' }

    $unsupported = Invoke-ProbeCase 'unsupported' $fixture $scriptB64
    $unsupportedParsed = Get-ParsedResult $unsupported
    if ($unsupportedParsed.error_code -ne 'LOGCAT_UNSUPPORTED_OPTION' -or $unsupported.Stdout.Contains('unrecognized option') -or (ConvertTo-Json $unsupportedParsed -Compress).Contains('unrecognized option')) { throw 'Unsupported option was not safely classified from separate stderr' }

    $oversized = Invoke-ProbeCase 'oversized-line' $fixture $scriptB64
    $oversizedParsed = Get-ParsedResult $oversized
    if ($oversizedParsed.error_code -ne 'OUTPUT_TRUNCATED' -or $oversized.Stdout -match 'frameMessage|x{100}') { throw 'Oversized raw line was not truncated safely' }

    $cap = Invoke-ProbeCase 'exactly-40' $fixture $scriptB64
    $capParsed = Get-ParsedResult $cap
    if (-not $capParsed.ok -or $capParsed.record_count -ne 40) { throw "40-record boundary code=$($capParsed.error_code), count=$($capParsed.record_count), exit=$($cap.ExitCode)" }

    $overflow = Invoke-ProbeCase 'over-40' $fixture $scriptB64
    $overflowParsed = Get-ParsedResult $overflow
    if ($overflowParsed.error_code -ne 'OUTPUT_LINE_LIMIT' -or $overflow.Stdout.Contains('requestID=')) { throw '41st normalized row was not rejected without exposing logs' }

    $null = Invoke-LocalWsl "rm -f '$fixture/logcat-called'`n"
    $noProcess = Invoke-ProbeCase 'no-process' $fixture $scriptB64
    $noProcessParsed = Get-ParsedResult $noProcess
    if ($noProcessParsed.status -ne 'NOT_OBSERVED' -or (Test-Path -LiteralPath "$fixture/logcat-called")) { throw 'Logcat ran without an attributable target process' }

    foreach ($case in @('ps-denied', 'malformed-process', 'awk-failure')) {
        $result = Invoke-ProbeCase $case $fixture $scriptB64
        $parsed = Get-ParsedResult $result
        if ($parsed.error_code -notin @('REMOTE_COMMAND_FAILURE', 'REMOTE_FILTER_UNVERIFIED')) { throw "$case was not classified fail-closed" }
        if ($result.Stdout -match 'PRIVATE|com\.pico') { throw "$case emitted raw process or helper diagnostics" }
        if ($result.Stderr.Length -ne 0) { throw "$case leaked remote diagnostics through stderr" }
    }

    Write-Output 'P3-A M2.8C reconstructed WSL POSIX integration: sh -c multiline probe, exact ps/logcat vectors, CRLF, filtered 3,540-byte source, injection rejection, pipeline/nonzero status, unsupported option, 40/41 record boundary, process denial/invalidity and awk failure PASS'
}
finally {
    $null = Invoke-LocalWsl "rm -rf '$fixture'`n"
    Pop-Location
}
