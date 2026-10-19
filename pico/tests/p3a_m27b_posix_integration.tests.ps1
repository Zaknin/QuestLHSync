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
            throw 'Local POSIX discovery fixture exceeded 15 seconds'
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

function Assert-ContainsBytes([byte[]]$Bytes, [byte[]]$Needle) {
    for ($i = 0; $i -le $Bytes.Length - $Needle.Length; $i++) {
        $equal = $true
        for ($j = 0; $j -lt $Needle.Length; $j++) {
            if ($Bytes[$i + $j] -ne $Needle[$j]) { $equal = $false; break }
        }
        if ($equal) { return $true }
    }
    return $false
}

$fixture = '/tmp/p3a-m27b-' + [guid]::NewGuid().ToString('N')
$roots = @("$fixture/vendor/lib64", "$fixture/system/lib64", "$fixture/absent/lib64", "$fixture/apex", "$fixture/nonregular/lib64")
$rootsJson = ConvertTo-Json -InputObject $roots -Compress
$pythonCode = "import json; from pico.tools import p3a_m27b_camx_provider as m; print(json.dumps(m._render_discovery_script(tuple(json.loads('$rootsJson')))))"
$probeJson = & python -c $pythonCode
if ($LASTEXITCODE -ne 0) { throw 'Could not render the production POSIX probe' }
$probe = [string]($probeJson | ConvertFrom-Json)
$setup = @"
set -eu
fixture='$fixture'
mkdir -p "`$fixture/vendor/lib64" "`$fixture/system/lib64"
mkdir -p "`$fixture/apex/pkg/lib64"
mkdir -p "`$fixture/nonregular/lib64/camx_core.so"
: > "`$fixture/vendor/lib64/camx_core.so"
printf 'synthetic ELF target\n' > "`$fixture/system/lib64/libcamx_core.so.1"
ln -s 'libcamx_core.so.1' "`$fixture/system/lib64/camx_core.so"
printf 'synthetic APEX provider\n' > "`$fixture/apex/pkg/lib64/camx_core.so"
"@

try {
    $setupResult = Invoke-LocalWsl $setup
    if ($setupResult.ExitCode -ne 0) { throw "Fixture setup failed: $($setupResult.Stderr)" }
    $linkCheck = Invoke-LocalWsl "find '$fixture/system' -name camx_core.so -print`n"
    if ($linkCheck.ExitCode -ne 0 -or -not [Text.Encoding]::UTF8.GetString($linkCheck.Bytes).Contains('camx_core.so')) {
        throw "Synthetic symlink fixture was not created: $($linkCheck.Stderr)"
    }
    $result = Invoke-LocalWsl $probe
    if ($result.ExitCode -ne 0) { throw "POSIX discovery failed: $($result.Stderr)" }
    $text = [Text.Encoding]::UTF8.GetString($result.Bytes)
    if (-not (Assert-ContainsBytes $result.Bytes ([Text.Encoding]::UTF8.GetBytes("P3A27A`tROOT`t")))) {
        throw 'Probe output lacks literal tab bytes'
    }
    if ($text.Contains('\t')) { throw 'Probe output contains literal backslash+t text' }

    $encoded = [Convert]::ToBase64String($result.Bytes)
    $parserCode = "import base64,json; from pico.tools import p3a_m27b_camx_provider as m; roots=tuple(json.loads('$rootsJson')); print(json.dumps(m.parse_discovery_output(base64.b64decode('$encoded').decode('utf-8'), roots=roots)))"
    $parsedJson = & python -c $parserCode
    if ($LASTEXITCODE -ne 0) { throw 'Python parser rejected actual POSIX probe bytes' }
    $parsed = $parsedJson | ConvertFrom-Json
    if ($parsed.candidates.Count -ne 3) { throw "Parser did not retain regular, symlink, and APEX candidates: $text" }
    if ($parsed.candidates[1].source_path -ne "$fixture/system/lib64/libcamx_core.so.1") {
        throw 'Parser did not preserve the resolved symlink target path'
    }
    if ($parsed.root_status."$fixture/absent/lib64" -ne 'ABSENT') { throw 'Missing root was not explicitly reported' }
    if ($parsed.candidate_limitations.Count -ne 1 -or $parsed.candidate_limitations[0].code -ne 'NOT_REGULAR_FILE') {
        throw 'Exact-path non-regular object was not reported as a bounded candidate limitation'
    }

    # Force the actual POSIX find command to return 1 after producing the system candidate.
    # The probe must retain its stdout path while reporting this root incomplete.
    $partialHeader = @'
find () {
  /usr/bin/find "$@"
  find_exit=$?
  case "$*" in *__PARTIAL_ROOT__*) return 1 ;; esac
  return "$find_exit"
}
'@ -replace '__PARTIAL_ROOT__', "$fixture/system/lib64"
    $partialResult = Invoke-LocalWsl ($partialHeader + "`n" + $probe)
    if ($partialResult.ExitCode -ne 0) { throw "Partial-find POSIX probe failed: $($partialResult.Stderr)" }
    $partialText = [Text.Encoding]::UTF8.GetString($partialResult.Bytes)
    $partialEncoded = [Convert]::ToBase64String($partialResult.Bytes)
    $partialParserCode = "import base64,json; from pico.tools import p3a_m27b_camx_provider as m; roots=tuple(json.loads('$rootsJson')); print(json.dumps(m.parse_discovery_output(base64.b64decode('$partialEncoded').decode('utf-8'), roots=roots)))"
    $partialParsedJson = & python -c $partialParserCode
    if ($LASTEXITCODE -ne 0) { throw 'Parser rejected actual partial-find shell output' }
    $partialParsed = $partialParsedJson | ConvertFrom-Json
    if ($partialParsed.root_status."$fixture/system/lib64" -ne 'FIND_ERROR') {
        throw 'Nonzero find exit was not preserved as FIND_ERROR'
    }
    if ($partialParsed.candidates.Count -ne 3 -or $partialParsed.scan_complete) {
        throw 'Partial root stdout candidates were lost or scan was marked complete'
    }
    if (-not $partialText.Contains("$fixture/system/lib64/camx_core.so")) {
        throw 'Actual find stdout path was not retained in protocol output'
    }

    # Syntax-check the exact production script separately, still with no device access.
    $syntaxJson = & python -c "import json; from pico.tools import p3a_m27b_camx_provider as m; print(json.dumps(m.DISCOVERY_SCRIPT))"
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the fixed production script' }
    $productionScript = [string]($syntaxJson | ConvertFrom-Json)
    $syntax = Invoke-LocalWsl ($productionScript + "`n")
    if ($syntax.ExitCode -ne 0) { throw "Production POSIX script syntax failed: $($syntax.Stderr)" }
    Write-Output 'P3-A M2.7B POSIX integration: real /bin/sh fixture, regular/symlink/APEX paths, partial find stdout with exit 1, tabs, parser round-trip, and production syntax PASS'
}
finally {
    $cleanup = "rm -rf -- '$fixture'`n"
    $null = Invoke-LocalWsl $cleanup
    Pop-Location
}
