param()

$ErrorActionPreference = 'Stop'
$modulePath = Join-Path $PSScriptRoot '..\tools\P3A6Inventory.psm1'
Import-Module $modulePath -Force
$module = Get-Module P3A6Inventory

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
}

function Test-ByteSequence([byte[]]$Bytes, [byte[]]$Needle) {
    if ($Needle.Length -eq 0 -or $Bytes.Length -lt $Needle.Length) { return $false }
    for ($i = 0; $i -le $Bytes.Length - $Needle.Length; $i++) {
        $match = $true
        for ($j = 0; $j -lt $Needle.Length; $j++) {
            if ($Bytes[$i + $j] -ne $Needle[$j]) { $match = $false; break }
        }
        if ($match) { return $true }
    }
    return $false
}

function Invoke-LocalWsl {
    param([string[]]$LinuxArguments, [string]$StdinText = '')

    $wsl = Get-Command wsl.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $wsl.Source
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $LinuxArguments) { $startInfo.ArgumentList.Add([string]$argument) }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw 'Could not start local WSL POSIX shell' }
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if ($StdinText) { $process.StandardInput.Write($StdinText) }
    $process.StandardInput.Close()
    $memory = [IO.MemoryStream]::new()
    try {
        $process.StandardOutput.BaseStream.CopyTo($memory)
        if (-not $process.WaitForExit(15000)) {
            try { $process.Kill($true) } catch { }
            throw 'Local POSIX shell exceeded 15 seconds'
        }
        $stderr = $stderrTask.GetAwaiter().GetResult()
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Bytes = $memory.ToArray(); Stderr = $stderr }
    }
    finally {
        $memory.Dispose()
        $process.Dispose()
    }
}

$root = '/tmp/p3a6-posix-' + [guid]::NewGuid().ToString('N')
$setup = @'
set -eu
root='__ROOT__'
mkdir -p "$root/123/fd" "$root/123/fdinfo" "$root/bin"
: > "$root/123/fd/9"
cat > "$root/bin/readlink" <<'P3A6_EOF'
#!/bin/sh
printf '/dev/video7\n'
P3A6_EOF
cat > "$root/bin/ps" <<'P3A6_EOF'
#!/bin/sh
root='__ROOT__'
if [ "$#" -ne 3 ] || [ "$1" != "-A" ] || [ "$2" != "-o" ] || [ "$3" != "PID,NAME" ]; then exit 99; fi
printf '%s\n' "$*" >> "$root/ps-invocations"
mode=$(cat "$root/ps-mode")
printf '%s\n' "$mode" > "$root/ps-mode-seen"
case "$mode" in
  success) printf 'PID NAME\n123 com.picovr.quickcamera\n124 PVR\n' ;;
  fail) printf 'partial output that must be discarded\n'; exit 7 ;;
  bad-header) printf 'NOT_PID NAME\n123 com.picovr.quickcamera\n' ;;
  *) exit 98 ;;
esac
P3A6_EOF
chmod 700 "$root/bin/readlink" "$root/bin/ps"
printf 'pos: 0\nflags: 02000002\nmnt_id: 55\nino: 1234\n' > "$root/123/fdinfo/9"
printf 'success\n' > "$root/ps-mode"
'@
$setup = $setup.Replace('__ROOT__', $root)
try {
    $setupResult = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-s') -StdinText $setup
    Assert-True ($setupResult.ExitCode -eq 0) "POSIX fixture setup failed: $($setupResult.Stderr)"

    $fdProbe = [string](& $module { Get-P3A6ProbeScript -ProcessId 123 -RecordBudget 32 })
    $quotedGeneratedFdProbe = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $fdProbe
    $generatedFdArgs = @('shell', 'sh', '-c', $quotedGeneratedFdProbe)
    $generatedFdAllowed = & $module { param($adbArgs) Test-P3A6AllowedAdbArguments -Arguments $adbArgs } $generatedFdArgs
    $rawFdArgs = @('shell', 'sh', '-c', $fdProbe)
    $rawFdAllowed = & $module { param($adbArgs) Test-P3A6AllowedAdbArguments -Arguments $adbArgs } $rawFdArgs
    Assert-True ($generatedFdAllowed -and -not $rawFdAllowed) 'Native allowlist must require POSIX quoting for a multiline Android 10 shell argument'
    $fdProbe = $fdProbe.Replace('/proc/', "$root/")

    # Android 10 ADB joins shell argv with spaces. Use the same quote helper as
    # the collector and mirror that join under local /bin/sh without invoking ADB.
    $quotedFdProbe = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $fdProbe
    $remoteFdCommand = "PATH='$root/bin`:/usr/bin`:/bin' " + [string]::Join(' ', @('sh', '-c', $quotedFdProbe))
    $fdResult = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-c', $remoteFdCommand)
    Assert-True ($fdResult.ExitCode -eq 0) "Generated fd probe failed under POSIX sh: $($fdResult.Stderr)"

    $expectedFd = [Text.Encoding]::UTF8.GetBytes("P3A6`tFD`t9`t/dev/video7`n")
    Assert-True (Test-ByteSequence -Bytes $fdResult.Bytes -Needle $expectedFd) 'Generated FD record must contain literal tab bytes (0x09), not backslash+t'
    $literalBackslashT = [Text.Encoding]::UTF8.GetBytes('P3A6\tFD\t')
    Assert-True (-not (Test-ByteSequence -Bytes $fdResult.Bytes -Needle $literalBackslashT)) 'Generated FD record must not contain literal backslash+t separators'

    $fdText = [Text.Encoding]::UTF8.GetString($fdResult.Bytes)
    $parsed = & $module { param($text) Convert-P3A6ProbeOutput -ProbeText $text } $fdText
    Assert-True ($parsed.valid -and $parsed.status -eq 'OBSERVED') 'Real POSIX output must pass Convert-P3A6ProbeOutput'
    Assert-True ($parsed.fds['9'].node -eq '/dev/video7') 'Parser must retain the FD node from real POSIX output'
    Assert-True ($parsed.fds['9'].info['flags'] -eq '02000002' -and $parsed.fds['9'].info['ino'] -eq '1234') 'Parser must retain allowlisted fdinfo from real POSIX output'

    $processProbe = [string](& $module { Get-P3A6ProcessProbeScript -ProcessBudget 10 })
    $quotedGeneratedProcessProbe = & $module { param($text) ConvertTo-P3A6PosixShellArgument -Value $text } $processProbe
    $generatedProcessArgs = @('shell', 'sh', '-c', $quotedGeneratedProcessProbe)
    $generatedProcessAllowed = & $module { param($adbArgs) Test-P3A6AllowedAdbArguments -Arguments $adbArgs } $generatedProcessArgs
    Assert-True $generatedProcessAllowed 'Native allowlist must accept the exact quoted process probe'
    $remoteProcessCommand = "PATH='$root/bin`:/usr/bin`:/bin' " + [string]::Join(' ', @('sh', '-c', $quotedGeneratedProcessProbe))
    $processResult = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-c', $remoteProcessCommand)
    Assert-True ($processResult.ExitCode -eq 0) "Generated process probe failed under POSIX sh: $($processResult.Stderr)"
    $processText = [Text.Encoding]::UTF8.GetString($processResult.Bytes)
    Assert-True ($processText -match '(?m)^123 com\.picovr\.quickcamera\r?$' -and $processText -match '(?m)^124 PVR\r?$') 'Process probe must frame filtered ps rows'
    Assert-True (Test-ByteSequence -Bytes $processResult.Bytes -Needle ([Text.Encoding]::UTF8.GetBytes("P3A6`tPROCESS_STATUS`tOBSERVED`n"))) 'Process success marker must contain literal tab bytes'

    $setPsMode = "printf '%s\n' 'fail' > '$root/ps-mode'`n"
    $null = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-s') -StdinText $setPsMode
    $failedProcessResult = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-c', $remoteProcessCommand)
    Assert-True ($failedProcessResult.ExitCode -eq 0) 'A nonzero ps status must be represented by the protocol, not an empty successful result'
    $failedProcessText = [Text.Encoding]::UTF8.GetString($failedProcessResult.Bytes)
    Assert-True ($failedProcessText -ceq "P3A6`tPROCESS_STATUS`tUNAVAILABLE`n") 'Nonzero ps status must discard partial rows and produce only an unavailable marker'
    $modeSeen = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/cat', "$root/ps-mode-seen")
    Assert-True ([Text.Encoding]::UTF8.GetString($modeSeen.Bytes).Trim() -ceq 'fail') 'Nonzero ps test must exercise the explicit failing ps fixture'

    $setPsMode = "printf '%s\n' 'bad-header' > '$root/ps-mode'`n"
    $null = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-s') -StdinText $setPsMode
    $badHeaderResult = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-c', $remoteProcessCommand)
    Assert-True (Test-ByteSequence -Bytes $badHeaderResult.Bytes -Needle ([Text.Encoding]::UTF8.GetBytes("P3A6`tPROCESS_STATUS`tUNAVAILABLE`n"))) 'Unexpected ps header must produce unavailable, not a successful empty list'
    $modeSeen = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/cat', "$root/ps-mode-seen")
    Assert-True ([Text.Encoding]::UTF8.GetString($modeSeen.Bytes).Trim() -ceq 'bad-header') 'Malformed-header test must exercise the explicit bad-header ps fixture'
    $psInvocations = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/cat', "$root/ps-invocations")
    $psInvocationLines = @([Text.Encoding]::UTF8.GetString($psInvocations.Bytes) -split "`n" | Where-Object { $_ })
    Assert-True ($psInvocationLines.Count -eq 3 -and @($psInvocationLines | Where-Object { $_ -cne '-A -o PID,NAME' }).Count -eq 0) 'Each path must run exactly one ps -A -o PID,NAME command; no fallback is permitted'

    Write-Output 'P3-A6 local POSIX shell integration: FD byte/parser path, Android 10 argv join, and ps framing/errors PASS'
}
finally {
    $cleanup = "rm -rf -- '$root'`n"
    $null = Invoke-LocalWsl -LinuxArguments @('--exec', '/bin/sh', '-s') -StdinText $cleanup
}
