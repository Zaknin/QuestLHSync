$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repoRoot

function Invoke-LocalWsl {
    param([string]$Text)
    $wsl = Get-Command wsl.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $wsl.Source
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($arg in @('--exec', '/bin/sh', '-s')) { $startInfo.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw 'Could not start local WSL /bin/sh' }
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.Write($Text)
    $process.StandardInput.Close()
    $memory = [IO.MemoryStream]::new()
    try {
        $process.StandardOutput.BaseStream.CopyTo($memory)
        if (-not $process.WaitForExit(15000)) {
            try { $process.Kill($true) } catch { }
            throw 'Local POSIX probe exceeded its 15-second fixture bound'
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Bytes = $memory.ToArray()
            Stderr = $stderrTask.GetAwaiter().GetResult()
        }
    }
    finally {
        $memory.Dispose()
        $process.Dispose()
    }
}

function Convert-ProbeOutput {
    param([byte[]]$Bytes)
    $text = [Text.Encoding]::UTF8.GetString($Bytes)
    $encoded = [Convert]::ToBase64String($Bytes)
    $python = "import base64,json; from pico.tools import p3a_m28b_runtime_mapping as m; print(json.dumps(m.parse_probe_output(base64.b64decode('$encoded').decode('utf-8'))))"
    $parsedJson = & python -c $python
    if ($LASTEXITCODE -ne 0) { throw "Python rejected actual POSIX probe bytes: $text" }
    return [pscustomobject]@{ Text = $text; Parsed = ($parsedJson | ConvertFrom-Json) }
}

function Invoke-ProbeCase {
    param([string]$Script, [string]$Fixture, [string]$Case)
    $prefix = @(
        "export PATH='$Fixture/bin':`$PATH",
        "export M28B_FIXTURE='$Fixture'",
        "export M28B_CASE='$Case'"
    ) -join "`n"
    return Invoke-LocalWsl ($prefix + "`n" + $Script + "`n")
}

$fixture = '/tmp/p3a-m28b-' + [guid]::NewGuid().ToString('N')
$procRoot = "$fixture/proc"
$rootsJson = ConvertTo-Json -InputObject $procRoot -Compress
$scriptB64 = & python -c "import base64,json; from pico.tools import p3a_m28b_runtime_mapping as m; print(base64.b64encode(m.render_probe_script_for_fixture(json.loads('$rootsJson')).encode('ascii')).decode('ascii'))"
if ($LASTEXITCODE -ne 0) { throw 'Could not render fixture-only POSIX probe' }
$script = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$scriptB64))
$productionB64 = & python -c "import base64; from pico.tools import p3a_m28b_runtime_mapping as m; print(base64.b64encode(m.PROBE_SCRIPT.encode('ascii')).decode('ascii'))"
if ($LASTEXITCODE -ne 0) { throw 'Could not read fixed production probe' }
$productionScript = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$productionB64))
$statFields = @('S', '1', '1', '1', '0', '-1') + (@('0') * 11) + @('1', '0', '987654')
if ($statFields.Count -ne 20) { throw 'Synthetic /proc stat fixture must contain fields 3 through 22' }
$statLine = "412 (quickcamera) " + ($statFields -join ' ')

$setupLines = @(
    'set -eu',
    "fixture='$fixture'",
    'mkdir -p "$fixture/bin" "$fixture/proc/412"',
    'cat > "$fixture/bin/ps" <<''EOF''',
    '#!/bin/sh',
    'case "$M28B_CASE" in',
    '  absent) printf ''PID NAME\n'' ;;',
    '  exit) rm -rf "$M28B_FIXTURE/proc/412"; printf ''PID NAME\n412 com.picovr.quickcamera:service\n'' ;;',
    '  identity-change) if [ -f "$M28B_FIXTURE/ps-seen" ]; then printf ''PID NAME\n412 com.picovr.quickcamera:changed\n''; else : > "$M28B_FIXTURE/ps-seen"; printf ''PID NAME\n412 com.picovr.quickcamera:service\n''; fi ;;',
    '  *) printf ''PID NAME\n412 com.picovr.quickcamera:service\n'' ;;',
    'esac',
    'EOF',
    'cat > "$fixture/bin/stat" <<''EOF''',
    '#!/bin/sh',
    'case "$3" in */camx_core.so) printf ''45855 112233\n'' ;; */quickcamera.core.so) printf ''45855 445566\n'' ;; *) exit 1 ;; esac',
    'EOF',
    'cat > "$fixture/bin/cat" <<''EOF''',
    '#!/bin/sh',
    'case "$1" in',
    '  */stat) if [ "$M28B_CASE" = reuse ] && [ -f "$M28B_FIXTURE/stat-seen" ]; then /bin/sed ''s/987654$/987655/'' "$1"; else if [ "$M28B_CASE" = reuse ]; then : > "$M28B_FIXTURE/stat-seen"; fi; exec /bin/cat "$@"; fi ;;',
    '  *) exec /bin/cat "$@" ;;',
    'esac',
    'EOF',
    'cat > "$fixture/bin/awk" <<''EOF''',
    '#!/bin/sh',
    'last=',
    'for arg do last=$arg; done',
    'case "$last" in */maps) if [ "$M28B_CASE" = denied ]; then exit 2; fi ;; esac',
    'exec /usr/bin/awk "$@"',
    'EOF',
    'chmod 700 "$fixture/bin/ps" "$fixture/bin/stat" "$fixture/bin/cat" "$fixture/bin/awk"',
    "printf '%s\n' '$statLine' > `"`$fixture/proc/412/stat`"",
    'printf ''unrelated mapping line\n'' > "$fixture/proc/412/maps"'
)
$setupResult = Invoke-LocalWsl ($setupLines -join "`n")
if ($setupResult.ExitCode -ne 0) { throw "WSL fixture setup failed: $($setupResult.Stderr)" }

try {
    $syntax = Invoke-LocalWsl ($productionScript + "`n")
    if ($syntax.ExitCode -ne 0) { throw "Production POSIX syntax failed: $($syntax.Stderr)" }

    $successMapLines = @(
        '7a100000-7a101000 r-xp 00000000 b3:1f 112233 /vendor/lib64/camx_core.so',
        '7a102000-7a103000 r--p 00002000 b3:1f 112233 /vendor/lib64/camx_core.so',
        '7a200000-7a201000 r-xp 00000000 b3:1f 445566 /vendor/lib64/quickcamera.core.so'
    ) -join "`n"
    $writeMaps = "printf '%s\n' '$successMapLines' > '$procRoot/412/maps'`n"
    $writeResult = Invoke-LocalWsl $writeMaps
    if ($writeResult.ExitCode -ne 0) { throw 'Could not prepare multiple-segment maps fixture' }
    $successRun = Invoke-ProbeCase $script $fixture 'success'
    if ($successRun.ExitCode -ne 0) { throw "Success fixture failed: $($successRun.Stderr)" }
    $successParsed = Convert-ProbeOutput $successRun.Bytes
    if ($successParsed.Parsed.mappings.Count -ne 3) { throw "Multiple exact-path mapping segments were not preserved: $($successParsed.Text)" }
    if (-not $successParsed.Text.Contains("P3A28B`tMAP`t412`tcom.picovr.quickcamera:service")) {
        throw 'Actual shell bytes lack tab-delimited process/mapping fields'
    }
    if ($successParsed.Text.Contains('\t')) { throw 'Actual shell output contains literal backslash+t' }
    $successEncoded = [Convert]::ToBase64String($successRun.Bytes)
    $evalCode = "import base64,json; from pico.tools import p3a_m28b_runtime_mapping as m; p=m.parse_probe_output(base64.b64decode('$successEncoded').decode()); print(json.dumps(m.evaluate_mapping_result(p)))"
    $evaluated = & python -c $evalCode | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $evaluated.status -ne 'PASS') { throw 'POSIX output did not round-trip to a correlated synthetic PASS' }

    $denied = Invoke-ProbeCase $script $fixture 'denied'
    if ($denied.ExitCode -ne 0) { throw 'Permission-denial probe failed to return bounded protocol output' }
    $deniedParsed = (Convert-ProbeOutput $denied.Bytes).Parsed
    if ($deniedParsed.scan_status -ne 'PROC_ACCESS_DENIED' -or $deniedParsed.process_statuses[0].status -ne 'PROC_ACCESS_DENIED') {
        throw 'Simulated maps permission denial did not stop with PROC_ACCESS_DENIED'
    }

    $reuse = Invoke-ProbeCase $script $fixture 'reuse'
    if ($reuse.ExitCode -ne 0) { throw 'PID-reuse probe failed to return bounded protocol output' }
    $reuseParsed = (Convert-ProbeOutput $reuse.Bytes).Parsed
    if ($reuseParsed.scan_status -ne 'PID_REUSED' -or $reuseParsed.mappings.Count -ne 0) {
        throw 'Changed process starttime did not discard mappings and stop as PID_REUSED'
    }

    $identityChanged = Invoke-ProbeCase $script $fixture 'identity-change'
    $identityChangedParsed = (Convert-ProbeOutput $identityChanged.Bytes).Parsed
    if ($identityChangedParsed.scan_status -ne 'PROCESS_IDENTITY_CHANGED' -or $identityChangedParsed.mappings.Count -ne 0) {
        throw 'Changed ps PID/name pair was not rejected before accepting mappings'
    }

    $exited = Invoke-ProbeCase $script $fixture 'exit'
    $exitedParsed = (Convert-ProbeOutput $exited.Bytes).Parsed
    if ($exitedParsed.scan_status -ne 'PROCESS_EXITED' -or $exitedParsed.mappings.Count -ne 0) {
        throw 'Disappeared process was not reported as PROCESS_EXITED'
    }

    $missingSetup = "mkdir -p '$procRoot/412'; printf '%s\n' '$statLine' > '$procRoot/412/stat'; printf '%s\n' '7f000000-7f001000 r-xp 00000000 00:01 4 /system/lib64/unrelated.so' > '$procRoot/412/maps'`n"
    if ((Invoke-LocalWsl $missingSetup).ExitCode -ne 0) { throw 'Could not prepare absent-mapping fixture' }
    $missing = Invoke-ProbeCase $script $fixture 'missing'
    $missingParsed = (Convert-ProbeOutput $missing.Bytes).Parsed
    if ($missingParsed.process_statuses[0].status -ne 'NO_TARGET_MAPPING' -or $missingParsed.mappings.Count -ne 0) {
        throw 'Unrelated mapping lines were not filtered to NO_TARGET_MAPPING'
    }

    $malformedSetup = "printf '%s\n' 'BROKEN r-xp 00000000 b3:1f 112233 /vendor/lib64/camx_core.so' > '$procRoot/412/maps'`n"
    if ((Invoke-LocalWsl $malformedSetup).ExitCode -ne 0) { throw 'Could not prepare malformed-mapping fixture' }
    $malformed = Invoke-ProbeCase $script $fixture 'malformed'
    $malformedParsed = (Convert-ProbeOutput $malformed.Bytes).Parsed
    if ($malformedParsed.scan_status -ne 'MALFORMED_MAPS' -or $malformedParsed.mappings.Count -ne 0) {
        throw 'Malformed target mapping was not discarded as MALFORMED_MAPS'
    }

    $limitSetup = @(
        ": > '$procRoot/412/maps'",
        'i=0',
        'while [ "$i" -lt 40 ]; do',
        '  start=$(printf ''%x'' $((0x7a100000 + i * 4096)))',
        '  end=$(printf ''%x'' $((0x7a101000 + i * 4096)))',
        "  printf '%s-%s r-xp 00000000 b3:1f 112233 /vendor/lib64/camx_core.so\n' `$start `$end >> '$procRoot/412/maps'",
        '  i=$((i + 1))',
        'done'
    ) -join "`n"
    $limitSetupResult = Invoke-LocalWsl $limitSetup
    if ($limitSetupResult.ExitCode -ne 0) { throw "Could not prepare record-limit fixture: $($limitSetupResult.Stderr)" }
    $limited = Invoke-ProbeCase $script $fixture 'limit'
    $limitedParsed = (Convert-ProbeOutput $limited.Bytes).Parsed
    if ($limitedParsed.scan_status -ne 'LIMIT_REACHED' -or $limitedParsed.record_count -ne 40) {
        throw "The 40-normalized-record ceiling was not enforced exactly: $($limitedParsed | ConvertTo-Json -Compress)"
    }

    $absentSetup = @(
        "cat > '$fixture/bin/ps' <<'EOF'",
        '#!/bin/sh',
        "printf 'PID NAME\n'",
        'EOF',
        "chmod 700 '$fixture/bin/ps'"
    ) -join "`n"
    if ((Invoke-LocalWsl $absentSetup).ExitCode -ne 0) { throw 'Could not prepare process-absent fixture' }
    $absent = Invoke-ProbeCase $script $fixture 'absent'
    $absentParsed = (Convert-ProbeOutput $absent.Bytes).Parsed
    if ($absentParsed.scan_status -ne 'NO_MATCHING_PROCESSES') { throw "Missing target process was not explicit: $($absentParsed | ConvertTo-Json -Compress)" }

    Write-Output 'P3-A M2.8B WSL POSIX integration: production syntax, real shell tabs/parser round-trip, multiple segments, permission denial, PID reuse/name change/exit, no mapping, malformed maps, 40-record cap, and process absence PASS'
}
finally {
    $null = Invoke-LocalWsl "rm -rf '$fixture'`n"
    Pop-Location
}
