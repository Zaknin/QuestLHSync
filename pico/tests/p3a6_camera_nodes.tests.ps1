param()
$ErrorActionPreference='Stop'
$modulePath=Join-Path $PSScriptRoot '..\tools\P3A6CameraNodes.psm1'
Import-Module $modulePath -Force
$script:checks=0

function Assert-True([bool]$Condition,[string]$Message) {
    $script:checks++
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
}
function Assert-Equal($Actual,$Expected,[string]$Message) {
    $script:checks++
    if ($Actual -cne $Expected) { throw "ASSERTION FAILED: $Message (actual=[$Actual], expected=[$Expected])" }
}
function Assert-VectorEqual([string[]]$Actual,[string[]]$Expected,[string]$Message) {
    $script:checks++
    if ($Actual.Count -ne $Expected.Count) { throw "ASSERTION FAILED: $Message (arg count $($Actual.Count) != $($Expected.Count))" }
    for ($i=0;$i -lt $Expected.Count;$i++) { if ($Actual[$i] -cne $Expected[$i]) { throw "ASSERTION FAILED: $Message (arg $i differs)" } }
}
function Test-ByteSequence([byte[]]$Bytes,[byte[]]$Needle) {
    if($Needle.Length -eq 0 -or $Bytes.Length -lt $Needle.Length){return $false}
    for($i=0;$i -le $Bytes.Length-$Needle.Length;$i++){
        $match=$true;for($j=0;$j -lt $Needle.Length;$j++){if($Bytes[$i+$j] -ne $Needle[$j]){$match=$false;break}}
        if($match){return $true}
    }
    return $false
}
function Invoke-LocalWsl {
    param([string[]]$LinuxArguments,[string]$StdinText='')
    $wsl=Get-Command wsl.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $start=[Diagnostics.ProcessStartInfo]::new(); $start.FileName=$wsl.Source; $start.UseShellExecute=$false; $start.CreateNoWindow=$true
    $start.RedirectStandardInput=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    foreach($arg in $LinuxArguments){$start.ArgumentList.Add([string]$arg)}
    $process=[Diagnostics.Process]::new();$process.StartInfo=$start
    if(-not $process.Start()){throw 'Could not start local WSL shell'}
    $stderrTask=$process.StandardError.ReadToEndAsync();if($StdinText){$process.StandardInput.Write($StdinText)};$process.StandardInput.Close()
    $memory=[IO.MemoryStream]::new()
    try {
        $process.StandardOutput.BaseStream.CopyTo($memory)
        if(-not $process.WaitForExit(15000)){try{$process.Kill($true)}catch{};throw 'Local POSIX test exceeded 15 seconds'}
        [pscustomobject]@{ExitCode=$process.ExitCode;Bytes=$memory.ToArray();Stderr=$stderrTask.GetAwaiter().GetResult()}
    } finally {$memory.Dispose();$process.Dispose()}
}
function New-FixtureRoot {
    $root='/tmp/p3a6-m2-'+[guid]::NewGuid().ToString('N')
    $setup="mkdir -p '$root/sys/class/video4linux' '$root/sys/real' '$root/dev' '$root/bin'`n"
    $result=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-s') -StdinText $setup
    Assert-Equal $result.ExitCode 0 'Create isolated POSIX fixture root'
    return $root
}
function Invoke-WslSetup([string]$Script) {
    $r=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-s') -StdinText ($Script+"`n")
    Assert-Equal $r.ExitCode 0 "POSIX fixture setup failed: $($r.Stderr)"
}
function Add-SysfsFixtureNode([string]$Root,[string]$Suffix,[string]$Name='Pico Camera',[string]$Index='0',[string]$Dev='81:0') {
    $real="$Root/sys/real/n$Suffix"; $entry="$Root/sys/class/video4linux/video$Suffix"
    $script="mkdir -p '$real'`nln -s '../../real/n$Suffix' '$entry'`nprintf '%s\n' '$Name' > '$real/name'`nprintf '%s\n' '$Index' > '$real/index'`nprintf '%s\n' '$Dev' > '$real/dev'`n"
    Invoke-WslSetup $script
}
function Invoke-GeneratedProbe([ValidateSet('sysfs','dev')][string]$Source,[int]$NodeLimit,[string]$Root,[string]$PathPrefix='',[switch]$TestOnlyLsFixture) {
    $probe=Get-P3A6M2ProbeScript -Source $Source -NodeLimit $NodeLimit
    if($Source -ceq 'sysfs'){$probe=$probe.Replace('/sys/class/video4linux',"$Root/sys/class/video4linux")}
    else{
        if($TestOnlyLsFixture){
            $probe=$probe.Replace('if [ ! -c "$entry" ]; then','if false; then')
            $testQuote=ConvertTo-P3A6M2PosixArgument -Value $probe
            Assert-True (-not (Test-P3A6M2AllowedAdbArguments -Arguments ([string[]]@('shell','sh','-c',$testQuote)))) 'Test-only ls fixture cannot pass production native allowlist'
        }
        $probe=$probe.Replace("root='/dev'","root='$Root/dev'")
    }
    $quoted=ConvertTo-P3A6M2PosixArgument -Value $probe
    $path=if($PathPrefix){$PathPrefix}else{'/usr/bin:/bin'}
    $remote="PATH='$(($path.Replace("'","'\''")))'; export PATH; /bin/sh -c $quoted"
    $r=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',$remote)
    if($r.ExitCode -ne 0){throw "Generated $Source probe failed: $($r.Stderr)"}
    [pscustomobject]@{Bytes=$r.Bytes;Text=[Text.Encoding]::UTF8.GetString($r.Bytes);Script=$probe;Quoted=$quoted}
}
function New-TestApproval([int]$Duration=30,[int]$Observations=40,[bool]$Expired=$false) {
    $now=[DateTime]::UtcNow
    $issued=$now.AddMinutes(-2);$expires=if($Expired){$now.AddMinutes(-1)}else{$now.AddMinutes(10)}
    return [ordered]@{schema='p3a6.hardware_approval.v1';approval_id=('OFFLINE_TEST_'+[guid]::NewGuid().ToString('N').Substring(0,8));device='Pico 4 Pro';approved_actions=@('read-only-camera-node-metadata');max_duration_seconds=$Duration;max_observations=$Observations;issued_at_utc=$issued.ToString('yyyy-MM-ddTHH:mm:ssZ');expires_at_utc=$expires.ToString('yyyy-MM-ddTHH:mm:ssZ')}
}
function New-StrictMockExecutor([object[]]$ExpectedVectors,[string[]]$ExpectedResponses,[scriptblock]$OnCall=$null) {
    $mockState=[hashtable]::Synchronized(@{index=0})
    $executor={
        param([string[]]$Arguments,[int]$TimeoutMs)
        if(-not (Test-P3A6M2AllowedAdbArguments -Arguments $Arguments)){throw 'MOCK_REJECTED_BY_NATIVE_ALLOWLIST'}
        if($TimeoutMs -lt 100){throw 'MOCK_TIMEOUT_BUDGET_INVALID'}
        if($mockState.index -ge $ExpectedVectors.Count){throw 'MOCK_UNEXPECTED_EXTRA_COMMAND'}
        $expected=[string[]]$ExpectedVectors[$mockState.index]
        Assert-VectorEqual $Arguments $expected "Native mock exact vector #$($mockState.index+1)"
        if($OnCall){& $OnCall $Arguments $TimeoutMs}
        $response=$ExpectedResponses[$mockState.index]
        $mockState.index++
        [pscustomobject]@{exit_code=0;stdout=$response}
    }.GetNewClosure()
    return [pscustomobject]@{Executor=$executor;State=$mockState}
}

# Native argument allowlist: every fixed operation, both transport modes, and reject command/path injection.
$fixed=@([string[]]@('get-state'))
foreach($key in @('ro.product.model','ro.product.device','ro.product.name','ro.product.manufacturer','ro.build.fingerprint','ro.build.version.release')){$fixed+=,[string[]]@('shell','getprop',$key)}
$fixed+=,[string[]]@('shell','uname','-r')
foreach($source in @('sysfs','dev')){
    $scriptText=Get-P3A6M2ProbeScript -Source $source -NodeLimit 16
    $fixed+=,[string[]]@('shell','sh','-c',(ConvertTo-P3A6M2PosixArgument -Value $scriptText))
}
foreach($vector in $fixed){
    Assert-True (Test-P3A6M2AllowedAdbArguments -Arguments $vector) "Allow exact vector $($vector[0])"
    Assert-True (Test-P3A6M2AllowedAdbArguments -Arguments ([string[]](@('-t','42')+$vector))) 'Allow exact selected numeric transport variant'
}
foreach($nodeLimit in 1..16){
    foreach($source in @('sysfs','dev')){
        $exactScript=Get-P3A6M2ProbeScript -Source $source -NodeLimit $nodeLimit
        $exactVector=[string[]]@('shell','sh','-c',(ConvertTo-P3A6M2PosixArgument -Value $exactScript))
        Assert-True (Test-P3A6M2AllowedAdbArguments -Arguments $exactVector) "Allow fixed $source probe for exact numeric limit $nodeLimit"
        Assert-True (Test-P3A6M2AllowedAdbArguments -Arguments ([string[]](@('-t','42')+$exactVector))) "Allow selected transport for fixed $source probe limit $nodeLimit"
    }
}
foreach($bad in @(
    [string[]]@('shell','su','-c','id'),
    [string[]]@('shell','sh','-c','echo hacked'),
    [string[]]@('shell','getprop','ro.serialno'),
    [string[]]@('shell','getprop','ro.product.model;id'),
    [string[]]@('-t','0','get-state'),
    [string[]]@('-t','42','-s','serial','get-state'),
    [string[]]@('shell','sh','-c',"`$(id)")
)){Assert-True (-not (Test-P3A6M2AllowedAdbArguments -Arguments $bad)) 'Reject unapproved command, path, shell syntax or transport'}
$mutatedScript=Get-P3A6M2ProbeScript sysfs 16
$mutatedArgs=[string[]]@('shell','sh','-c',(ConvertTo-P3A6M2PosixArgument -Value ($mutatedScript.Replace("root='/sys/class/video4linux'","root='/tmp/user-path'"))))
Assert-True (-not (Test-P3A6M2AllowedAdbArguments -Arguments $mutatedArgs)) 'Reject fixture path or modified production script'
$sameHashA=Get-P3A6M2TextSha256 -Text (Get-P3A6M2ProbeScript sysfs 16)
$sameHashB=Get-P3A6M2TextSha256 -Text (Get-P3A6M2ProbeScript sysfs 16)
Assert-Equal $sameHashA $sameHashB 'Probe source digest is deterministic'
Assert-True (-not (Get-P3A6M2ProbeScript sysfs 16).Contains("`r") -and (Get-P3A6M2ProbeScript sysfs 16).EndsWith("`n")) 'Probe bytes are canonical UTF-8/LF with one final newline'

# Missing pinned SDK path fails closed without invoking an executable.
$savedLocalAppData=$env:LOCALAPPDATA
$missingSdk=Join-Path ([IO.Path]::GetTempPath()) ('p3a6-m2-no-sdk-'+[guid]::NewGuid().ToString('N'))
$null=[IO.Directory]::CreateDirectory($missingSdk)
$nativeApproval=New-TestApproval
$nativeToken='P3-A6 APPROVE {0} read-only-camera-node-metadata' -f $nativeApproval.approval_id
try {
    $env:LOCALAPPDATA=$missingSdk
    Assert-Equal (Get-P3A6M2PinnedAdbPath) ([IO.Path]::GetFullPath((Join-Path $missingSdk 'Android\Sdk\platform-tools\adb.exe'))) 'Use only pinned SDK ADB path'
    $gateBlocked=$false;try{Invoke-P3A6M2NativeAdb -Arguments ([string[]]@('get-state')) -TimeoutMs 1000 -Approval $null -OwnerConfirmation ''}catch{$gateBlocked=$_.Exception.Message -match 'BLOCKED_NO_APPROVAL'}
    Assert-True $gateBlocked 'Direct native executor requires the Python approval gate'
    $threw=$false;try{Invoke-P3A6M2NativeAdb -Arguments ([string[]]@('get-state')) -TimeoutMs 1000 -Approval $nativeApproval -OwnerConfirmation $nativeToken}catch{$threw=$_.Exception.Message -match 'BLOCKED_PINNED_ADB_MISSING'}
    Assert-True $threw 'Missing pinned SDK ADB fails before process creation'
} finally {$env:LOCALAPPDATA=$savedLocalAppData;Remove-Item -LiteralPath $missingSdk -Recurse -Force}

# POSIX source fixtures: empty roots, symlink-backed sysfs entries, partial fields, malformed values, permission and limits.
$empty=New-FixtureRoot
try {
    $emptySys=Invoke-GeneratedProbe sysfs 16 $empty
    Assert-True (Test-ByteSequence -Bytes $emptySys.Bytes -Needle ([Text.Encoding]::UTF8.GetBytes("P3A6M2`tSYSFS_SOURCE`tNOT_OBSERVED`n"))) 'Empty sysfs fixture is explicitly not observed'
    $parsed=ConvertFrom-P3A6M2ProbeOutput -ProbeText $emptySys.Text -Source sysfs
    Assert-True ($parsed.valid -and $parsed.source_status -ceq 'NOT_OBSERVED' -and $parsed.nodes.Count -eq 0) 'Empty sysfs parser round-trip'
    $emptyDev=Invoke-GeneratedProbe dev 16 $empty
    $parsedDev=ConvertFrom-P3A6M2ProbeOutput -ProbeText $emptyDev.Text -Source dev
    Assert-True ($parsedDev.valid -and $parsedDev.source_status -ceq 'NOT_OBSERVED') 'Empty dev fixture is not a successful camera inventory'
    $fixtureUid=[Text.Encoding]::UTF8.GetString((Invoke-LocalWsl -LinuxArguments @('--exec','/usr/bin/id','-u')).Bytes).Trim()
    if($fixtureUid -cne '0'){
        Invoke-WslSetup "chmod 000 '$empty/sys/class/video4linux'"
        $deniedRoot=Invoke-GeneratedProbe sysfs 16 $empty
        $deniedRootParsed=ConvertFrom-P3A6M2ProbeOutput $deniedRoot.Text sysfs
        Assert-True ($deniedRootParsed.valid -and $deniedRootParsed.source_status -ceq 'PERMISSION_DENIED') 'Unreadable sysfs source root is explicit permission denied'
        Invoke-WslSetup "chmod 700 '$empty/sys/class/video4linux'; chmod 000 '$empty/dev'"
        $deniedDev=Invoke-GeneratedProbe dev 16 $empty
        $deniedDevParsed=ConvertFrom-P3A6M2ProbeOutput $deniedDev.Text dev
        Assert-True ($deniedDevParsed.valid -and $deniedDevParsed.source_status -ceq 'PERMISSION_DENIED') 'Unreadable /dev source root is explicit permission denied'
        Invoke-WslSetup "chmod 700 '$empty/dev'"
    }
    Assert-True (-not (ConvertFrom-P3A6M2ProbeOutput -ProbeText '' -Source sysfs).valid) 'Empty output is malformed rather than success'
    Assert-True (-not (ConvertFrom-P3A6M2ProbeOutput -ProbeText ($emptySys.Text+"P3A6M2`tSURPRISE`tvalue`n") -Source sysfs).valid) 'Unexpected protocol records fail closed'
    Assert-True (-not (ConvertFrom-P3A6M2ProbeOutput -ProbeText ($emptySys.Text.TrimEnd("`n")) -Source sysfs).valid) 'Truncated protocol framing is rejected'
    Assert-True (-not (ConvertFrom-P3A6M2ProbeOutput -ProbeText "P3A6M2`tSYSFS_SOURCE`tobserved`n" -Source sysfs).valid) 'Protocol status tokens are case-sensitive'
    $lfParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText $emptySys.Text -Source sysfs
    Assert-True ($lfParse.valid -and $lfParse.line_ending_classification -ceq 'LF' -and $lfParse.record_count -eq 1) 'LF protocol records retain strict schema and expose safe framing metadata'
    $emptyOutputParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText '' -Source sysfs
    Assert-True (-not $emptyOutputParse.valid -and $emptyOutputParse.reason -ceq 'OUTPUT_FRAMING' -and $emptyOutputParse.line_ending_classification -ceq 'NONE') 'Empty output is framed as absent rather than misclassified as line-ending data'
    $androidLikeOutput="P3A6M2`tSYSFS_NODE`tvideo0`tname`tOBSERVED`tPICO Camera 0`nP3A6M2`tSYSFS_NODE`tvideo0`tindex`tOBSERVED`t0`nP3A6M2`tSYSFS_NODE`tvideo0`tdev`tOBSERVED`t81:0`nP3A6M2`tSYSFS_SOURCE`tOBSERVED`n"
    $androidLikeCrlf=$androidLikeOutput.Replace("`n","`r`n")
    $crlfParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText $androidLikeCrlf -Source sysfs
    Assert-True ($crlfParse.valid -and $crlfParse.line_ending_classification -ceq 'CRLF' -and $crlfParse.record_count -eq 4 -and $crlfParse.nodes.video0.name -ceq 'PICO Camera 0') 'Android-like CRLF command output parses without relaxing fields'
    Assert-Equal $crlfParse.nodes.video0.node_id 'video0' 'Sysfs parser preserves exact validated videoN identifier'
    $legacyFieldStatus=$androidLikeOutput.Replace("video0`tname`tOBSERVED`tPICO Camera 0", "video0`tname`tUNAVAILABLE`t")
    $legacyFieldStatusParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText $legacyFieldStatus -Source sysfs
    Assert-True (-not $legacyFieldStatusParse.valid -and $legacyFieldStatusParse.reason -ceq 'SYSFS_RECORD') 'Legacy generic sysfs field status is rejected by the bounded M2-v3 protocol'
    $mixedAndroidLike=$androidLikeOutput.Replace("video0`tname`tOBSERVED`tPICO Camera 0`n","video0`tname`tOBSERVED`tPICO Camera 0`r`n")
    $mixedParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText $mixedAndroidLike -Source sysfs
    Assert-True ($mixedParse.valid -and $mixedParse.line_ending_classification -ceq 'MIXED' -and $mixedParse.record_count -eq 4) 'Only valid LF and CRLF boundaries are normalized in a mixed stream'
    $standaloneCrParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText ($emptySys.Text.Replace('SYSFS_SOURCE',"SYSFS`rSOURCE")) -Source sysfs
    Assert-True (-not $standaloneCrParse.valid -and $standaloneCrParse.reason -ceq 'OUTPUT_FRAMING' -and $standaloneCrParse.line_ending_classification -ceq 'INVALID') 'Standalone CR is rejected as malformed framing'
    $controlParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText ($emptySys.Text.Replace('SYSFS_SOURCE',"SYSFS`vSOURCE")) -Source sysfs
    Assert-True (-not $controlParse.valid -and $controlParse.reason -ceq 'OUTPUT_CONTROL') 'Embedded non-protocol control characters are rejected'
    Assert-True ($standaloneCrParse.record_count -eq 0) 'Malformed line endings do not count as parsed records'
    $unexpectedOutput=$androidLikeOutput.Replace("P3A6M2`tSYSFS_SOURCE`tOBSERVED`n","P3A6M2`tSURPRISE`tvalue`nP3A6M2`tSYSFS_SOURCE`tOBSERVED`n")
    $unexpectedParse=ConvertFrom-P3A6M2ProbeOutput -ProbeText $unexpectedOutput -Source sysfs
    Assert-True (-not $unexpectedParse.valid -and $unexpectedParse.reason -ceq 'UNEXPECTED_RECORD' -and $unexpectedParse.record_count -eq 3) 'Unexpected records retain exact parser reason and count only prior valid records'
    Assert-True ($lfParse.PSObject.Properties.Name -contains 'line_ending_classification' -and $lfParse.PSObject.Properties.Name -contains 'record_count') 'Parser diagnostics expose only bounded metadata, not raw output'
    $missing=New-FixtureRoot
    try {
        $missScript=(Get-P3A6M2ProbeScript sysfs 16).Replace('/sys/class/video4linux',"$missing/absent/sysfs")
        $missQuoted=ConvertTo-P3A6M2PosixArgument $missScript
        $missResult=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"sh -c $missQuoted")
        $missParsed=ConvertFrom-P3A6M2ProbeOutput -ProbeText ([Text.Encoding]::UTF8.GetString($missResult.Bytes)) -Source sysfs
        Assert-True ($missParsed.valid -and $missParsed.source_status -ceq 'UNAVAILABLE') 'Missing sysfs root is unavailable, not empty success'
    } finally { $null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$missing'") }
} finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"chmod -R u+rwX '$empty' 2>/dev/null || true; rm -rf -- '$empty'")}

$one=New-FixtureRoot
try {
    Add-SysfsFixtureNode $one '0' 'Pico Camera 0' '0' '81:0'
    $run=Invoke-GeneratedProbe sysfs 16 $one
    $expectedBytes=[Text.Encoding]::UTF8.GetBytes("P3A6M2`tSYSFS_NODE`tvideo0`tname`tOBSERVED`tPico Camera 0`n")
    Assert-True (Test-ByteSequence -Bytes $run.Bytes -Needle $expectedBytes) 'Real shell bytes use 0x09 separators'
    Assert-True (-not (Test-ByteSequence -Bytes $run.Bytes -Needle ([Text.Encoding]::UTF8.GetBytes('P3A6M2\tSYSFS_NODE')))) 'Shell output does not contain literal backslash-t separators'
    $parsed=ConvertFrom-P3A6M2ProbeOutput -ProbeText $run.Text -Source sysfs
    Assert-True ($parsed.valid -and $parsed.source_status -ceq 'OBSERVED') 'Actual shell output passes real PowerShell parser'
    Assert-Equal $parsed.nodes.video0.name 'Pico Camera 0' 'Preserve parsed sysfs name'
    Assert-Equal $parsed.nodes.video0.index '0' 'Preserve parsed sysfs index'
    Assert-Equal $parsed.nodes.video0.dev '81:0' 'Preserve parsed sysfs dev tuple'
    Assert-True $parsed.nodes.video0.metadata_fields_complete 'All three sysfs metadata attributes are observed'
    $nativeQuoted=ConvertTo-P3A6M2PosixArgument (Get-P3A6M2ProbeScript sysfs 16)
    Assert-True (Test-P3A6M2AllowedAdbArguments -Arguments ([string[]]@('shell','sh','-c',$nativeQuoted))) 'Production script exactly matches native allowlist'
    Assert-True (-not (Test-P3A6M2AllowedAdbArguments -Arguments ([string[]]@('shell','sh','-c',$run.Quoted)))) 'Local fixture path never enters the production allowlist'
} finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$one'")}

$multi=New-FixtureRoot
try {
    for($i=0;$i -lt 17;$i++){Add-SysfsFixtureNode $multi ([string]$i) "Cam $i" ([string]$i) "81:$i"}
    $two=Invoke-GeneratedProbe sysfs 2 $multi
    $twoParsed=ConvertFrom-P3A6M2ProbeOutput -ProbeText $two.Text -Source sysfs
    Assert-True ($twoParsed.valid -and $twoParsed.nodes.Count -eq 2 -and $twoParsed.source_status -ceq 'LIMIT_REACHED') 'Node limit emits bounded first nodes and explicit overflow status'
    $sixteen=Invoke-GeneratedProbe sysfs 16 $multi
    $sixteenParsed=ConvertFrom-P3A6M2ProbeOutput -ProbeText $sixteen.Text -Source sysfs
    Assert-True ($sixteenParsed.valid -and $sixteenParsed.nodes.Count -eq 16 -and $sixteenParsed.source_status -ceq 'LIMIT_REACHED') 'Hard per-source limit is 16 with explicit overflow'
    $missingAttrRoot=New-FixtureRoot
    try {
        Add-SysfsFixtureNode $missingAttrRoot '3' 'Partial Node' '3' '81:3'
        Invoke-WslSetup "rm '$missingAttrRoot/sys/real/n3/dev'"
        $partial=Invoke-GeneratedProbe sysfs 16 $missingAttrRoot
        $partialParsed=ConvertFrom-P3A6M2ProbeOutput $partial.Text sysfs
        Assert-True ($partialParsed.valid -and $partialParsed.nodes.video3.fields.dev.status -ceq 'ATTRIBUTE_MISSING' -and -not $partialParsed.nodes.video3.metadata_fields_complete) 'Missing sysfs attribute has a bounded status while other observations survive'
    } finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$missingAttrRoot'")}
    $badRoot=New-FixtureRoot
    try {
        Add-SysfsFixtureNode $badRoot '4' 'Good Name' '4' '81:4'
        Invoke-WslSetup "printf 'line1\nline2\n' > '$badRoot/sys/real/n4/name'; printf '5\n6\n' > '$badRoot/sys/real/n4/index'; printf '%s\n' 'Bad/Name' > '$badRoot/sys/real/n4/dev'"
        $bad=Invoke-GeneratedProbe sysfs 16 $badRoot
        $badParsed=ConvertFrom-P3A6M2ProbeOutput $bad.Text sysfs
        Assert-True ($badParsed.valid -and $badParsed.nodes.video4.fields.name.status -ceq 'INVALID' -and $badParsed.nodes.video4.fields.index.status -ceq 'INVALID' -and $badParsed.nodes.video4.fields.dev.status -ceq 'INVALID') 'Multiline and invalid sysfs values have bounded invalid status codes'
        Assert-True ($null -eq $badParsed.nodes.video4.fields.name.value -and $null -eq $badParsed.nodes.video4.fields.index.value -and $null -eq $badParsed.nodes.video4.fields.dev.value) 'Invalid raw attribute contents are not retained'
        Assert-True (-not $bad.Text.Contains('line1') -and -not $bad.Text.Contains('Bad/Name')) 'Malformed sysfs values are absent from the shell protocol output'
        Invoke-WslSetup "printf '%s\n' 'Bad Name' > '$badRoot/sys/real/n4/name'; printf '%s\n' '4' > '$badRoot/sys/real/n4/index'; printf '%s\n' '81:4' > '$badRoot/sys/real/n4/dev'; chmod 000 '$badRoot/sys/real/n4/name'"
        $denied=Invoke-GeneratedProbe sysfs 16 $badRoot
        $deniedParsed=ConvertFrom-P3A6M2ProbeOutput $denied.Text sysfs
        if($fixtureUid -cne '0'){
            Assert-True ($deniedParsed.valid -and $deniedParsed.nodes.video4.fields.name.status -ceq 'PERMISSION_DENIED' -and $null -eq $deniedParsed.nodes.video4.fields.name.value -and $deniedParsed.nodes.video4.index -ceq '4' -and $deniedParsed.source_status -ceq 'OBSERVED') 'Unreadable attribute denial is explicit, contains no value, and preserves independent observations'
        }
        Invoke-WslSetup "chmod 600 '$badRoot/sys/real/n4/name'; chmod 000 '$badRoot/sys/real/n4';"
        $parentDenied=Invoke-GeneratedProbe sysfs 16 $badRoot
        $parentDeniedParsed=ConvertFrom-P3A6M2ProbeOutput $parentDenied.Text sysfs
        if($fixtureUid -cne '0'){
            Assert-True ($parentDeniedParsed.valid -and $parentDeniedParsed.nodes.video4.fields.name.status -ceq 'PERMISSION_DENIED' -and $parentDeniedParsed.nodes.video4.fields.index.status -ceq 'PERMISSION_DENIED' -and $parentDeniedParsed.source_status -ceq 'PERMISSION_DENIED') 'Unsearchable sysfs node directory is not misclassified as missing attributes'
        }
        Invoke-WslSetup "chmod 700 '$badRoot/sys/real/n4'; printf '%s\n' 'Bad/Name' > '$badRoot/sys/real/n4/name'"
        $slashName=Invoke-GeneratedProbe sysfs 16 $badRoot
        $slashParsed=ConvertFrom-P3A6M2ProbeOutput $slashName.Text sysfs
        Assert-True ($slashParsed.valid -and $slashParsed.nodes.video4.fields.name.status -ceq 'INVALID' -and $null -eq $slashParsed.nodes.video4.name) 'Names containing path separators receive INVALID status and are not recorded'
        $longName='N'*97
        Invoke-WslSetup "printf '%s\n' '$longName' > '$badRoot/sys/real/n4/name'"
        $long=Invoke-GeneratedProbe sysfs 16 $badRoot
        $longParsed=ConvertFrom-P3A6M2ProbeOutput $long.Text sysfs
        Assert-True ($longParsed.valid -and $longParsed.nodes.video4.fields.name.status -ceq 'INVALID') 'Sysfs names above 96 ASCII characters receive INVALID status'
        Invoke-WslSetup "chmod 600 '$badRoot/sys/real/n4/name'; printf 'Bad\tName\n' > '$badRoot/sys/real/n4/name'"
        $control=Invoke-GeneratedProbe sysfs 16 $badRoot
        $controlParsed=ConvertFrom-P3A6M2ProbeOutput $control.Text sysfs
        Assert-True ($controlParsed.valid -and $controlParsed.nodes.video4.fields.name.status -ceq 'INVALID') 'Tab/control in attribute is never emitted as protocol data and receives INVALID status'
    } finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$badRoot'")}
} finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$multi'")}

# /dev metadata: never open nodes; exercise symlink/non-character filtering and Toybox-like ls framing.
$devRoot=New-FixtureRoot
try {
    Invoke-WslSetup "touch '$devRoot/dev/video2'; ln -s video2 '$devRoot/dev/video1'; touch '$devRoot/dev/videoX' '$devRoot/dev/video2bad'"
    $dev=Invoke-GeneratedProbe dev 16 $devRoot
    $devParsed=ConvertFrom-P3A6M2ProbeOutput $dev.Text dev
    Assert-True ($devParsed.valid -and $devParsed.nodes.video1.reason -ceq 'SYMLINK_EXCLUDED' -and $devParsed.nodes.video2.reason -ceq 'UNEXPECTED_TYPE') 'Reject symlinked and non-character /dev candidates'
    Assert-Equal $devParsed.nodes.video1.node_id 'video1' 'Dev parser preserves exact validated videoN identifier'
    Assert-True (-not $dev.Text.Contains('videoX')) 'Ignore names without fully numeric suffixes'
    Assert-True (-not $dev.Text.Contains('video2bad')) 'Ignore suffixes that start numeric but are not fully numeric'
    $devOverflow=New-FixtureRoot
    try {
        for($i=0;$i -lt 17;$i++){Invoke-WslSetup "touch '$devOverflow/dev/video$i'"}
        $devLimited=Invoke-GeneratedProbe dev 16 $devOverflow
        $devLimitedParsed=ConvertFrom-P3A6M2ProbeOutput $devLimited.Text dev
        Assert-True ($devLimitedParsed.valid -and $devLimitedParsed.nodes.Count -eq 16 -and $devLimitedParsed.source_status -ceq 'LIMIT_REACHED') 'Dev source enforces 16-node limit and explicit overflow'
    } finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$devOverflow'")}
    $charRoot=New-FixtureRoot
    try {
        Invoke-WslSetup "touch '$charRoot/dev/video0'"
        $lsDir="$charRoot/bin"
        Invoke-WslSetup "cat > '$lsDir/ls' <<'EOF'`n#!/bin/sh`nprintf 'crw-rw---- 1 1000 1000 81, 0 2026-10-19 12:00 %s\n' `"`$2`"`nEOF`nchmod 700 '$lsDir/ls'"
        $char=Invoke-GeneratedProbe dev 16 $charRoot $lsDir -TestOnlyLsFixture
        $charParsed=ConvertFrom-P3A6M2ProbeOutput $char.Text dev
        Assert-True ($charParsed.valid -and $charParsed.source_status -ceq 'OBSERVED' -and $charParsed.nodes.video0.status -ceq 'OBSERVED' -and $charParsed.nodes.video0.mode -ceq 'crw-rw----' -and $charParsed.nodes.video0.device_number -ceq '81:0') 'Bounded Toybox-shaped mode/owner/device metadata parser is exercised on a local ls fixture'
        Invoke-WslSetup "cat > '$lsDir/ls' <<'EOF'`n#!/bin/sh`nprintf 'unsupported output\n'`nEOF`nchmod 700 '$lsDir/ls'"
        $incompatible=Invoke-GeneratedProbe dev 16 $charRoot $lsDir -TestOnlyLsFixture
        $incompatibleParsed=ConvertFrom-P3A6M2ProbeOutput $incompatible.Text dev
        Assert-True ($incompatibleParsed.valid -and $incompatibleParsed.nodes.video0.status -ceq 'UNAVAILABLE' -and $incompatibleParsed.nodes.video0.reason -ceq 'LS_INCOMPATIBLE') 'Incompatible Toybox listing becomes unavailable without fallback'
        Invoke-WslSetup "cat > '$lsDir/ls' <<'EOF'`n#!/bin/sh`nprintf 'crw-rw---- 1 1000 1000 81, 0 first\ncrw-rw---- 1 1000 1000 81, 0 second\n'`nEOF`nchmod 700 '$lsDir/ls'"
        $multiline=Invoke-GeneratedProbe dev 16 $charRoot $lsDir -TestOnlyLsFixture
        $multiParsed=ConvertFrom-P3A6M2ProbeOutput $multiline.Text dev
        Assert-True ($multiParsed.valid -and $multiParsed.nodes.video0.reason -ceq 'LS_MULTILINE') 'Multiline listing is rejected'
        $missingLs=Invoke-GeneratedProbe dev 16 $charRoot "$charRoot/no-such-bin" -TestOnlyLsFixture
        $missingLsParsed=ConvertFrom-P3A6M2ProbeOutput $missingLs.Text dev
        Assert-True ($missingLsParsed.valid -and $missingLsParsed.nodes.video0.reason -ceq 'LS_FAILED') 'Missing ls is an explicit unavailable field'
    } finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"rm -rf -- '$charRoot'")}
} finally {$null=Invoke-LocalWsl -LinuxArguments @('--exec','/bin/sh','-c',"chmod -R u+rwX '$devRoot' 2>/dev/null || true; rm -rf -- '$devRoot'")}

$correlation=Get-P3A6M2NodeCorrelations -SysfsNodes @(
    [pscustomobject]@{node_id='video3';dev='81:3'},
    [pscustomobject]@{node_id='video4';dev='81:4'}
) -DevNodes @(
    [pscustomobject]@{node_id='video9';status='OBSERVED';device_number='81:3'},
    [pscustomobject]@{node_id='video12';status='OBSERVED';device_number='81:12'}
)
$major81=@($correlation.major_groups | Where-Object major -ceq '81')[0]
Assert-True ($major81.status -ceq 'AMBIGUOUS_BY_MAJOR' -and @($major81.sysfs_node_ids).Count -eq 2 -and @($major81.dev_node_ids).Count -eq 2) 'Shared major groups are explicitly ambiguous and preserve exact node identifiers'
Assert-True ($correlation.exact_device_matches.Count -eq 1 -and $correlation.exact_device_matches[0].sysfs_node_id -ceq 'video3' -and $correlation.exact_device_matches[0].dev_node_id -ceq 'video9' -and $correlation.exact_device_matches[0].device_number -ceq '81:3') 'Synthetic sysfs-to-dev matching requires exact major:minor and retains both videoN identifiers'

# Confirmation rejection paths and scope/expiry never reach the mock ADB executor.
$approval=New-TestApproval
$script:adbTouches=0
$never={param([string[]]$Arguments,[int]$TimeoutMs)$script:adbTouches++;throw 'ADB_MUST_NOT_RUN'}.GetNewClosure()
foreach($case in @(@{response='no';interactive=$true;expected='BLOCKED_CONFIRMATION_REQUIRED'},@{response='';interactive=$true;expected='BLOCKED_CONFIRMATION_REQUIRED'},@{response='YES';interactive=$true;expected='BLOCKED_CONFIRMATION_REQUIRED'},@{response='y';interactive=$true;expected='BLOCKED_CONFIRMATION_REQUIRED'},@{response='yes ';interactive=$true;expected='BLOCKED_CONFIRMATION_REQUIRED'},@{response='yes';interactive=$false;expected='BLOCKED_NON_INTERACTIVE'})){
    $blocked=Invoke-P3A6M2ConfirmedInventory -Approval $approval -Response $case.response -Interactive $case.interactive -AdbExecutor $never
    Assert-Equal $blocked.status $case.expected 'Invalid or non-interactive confirmation rejected'
    Assert-Equal $blocked.adb_command_count 0 'Confirmation failure makes zero ADB calls'
}
$noApproval=Invoke-P3A6M2ConfirmedInventory -Approval $null -Response yes -Interactive $true -AdbExecutor $never
Assert-Equal $noApproval.status 'BLOCKED_NO_APPROVAL' 'Missing approval denied'
$wrongAction=Invoke-P3A6M2ConfirmedInventory -Approval $approval -Response yes -Interactive $true -AdbExecutor $never -Action read-only-inventory
Assert-Equal $wrongAction.status 'BLOCKED_SCOPE_MISMATCH' 'M1 authorization action cannot cross into M2'
$expired=New-TestApproval -Expired $true
$expiredResult=Invoke-P3A6M2ConfirmedInventory -Approval $expired -Response yes -Interactive $true -AdbExecutor $never
Assert-Equal $expiredResult.status 'BLOCKED_EXPIRED' 'Expired approval rejected'
$invalidTransport=Invoke-P3A6M2ConfirmedInventory -Approval $approval -Response yes -Interactive $true -AdbExecutor $never -TransportId '42;id'
Assert-Equal $invalidTransport.status 'BLOCKED_INVALID_TRANSPORT' 'Non-numeric transport selection rejected'
Assert-Equal $script:adbTouches 0 'All rejected approvals and confirmations have zero device-facing executor calls'
$dry=Invoke-P3A6M2DryRun
Assert-True ($dry.status -ceq 'DRY_RUN' -and -not $dry.hardware_accessed -and $dry.adb_command_count -eq 0) 'Module dry-run is device-free'

# End-to-end collector mock: strict vectors pass through native allowlist; output contains only allowlisted metadata.
$successApproval=New-TestApproval -Duration 60 -Observations 100
$nodeLine="P3A6M2`tSYSFS_NODE`tvideo0`tname`tOBSERVED`tPico Camera`nP3A6M2`tSYSFS_NODE`tvideo0`tindex`tOBSERVED`t0`nP3A6M2`tSYSFS_NODE`tvideo0`tdev`tOBSERVED`t81:0`nP3A6M2`tSYSFS_SOURCE`tOBSERVED`n"
$emptyDevText="P3A6M2`tDEV_SOURCE`tNOT_OBSERVED`n"
$observedDevText="P3A6M2`tDEV_NODE`tvideo0`tOBSERVED`tOK`tcrw-rw----`t1000`t1000`t81:0`nP3A6M2`tDEV_SOURCE`tOBSERVED`n"
$expectedVectors=[Collections.Generic.List[object]]::new();$responses=[Collections.Generic.List[string]]::new()
$expectedVectors.Add([string[]]@('get-state'));$responses.Add("device`n")
foreach($pair in @(@('ro.product.model','A8110'),@('ro.product.device','PICOA8110'),@('ro.product.name','Phoenix_ovs'),@('ro.product.manufacturer','Pico'),@('ro.build.fingerprint','PICO/phoenix/phoenix:10/QKQ1.200xxx/eng.build:user/release-keys'),@('ro.build.version.release','10'))){$expectedVectors.Add([string[]]@('shell','getprop',$pair[0]));$responses.Add("$($pair[1])`n")}
$expectedVectors.Add([string[]]@('shell','uname','-r'));$responses.Add("4.14.190-pico`n")
foreach($source in @('sysfs','dev')){$scriptText=Get-P3A6M2ProbeScript $source 16;$expectedVectors.Add([string[]]@('shell','sh','-c',(ConvertTo-P3A6M2PosixArgument $scriptText)));$responses.Add($(if($source -ceq 'sysfs'){$nodeLine}else{$observedDevText}))}
$strict=New-StrictMockExecutor $expectedVectors.ToArray() $responses.ToArray()
$testEvidenceRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-offline-tests-'+[guid]::NewGuid().ToString('N'))
try {
    $collected=Invoke-P3A6M2ConfirmedInventory -Approval $successApproval -Response 'yes' -Interactive $true -AdbExecutor $strict.Executor -OutputRoot $testEvidenceRoot
    Assert-Equal $strict.State.index 10 'Each expected command executed exactly once through strict mock'
    Assert-Equal $collected.adb_command_count 10 'M2 bounded command count is ten'
    Assert-Equal $collected.collection_status 'COMPLETE' 'Complete sysfs and /dev metadata yield a complete node-metadata collection'
    Assert-Equal $collected.observation_count 2 'Sysfs and /dev node entries each count against the observation budget'
    Assert-True (Test-Path -LiteralPath $collected.archive_path) 'Private evidence archive exists after scoped synthetic run'
    $runAcl=Get-Acl -LiteralPath $collected.evidence_directory
    Assert-True $runAcl.AreAccessRulesProtected 'Private evidence run directory blocks inherited ACLs'
    $allowedSids=@($runAcl.Access | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } | Sort-Object -Unique)
    $currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    Assert-True ($allowedSids.Count -eq 2 -and $allowedSids -contains $currentSid -and $allowedSids -contains 'S-1-5-18') 'Private evidence ACL allows only current owner and LocalSystem'
    $marker=Get-Content -LiteralPath $collected.marker_path -Raw | ConvertFrom-Json
    Assert-Equal $marker.archive_sha256 (Get-FileHash $collected.archive_path -Algorithm SHA256).Hash.ToLowerInvariant() 'Final marker binds archive SHA-256'
    $evidence=Get-Content -LiteralPath (Join-Path $collected.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
    Assert-Equal $evidence.schema 'p3a6.m2.node_inventory.v2' 'Evidence schema revision reflects node identifiers and correlation fields'
    Assert-Equal $evidence.identity_status 'PHOENIX_SOFTWARE_IDENTITY_VERIFIED_OWNER_BOUND' 'Exact software identity tuple is recorded with owner-bound qualification'
    Assert-Equal $evidence.owner_declared_hardware_variant 'Pico 4 Pro' 'Owner-declared hardware fact remains separate from Android tuple'
    Assert-True ($evidence.identity_provenance -match 'not cryptographic attestation') 'Software tuple is not described as cryptographic attestation'
    Assert-Equal $evidence.software_identity['ro.product.model'].value 'A8110' 'Record observed model value'
    Assert-Equal $evidence.limits.duration_seconds 30 'Collector caps approval duration at 30 seconds'
    Assert-Equal $evidence.limits.observations 40 'Collector caps approval observations at 40'
    Assert-True ($evidence.source_hashes.collector_module_sha256 -cmatch '^[0-9a-f]{64}$' -and $evidence.source_hashes.runner_sha256 -cmatch '^[0-9a-f]{64}$') 'Evidence includes collector and runner SHA-256 digests'
    Assert-Equal $evidence.source_hashes.collector_module_sha256 (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot '..\tools\P3A6CameraNodes.psm1') -Algorithm SHA256).Hash.ToLowerInvariant() 'Evidence collector digest matches source file'
    Assert-Equal $evidence.sources.sysfs.build_identity $evidence.build.fingerprint.value 'Node source evidence binds observed build fingerprint'
    Assert-Equal $evidence.sources.sysfs.nodes[0].metadata_fields_complete $true 'Evidence reports attribute completeness without claiming device identity'
    Assert-Equal $evidence.sources.sysfs.nodes[0].node_id 'video0' 'Serialized sysfs evidence preserves its exact videoN identifier'
    Assert-Equal $evidence.sources.dev.nodes[0].node_id 'video0' 'Serialized /dev evidence preserves its exact videoN identifier'
    Assert-True ($evidence.node_correlations.exact_device_matches.Count -eq 1 -and $evidence.node_correlations.exact_device_matches[0].sysfs_node_id -ceq 'video0' -and $evidence.node_correlations.exact_device_matches[0].dev_node_id -ceq 'video0') 'Private evidence includes bounded exact device-tuple correlation while retaining source identifiers'
    $evidenceJson=Get-Content -LiteralPath (Join-Path $collected.evidence_directory 'evidence.json') -Raw
    Assert-True ($evidenceJson -match '"observed_at_utc"\s*:\s*"\d{4}-\d{2}-\d{2}T[^\"]+Z"') 'Node source evidence includes UTC observation time'
    Assert-True (-not $evidence.safety_flags.exact_time -and -not $evidence.safety_flags.mapping_verified -and -not $evidence.safety_flags.pose_verified -and -not $evidence.safety_flags.shared_buffer_identity_verified -and -not $evidence.safety_flags.frame_meta_bridge_verified -and -not $evidence.safety_flags.live_lighthouse_correction_allowed -and -not $evidence.safety_flags.physical_event_verified) 'All timing, mapping, bridge, physical-event and Lighthouse gates remain false'
    $json=Get-Content -LiteralPath (Join-Path $collected.evidence_directory 'evidence.json') -Raw
    foreach($privateName in @('serial_number','ro.serialno','wifi_mac','bluetooth_address','image_path','frame_pixels')){Assert-True (-not $json.Contains($privateName)) "Evidence excludes prohibited field $privateName"}
    Assert-True (-not $json.Contains('PICO_USER_PRIVATE_SENTINEL')) 'Evidence does not contain unrequested personal data'

    $emptyVectors=[Collections.Generic.List[object]]::new();$emptyResponses=[Collections.Generic.List[string]]::new()
    foreach($i in 0..7){$emptyVectors.Add($expectedVectors[$i]);$emptyResponses.Add($responses[$i])}
    foreach($source in @('sysfs','dev')){$probeIndex=if($source -ceq 'sysfs'){8}else{9};$emptyVectors.Add($expectedVectors[$probeIndex]);$emptyResponses.Add("P3A6M2`t$($source.ToUpperInvariant())_SOURCE`tNOT_OBSERVED`n")}
    $emptyMock=New-StrictMockExecutor $emptyVectors.ToArray() $emptyResponses.ToArray()
    $emptyEvidenceRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-empty-inventory-'+[guid]::NewGuid().ToString('N'))
    try {
        $emptyResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $emptyMock.Executor -OutputRoot $emptyEvidenceRoot
        Assert-Equal $emptyResult.collection_status 'PARTIAL_LIMITATIONS' 'No visible nodes is not a successful empty inventory'
        Assert-Equal $emptyResult.observation_count 0 'Empty sources produce zero node observations'
        $emptyEvidence=Get-Content -LiteralPath (Join-Path $emptyResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $emptyEvidence.sources.sysfs.status 'NOT_OBSERVED' 'Empty sysfs source remains explicitly not observed'
        Assert-Equal $emptyEvidence.sources.dev.status 'NOT_OBSERVED' 'Empty /dev source remains explicitly not observed'
    } finally {if(Test-Path -LiteralPath $emptyEvidenceRoot){Remove-Item -LiteralPath $emptyEvidenceRoot -Recurse -Force}}

    $oneSourceVectors=[Collections.Generic.List[object]]::new();$oneSourceResponses=[Collections.Generic.List[string]]::new()
    foreach($i in 0..7){$oneSourceVectors.Add($expectedVectors[$i]);$oneSourceResponses.Add($responses[$i])}
    $oneSourceVectors.Add($expectedVectors[8]);$oneSourceResponses.Add($nodeLine)
    $oneSourceVectors.Add($expectedVectors[9]);$oneSourceResponses.Add($emptyDevText)
    $oneSourceMock=New-StrictMockExecutor $oneSourceVectors.ToArray() $oneSourceResponses.ToArray()
    $oneSourceRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-one-source-'+[guid]::NewGuid().ToString('N'))
    try {
        $oneSourceResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $oneSourceMock.Executor -OutputRoot $oneSourceRoot
        Assert-Equal $oneSourceResult.collection_status 'PARTIAL_LIMITATIONS' 'One empty source prevents a successful complete inventory'
        $oneSourceEvidence=Get-Content -LiteralPath (Join-Path $oneSourceResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $oneSourceEvidence.sources.sysfs.nodes[0].name 'Pico Camera' 'Observed source values remain preserved when the other source is empty'
        Assert-Equal $oneSourceEvidence.sources.dev.status 'NOT_OBSERVED' 'Empty second source remains explicitly not observed'
    } finally {if(Test-Path -LiteralPath $oneSourceRoot){Remove-Item -LiteralPath $oneSourceRoot -Recurse -Force}}

    $partialSourceVectors=[Collections.Generic.List[object]]::new();$partialSourceResponses=[Collections.Generic.List[string]]::new()
    foreach($i in 0..7){$partialSourceVectors.Add($expectedVectors[$i]);$partialSourceResponses.Add($responses[$i])}
    $partialSourceVectors.Add($expectedVectors[8]);$partialSourceResponses.Add($partial.Text)
    $partialSourceVectors.Add($expectedVectors[9]);$partialSourceResponses.Add($observedDevText)
    $partialSourceMock=New-StrictMockExecutor $partialSourceVectors.ToArray() $partialSourceResponses.ToArray()
    $partialSourceRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-partial-source-'+[guid]::NewGuid().ToString('N'))
    try {
        $partialSourceResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $partialSourceMock.Executor -OutputRoot $partialSourceRoot
        Assert-Equal $partialSourceResult.collection_status 'PARTIAL_LIMITATIONS' 'A missing sysfs attribute prevents a complete inventory even when /dev metadata is observed'
        $partialSourceEvidence=Get-Content -LiteralPath (Join-Path $partialSourceResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $partialSourceEvidence.sources.sysfs.nodes[0].name 'Partial Node' 'Independently observed sysfs value survives a missing attribute'
        Assert-Equal $partialSourceEvidence.sources.sysfs.nodes[0].metadata_fields_complete $false 'Partial sysfs record does not claim all allowed attributes were observed'
        Assert-Equal $partialSourceEvidence.sources.dev.nodes[0].status 'OBSERVED' 'Independent /dev metadata remains available in partial evidence'
    } finally {if(Test-Path -LiteralPath $partialSourceRoot){Remove-Item -LiteralPath $partialSourceRoot -Recurse -Force}}

    $wrongVectors=[Collections.Generic.List[object]]::new();$wrongResponses=[Collections.Generic.List[string]]::new()
    foreach($i in 0..4){$wrongVectors.Add($expectedVectors[$i]);$wrongResponses.Add($(if($i -eq 2){"PICOA8120`n"}else{$responses[$i]}))}
    $wrongMock=New-StrictMockExecutor $wrongVectors.ToArray() $wrongResponses.ToArray()
    $wrongRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-wrong-identity-'+[guid]::NewGuid().ToString('N'))
    try {
        $wrongResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $wrongMock.Executor -OutputRoot $wrongRoot
        Assert-Equal $wrongResult.collection_status 'BLOCKED_UNEXPECTED_DEVICE' 'Mismatching four-property tuple is fail-closed'
        Assert-Equal $wrongResult.adb_command_count 5 'Wrong device identity stops before build and node probes'
        Assert-Equal $wrongMock.State.index 5 'Mismatch test exact vectors stop at identity boundary'
    } finally {if(Test-Path -LiteralPath $wrongRoot){Remove-Item -LiteralPath $wrongRoot -Recurse -Force}}

    $malformedVectors=[object[]]@($expectedVectors[0],$expectedVectors[1])
    $malformedMock=New-StrictMockExecutor $malformedVectors ([string[]]@("device`n","A8110`nPICOA8110`n"))
    $malformedRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-malformed-'+[guid]::NewGuid().ToString('N'))
    try {
        $malformedResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $malformedMock.Executor -OutputRoot $malformedRoot
        Assert-Equal $malformedResult.collection_status 'PARTIAL_UNEXPECTED_OUTPUT' 'Multiline Android property output fails closed'
        Assert-Equal $malformedResult.adb_command_count 2 'Malformed identity output stops before later commands'
        $malformedEvidence=Get-Content -LiteralPath (Join-Path $malformedResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $malformedEvidence.software_identity['ro.product.model'].status 'UNAVAILABLE' 'Malformed identity value is recorded unavailable without retaining raw text'
        Assert-Equal $malformedEvidence.software_identity['ro.product.device'].status 'NOT_OBSERVED' 'Identity command not reached after malformed output stays explicitly not observed'
        Assert-Equal $malformedEvidence.build.fingerprint.status 'NOT_OBSERVED' 'Build command not reached after malformed identity stays explicitly not observed'
        Assert-Equal $malformedEvidence.kernel.release.status 'NOT_OBSERVED' 'Kernel command not reached after malformed identity stays explicitly not observed'
        Assert-Equal $malformedEvidence.device_state.status 'OBSERVED' 'Successful get-state remains independently observed before later failure'
    } finally {if(Test-Path -LiteralPath $malformedRoot){Remove-Item -LiteralPath $malformedRoot -Recurse -Force}}

    $protocolFailureText=$androidLikeOutput.Replace("`n","`r`n").Replace("P3A6M2`tSYSFS_SOURCE`tOBSERVED`r`n","P3A6M2`tUNKNOWN_PRIVATE_SENTINEL`tDO_NOT_PERSIST`r`nP3A6M2`tSYSFS_SOURCE`tOBSERVED`r`n")
    $protocolResponses=[string[]]$responses.ToArray();$protocolResponses[8]=$protocolFailureText
    $protocolMock=New-StrictMockExecutor $expectedVectors.ToArray() $protocolResponses
    $protocolRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-parser-diagnostics-'+[guid]::NewGuid().ToString('N'))
    try {
        $protocolResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $protocolMock.Executor -OutputRoot $protocolRoot
        Assert-Equal $protocolResult.collection_status 'PARTIAL_UNEXPECTED_OUTPUT' 'Malformed sysfs output remains a parser failure'
        Assert-Equal $protocolResult.adb_command_count 9 'Parser failure at sysfs prevents the /dev probe'
        Assert-Equal $protocolMock.State.index 9 'Only the exact nine commands before failed sysfs parsing are executed'
        $protocolEvidencePath=Join-Path $protocolResult.evidence_directory 'evidence.json'
        $protocolEvidenceJson=Get-Content -LiteralPath $protocolEvidencePath -Raw
        $protocolEvidence=ConvertFrom-Json -InputObject $protocolEvidenceJson -AsHashtable
        Assert-Equal $protocolEvidence.parser_diagnostics.failed_source 'sysfs' 'Private diagnostics identify the failed source'
        Assert-Equal $protocolEvidence.parser_diagnostics.normalized_line_ending_classification 'CRLF' 'Private diagnostics classify CRLF before parser normalization'
        Assert-Equal $protocolEvidence.parser_diagnostics.parsed_record_count 3 'Private diagnostics count only records accepted before failure'
        Assert-Equal $protocolEvidence.parser_diagnostics.parser_error_code 'UNEXPECTED_RECORD' 'Private evidence preserves the parser rejection reason'
        Assert-Equal $protocolEvidence.sources.sysfs.status 'UNAVAILABLE' 'Malformed source is explicitly unavailable while valid earlier records are not published as inventory'
        Assert-Equal $protocolEvidence.sources.sysfs.parser_error_code 'UNEXPECTED_RECORD' 'Source record carries its bounded parser error code'
        Assert-True (-not $protocolEvidenceJson.Contains('UNKNOWN_PRIVATE_SENTINEL') -and -not $protocolEvidenceJson.Contains('DO_NOT_PERSIST')) 'Malformed stdout is not persisted in private evidence'
        Assert-True ($protocolEvidence.collector_revision -ceq 'P3-A6-M2-v3' -and -not ($protocolEvidence.PSObject.Properties.Name -contains 'stdout')) 'Diagnostic schema revision excludes raw stdout'
    } finally {if(Test-Path -LiteralPath $protocolRoot){Remove-Item -LiteralPath $protocolRoot -Recurse -Force}}

    $framingFailureText=$androidLikeOutput.Replace("PICO Camera 0","PICO Camera 0`rBROKEN").Replace("`n","`r`n")
    $framingResponses=[string[]]$responses.ToArray();$framingResponses[8]=$framingFailureText
    $framingMock=New-StrictMockExecutor $expectedVectors.ToArray() $framingResponses
    $framingRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-framing-diagnostics-'+[guid]::NewGuid().ToString('N'))
    try {
        $framingResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $framingMock.Executor -OutputRoot $framingRoot
        $framingEvidence=Get-Content -LiteralPath (Join-Path $framingResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $framingResult.collection_status 'PARTIAL_UNEXPECTED_OUTPUT' 'Standalone CR at sysfs boundary fails closed'
        Assert-Equal $framingEvidence.parser_diagnostics.failed_source 'sysfs' 'Framing diagnostic identifies sysfs source'
        Assert-Equal $framingEvidence.parser_diagnostics.normalized_line_ending_classification 'INVALID' 'Framing diagnostic records invalid line-ending classification'
        Assert-Equal $framingEvidence.parser_diagnostics.parsed_record_count 0 'Framing failure before parsing reports zero accepted records'
        Assert-Equal $framingEvidence.parser_diagnostics.parser_error_code 'OUTPUT_FRAMING' 'Private evidence preserves OUTPUT_FRAMING exactly'
        $framingEvidenceJson=Get-Content -LiteralPath (Join-Path $framingResult.evidence_directory 'evidence.json') -Raw
        Assert-True (-not $framingEvidenceJson.Contains('BROKEN')) 'Standalone CR context and malformed stdout are not persisted'
    } finally {if(Test-Path -LiteralPath $framingRoot){Remove-Item -LiteralPath $framingRoot -Recurse -Force}}

    $budgetVectors=[Collections.Generic.List[object]]::new();$budgetResponses=[Collections.Generic.List[string]]::new()
    foreach($i in 0..7){$budgetVectors.Add($expectedVectors[$i]);$budgetResponses.Add($responses[$i])}
    $budgetProbe=Get-P3A6M2ProbeScript sysfs 1
    $budgetVectors.Add([string[]]@('shell','sh','-c',(ConvertTo-P3A6M2PosixArgument $budgetProbe)))
    $budgetResponses.Add($nodeLine)
    $budgetMock=New-StrictMockExecutor $budgetVectors.ToArray() $budgetResponses.ToArray()
    $budgetRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-budget-'+[guid]::NewGuid().ToString('N'))
    try {
        $budgetResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval -Observations 1) -Response yes -Interactive $true -AdbExecutor $budgetMock.Executor -OutputRoot $budgetRoot
        Assert-Equal $budgetResult.observation_count 1 'Collector stops at one approved observation'
        Assert-Equal $budgetResult.adb_command_count 9 'Collector does not call second source after record budget exhaustion'
        $budgetEvidence=Get-Content -LiteralPath (Join-Path $budgetResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $budgetEvidence.sources.dev.status 'LIMIT_REACHED' 'Unqueried source receives explicit limit status'
    } finally {if(Test-Path -LiteralPath $budgetRoot){Remove-Item -LiteralPath $budgetRoot -Recurse -Force}}

    # Each source may inspect 16 nodes while sharing the approved overall observation budget.
    $sixteenSysfsLines=[Collections.Generic.List[string]]::new();$sixteenDevLines=[Collections.Generic.List[string]]::new()
    for($i=0;$i -lt 16;$i++){
        $node="video$i"
        $sixteenSysfsLines.Add("P3A6M2`tSYSFS_NODE`t$node`tname`tOBSERVED`tSynthetic Camera $i")
        $sixteenSysfsLines.Add("P3A6M2`tSYSFS_NODE`t$node`tindex`tOBSERVED`t$i")
        $sixteenSysfsLines.Add("P3A6M2`tSYSFS_NODE`t$node`tdev`tOBSERVED`t81:$i")
        $sixteenDevLines.Add("P3A6M2`tDEV_NODE`t$node`tOBSERVED`tOK`tcrw-rw----`t1000`t1000`t81:$i")
    }
    $sixteenSysfsText=($sixteenSysfsLines -join "`n")+"`nP3A6M2`tSYSFS_SOURCE`tOBSERVED`n"
    $sixteenDevText=($sixteenDevLines -join "`n")+"`nP3A6M2`tDEV_SOURCE`tOBSERVED`n"
    $allocationVectors=[Collections.Generic.List[object]]::new();$allocationResponses=[Collections.Generic.List[string]]::new()
    foreach($i in 0..7){$allocationVectors.Add($expectedVectors[$i]);$allocationResponses.Add($responses[$i])}
    $allocationVectors.Add($expectedVectors[8]);$allocationResponses.Add($sixteenSysfsText)
    $allocationVectors.Add($expectedVectors[9]);$allocationResponses.Add($sixteenDevText)
    $allocationMock=New-StrictMockExecutor $allocationVectors.ToArray() $allocationResponses.ToArray()
    $allocationRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-node-budget-allocation-'+[guid]::NewGuid().ToString('N'))
    try {
        $allocationResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval -Observations 40) -Response yes -Interactive $true -AdbExecutor $allocationMock.Executor -OutputRoot $allocationRoot
        Assert-Equal $allocationResult.collection_status 'COMPLETE' '16 sysfs plus 16 /dev nodes complete within the shared budget of 40'
        Assert-Equal $allocationResult.observation_count 32 'Both sources retain their full 16-node allowance'
        Assert-Equal $allocationResult.adb_command_count 10 'Both source probes run after the identity and build queries'
        Assert-Equal $allocationMock.State.index 10 'The strict native-allowlisted mock accepts both exact 16-node probes'
        $allocationEvidence=Get-Content -LiteralPath (Join-Path $allocationResult.evidence_directory 'evidence.json') -Raw | ConvertFrom-Json -AsHashtable
        Assert-Equal $allocationEvidence.sources.sysfs.status 'OBSERVED' 'Sysfs source is not artificially limited after 16 nodes'
        Assert-Equal $allocationEvidence.sources.dev.status 'OBSERVED' '/dev source is not artificially limited by a halved remainder'
        Assert-True ($allocationEvidence.sources.sysfs.nodes.Count -eq 16 -and $allocationEvidence.sources.dev.nodes.Count -eq 16 -and $allocationEvidence.observation_count -eq 32) 'Evidence contains 16 nodes from each source and no LIMIT_REACHED status'
    } finally {if(Test-Path -LiteralPath $allocationRoot){Remove-Item -LiteralPath $allocationRoot -Recurse -Force}}

    # Transport selection preserves every argument boundary, including the adb shell script.
    $transportVectors=@();foreach($vector in $expectedVectors.ToArray()){$transportVectors+=,[string[]](@('-t','42')+[string[]]$vector)}
    $transportStrict=New-StrictMockExecutor $transportVectors $responses.ToArray()
    $transportEvidence=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-offline-transport-'+[guid]::NewGuid().ToString('N'))
    try {
        $transportResult=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $transportStrict.Executor -OutputRoot $transportEvidence -TransportId '42'
        Assert-Equal $transportResult.collection_status 'COMPLETE' 'Explicit transport collector run completes on fully observed synthetic outputs'
        Assert-Equal $transportStrict.State.index 10 'Every -t 42 command was exact and allowlisted'
    } finally {if($transportEvidence -and (Test-Path -LiteralPath $transportEvidence)){Remove-Item -LiteralPath $transportEvidence -Recurse -Force}}
    # Expiry, invalid command status, unexpected output and execution timeout remain fail-closed.
    $badState={param([string[]]$Arguments,[int]$TimeoutMs)if(-not(Test-P3A6M2AllowedAdbArguments $Arguments)){throw 'allowlist'};[pscustomobject]@{exit_code=1;stdout='device'}}
    $badRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-bad-'+[guid]::NewGuid().ToString('N'))
    try {
        $badRun=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $badState -OutputRoot $badRoot
        Assert-Equal $badRun.collection_status 'PARTIAL_ADB_ERROR' 'Nonzero ADB status is not converted to empty success'
    } finally {if(Test-Path -LiteralPath $badRoot){Remove-Item -LiteralPath $badRoot -Recurse -Force}}
    $timeoutExec={param([string[]]$Arguments,[int]$TimeoutMs)if(-not(Test-P3A6M2AllowedAdbArguments $Arguments)){throw 'allowlist'};throw 'ADB_TIMEOUT'}
    $timeoutRoot=Join-Path $env:LOCALAPPDATA ('PicoLHSync\M2-timeout-'+[guid]::NewGuid().ToString('N'))
    $timeoutRun=Invoke-P3A6M2ConfirmedInventory -Approval (New-TestApproval) -Response yes -Interactive $true -AdbExecutor $timeoutExec -OutputRoot $timeoutRoot
    Assert-Equal $timeoutRun.collection_status 'PARTIAL_TIMEOUT' 'Native timeout is recorded as partial timeout'
    Assert-Equal $timeoutRun.adb_command_count 1 'Timed-out native executor attempt is included in the command count'
    if(Test-Path -LiteralPath $timeoutRoot){Remove-Item -LiteralPath $timeoutRoot -Recurse -Force}
} finally {if(Test-Path -LiteralPath $testEvidenceRoot){Remove-Item -LiteralPath $testEvidenceRoot -Recurse -Force}}

Write-Output "P3-A6-M2 camera node checks: $script:checks PASS"
