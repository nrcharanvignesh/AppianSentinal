# Installed-app smoke for Appian Sentinel.
# Does not build or install. Launch only after resources\app.asar matches
# -ExpectedAsarSha256. Cleanup kills owned process identities only.
#
# Example:
#   powershell -NoProfile -ExecutionPolicy Bypass -File desktop/scripts/installed-app-smoke.ps1 -ExpectedAsarSha256 <64-hex>

param(
    [Parameter(Mandatory = $true)]
    [string]$ExpectedAsarSha256,
    [string]$WorkspaceDir = "",
    [string]$InstallDir = "",
    [int]$LaunchWaitSec = 120,
    [int]$QuitWaitSec = 20
)

$ErrorActionPreference = "Continue"
$script:Failures = @()
$script:OwnedSnapshot = @()
$script:LaunchedPid = $null
$script:BaselineProcessIds = [System.Collections.Generic.HashSet[int]]::new()
$script:StdoutLog = Join-Path $env:TEMP "sentinel-installed-smoke-out.log"
$script:StderrLog = Join-Path $env:TEMP "sentinel-installed-smoke-err.log"

function Say  ([string]$m) { Write-Host "[INFO] $m" }
function Pass ([string]$m) { Write-Host "[SUCCESS] PASS - $m" }
function Fail ([string]$m) { Write-Host "[ERROR] FAIL - $m"; $script:Failures += $m }

function Get-WorkspaceRoot {
    if ($WorkspaceDir) { return $WorkspaceDir }
    $override = [Environment]::GetEnvironmentVariable('SENTINEL_WORKSPACE_DIR', 'Process')
    if (-not $override) {
        $override = [Environment]::GetEnvironmentVariable('SENTINEL_WORKSPACE_DIR', 'User')
    }
    if ($override) { return $override }
    return Join-Path $env:USERPROFILE 'Documents\AppianSentinel'
}

function Get-InstallRoot {
    if ($InstallDir) { return $InstallDir }
    $fromEnv = [Environment]::GetEnvironmentVariable('SENTINEL_INSTALL_DIR', 'Process')
    if ($fromEnv) { return $fromEnv }
    return Join-Path (Get-WorkspaceRoot) 'install\desktop-app'
}

function Show-Procs ($procs, [string]$label) {
    $list = @($procs)
    if ($list.Count -eq 0) { Say "$label : none"; return }
    Say "$label : $($list.Count) process(es)"
    foreach ($p in $list) {
        $cl = [string]$p.CommandLine
        if ($cl.Length -gt 140) { $cl = $cl.Substring(0, 140) }
        Write-Host ("        pid={0} ppid={1} {2} :: {3}" -f $p.ProcessId, $p.ParentProcessId, $p.Name, $cl)
    }
}

function Get-SentinelProcesses {
    $roots = @(
        (Get-InstallRoot),
        (Get-WorkspaceRoot)
    ) | Select-Object -Unique | ForEach-Object { $_.ToLower() }

    $found = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $hay = (([string]$_.ExecutablePath) + " " + ([string]$_.CommandLine)).ToLower()
        if ($hay -match 'cursor\\resources') { return $false }
        if ($hay -match 'installed-app-smoke\.ps1') { return $false }
        $hit = $false
        foreach ($r in $roots) {
            if ($r -and $hay.Contains($r)) { $hit = $true }
        }
        return $hit
    } | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine, CreationDate)
    if ($script:BaselineProcessIds.Count -gt 0) {
        $found = @($found | Where-Object { -not $script:BaselineProcessIds.Contains([int]$_.ProcessId) })
    }
    return $found
}

function Test-OwnedIdentity ([string]$hay, [int]$port) {
    $install = (Get-InstallRoot).ToLower().TrimEnd('\') + '\'
    $text = $hay.ToLower()
    if (-not $text.StartsWith($install) -and -not $text.Contains($install)) { return $false }
    if ($port -eq 7842) {
        return [bool]($text -match 'appian-sentinel-sidecar(?:\.exe)?')
    }
    if ($port -eq 8888) {
        return [bool]($text -match 'server\.js')
    }
    return [bool]($text -match 'appiansentinel(?:\.exe)?')
}

function Get-PortListeners ([int]$port) {
    $out = & "$env:SystemRoot\System32\netstat.exe" -ano -p TCP 2>$null
    $pids = @()
    foreach ($line in $out) {
        if ($line -notmatch 'LISTENING') { continue }
        $cols = ($line.Trim() -split '\s+')
        if ($cols.Count -lt 5) { continue }
        if (-not $cols[1].EndsWith(":$port")) { continue }
        $pids += $cols[$cols.Count - 1]
    }
    return @($pids | Select-Object -Unique)
}

function Get-ProcessTreeSnapshot ([int]$rootPid) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $owned = [System.Collections.Generic.Dictionary[int, object]]::new()
    $root = $all | Where-Object { [int]$_.ProcessId -eq $rootPid } | Select-Object -First 1
    if (-not $root) { return @() }
    $owned[$rootPid] = $root
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($p in $all) {
            $childPid = [int]$p.ProcessId
            $parentPid = [int]$p.ParentProcessId
            if ($owned.ContainsKey($childPid)) { continue }
            if (-not $owned.ContainsKey($parentPid)) { continue }
            if ($p.CreationDate -lt $owned[$parentPid].CreationDate) { continue }
            $owned[$childPid] = $p
            $changed = $true
        }
    }
    return @($owned.Values | Select-Object ProcessId, ParentProcessId, Name,
        ExecutablePath, CommandLine, CreationDate)
}

function Test-SameProcessAlive ($identity) {
    if (-not $identity) { return $false }
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$identity.ProcessId)" `
        -ErrorAction SilentlyContinue
    return [bool]($current -and
        [string]$current.CreationDate -eq [string]$identity.CreationDate)
}

function Stop-OwnedProcesses {
    $targets = @()
    if ($script:OwnedSnapshot.Count -gt 0) {
        $targets += @($script:OwnedSnapshot | Where-Object { Test-SameProcessAlive $_ })
    }
    $targets += @(Get-SentinelProcesses)
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($p in $targets) {
        $id = [int]$p.ProcessId
        if ($id -le 4 -or $script:BaselineProcessIds.Contains($id)) { continue }
        if (-not $seen.Add($id)) { continue }
        $now = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if (-not $now) { continue }
        if ($p.CreationDate -and [string]$now.CreationDate -ne [string]$p.CreationDate) { continue }
        Say "stopping owned pid=$id ($($p.Name))"
        & "$env:SystemRoot\System32\taskkill.exe" /F /PID $id 2>$null | Out-Null
    }
}

function Maximize-MainWindow ([int]$pid) {
    Add-Type -Namespace SentinelSmoke -Name Native -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
'@ -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.MainWindowHandle -eq [IntPtr]::Zero) { return $false }
    return [SentinelSmoke.Native]::ShowWindow($proc.MainWindowHandle, 3)
}

function Get-DesktopLogPath {
    $dirs = @(
        (Join-Path (Get-WorkspaceRoot) 'logs')
    )
    $fromEnv = [Environment]::GetEnvironmentVariable('SENTINEL_LOG_DIR', 'Process')
    if ($fromEnv) { $dirs = @($fromEnv) + $dirs }
    foreach ($d in ($dirs | Select-Object -Unique)) {
        $candidate = Join-Path $d 'desktop.log'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Write-CapturedLogs {
    foreach ($path in @($script:StdoutLog, $script:StderrLog, (Get-DesktopLogPath))) {
        if (-not $path -or -not (Test-Path -LiteralPath $path)) { continue }
        Say "--- log $path (tail) ---"
        Get-Content -LiteralPath $path -Tail 40 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "        $_" }
    }
}

function Test-ExpectedHash {
    $raw = $ExpectedAsarSha256.Trim()
    if ($raw -notmatch '^[0-9a-fA-F]{64}$') {
        Fail "ExpectedAsarSha256 must be 64 hex characters"
        return $null
    }
    return $raw.ToLowerInvariant()
}

Write-Host "=============================================="
Write-Host " Appian Sentinel - INSTALLED APP SMOKE"
Write-Host "=============================================="

$expected = Test-ExpectedHash
$install = Get-InstallRoot
$exe = Join-Path $install 'AppianSentinel.exe'
$asar = Join-Path $install 'resources\app.asar'
Say "workspace=$(Get-WorkspaceRoot)"
Say "install=$install"
Say "exe=$exe"

$pre = @(Get-SentinelProcesses)
Show-Procs $pre "baseline sentinel processes (left running)"
foreach ($p in $pre) { [void]$script:BaselineProcessIds.Add([int]$p.ProcessId) }
if ($script:BaselineProcessIds.Count -gt 0) {
    Say "preserving $($script:BaselineProcessIds.Count) unrelated baseline process(es)"
}

try {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        Fail "installed exe missing: $exe"
    } else {
        Pass "installed exe present"
    }

    if (-not $expected) {
        # Hash argument already failed closed.
    } elseif (-not (Test-Path -LiteralPath $asar -PathType Leaf)) {
        Fail "installed app.asar missing: $asar"
    } else {
        $actual = (Get-FileHash -LiteralPath $asar -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -eq $expected) {
            Pass "installed app.asar SHA-256 matches $actual"
        } else {
            Fail "stale app.asar: installed SHA-256 $actual, expected $expected; close Appian Sentinel and install again"
        }
    }

    $canLaunch = ($script:Failures.Count -eq 0)
    if (-not $canLaunch) {
        Say "skipping launch because identity gates failed"
    } else {
        Remove-Item $script:StdoutLog, $script:StderrLog -ErrorAction SilentlyContinue
        $env:ELECTRON_ENABLE_LOGGING = "1"
        $env:NODE_OPTIONS = $null
        Say "launching installed exe maximized (wait up to ${LaunchWaitSec}s)"
        # Start-Process forbids -WindowStyle with stdio redirect. Maximize via ShowWindow.
        $launched = Start-Process -FilePath $exe -PassThru `
            -RedirectStandardOutput $script:StdoutLog `
            -RedirectStandardError $script:StderrLog
        $script:LaunchedPid = $launched.Id
        Say "launched pid=$($launched.Id)"

        $ready = $false
        $deadline = (Get-Date).AddSeconds($LaunchWaitSec)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 2
            if (-not (Get-Process -Id $launched.Id -ErrorAction SilentlyContinue)) {
                $replacement = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                    Where-Object { [string]$_.ExecutablePath -eq $exe } |
                    Select-Object -First 1
                if ($replacement) {
                    $launched = Get-Process -Id $replacement.ProcessId -ErrorAction SilentlyContinue
                    $script:LaunchedPid = $replacement.ProcessId
                    Say "adopted spawned app pid=$($replacement.ProcessId)"
                } else {
                    Fail "app process exited during launch window"
                    break
                }
            }
            if ($launched) { [void](Maximize-MainWindow $launched.Id) }
            $script:OwnedSnapshot = @(Get-ProcessTreeSnapshot $launched.Id)
            $agentOk = $false
            $uiOk = $false
            foreach ($pidText in @(Get-PortListeners 7842)) {
                $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$pidText" -ErrorAction SilentlyContinue
                $hay = ([string]$owner.ExecutablePath) + " " + ([string]$owner.CommandLine)
                if ($owner -and (Test-OwnedIdentity $hay 7842)) { $agentOk = $true }
            }
            foreach ($pidText in @(Get-PortListeners 8888)) {
                $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$pidText" -ErrorAction SilentlyContinue
                $hay = ([string]$owner.ExecutablePath) + " " + ([string]$owner.CommandLine)
                if ($owner -and (Test-OwnedIdentity $hay 8888)) { $uiOk = $true }
            }
            if ($agentOk -and $uiOk) { $ready = $true; break }
        }

        if ($ready) {
            Pass "owned listeners on 7842 and 8888"
        } else {
            Fail "ports 7842/8888 did not become ready under the installed process tree"
        }

        $alive = $launched -and (Get-Process -Id $launched.Id -ErrorAction SilentlyContinue)
        if ($alive) { Pass "app process alive after launch (pid $($launched.Id))" }
        elseif ($script:Failures -notcontains "app process exited during launch window") {
            Fail "app process not alive after launch"
        }

        $script:OwnedSnapshot = @(Get-ProcessTreeSnapshot $script:LaunchedPid)
        Show-Procs $script:OwnedSnapshot "owned process tree"
        $ownedHay = (($script:OwnedSnapshot | ForEach-Object {
            (([string]$_.ExecutablePath) + " " + ([string]$_.CommandLine))
        }) -join "`n")
        if ($ownedHay -match 'appian-sentinel-sidecar') {
            Pass "owned tree includes appian-sentinel-sidecar"
        } else {
            Fail "owned tree missing appian-sentinel-sidecar"
        }
        if ($ownedHay -match 'server\.js') {
            Pass "owned tree includes UI server.js"
        } else {
            Fail "owned tree missing UI server.js"
        }

        if (Maximize-MainWindow $script:LaunchedPid) {
            Pass "main window maximized"
        } else {
            Say "ShowWindow maximize not confirmed (handle may still be hidden)"
        }

        Write-CapturedLogs
        $desktopLog = Get-DesktopLogPath
        if ($desktopLog) { Pass "captured desktop.log at $desktopLog" }
        else { Say "desktop.log not present yet; stdout/stderr still captured" }

        if ($alive) {
            Say "quitting shell (CloseMainWindow); children must die with the owned tree"
            $p = Get-Process -Id $script:LaunchedPid -ErrorAction SilentlyContinue
            if ($p) {
                $null = $p.CloseMainWindow()
                Start-Sleep -Seconds 8
                $p = Get-Process -Id $script:LaunchedPid -ErrorAction SilentlyContinue
                if ($p) {
                    & "$env:SystemRoot\System32\taskkill.exe" /F /PID $script:LaunchedPid 2>$null | Out-Null
                }
            }
            Start-Sleep -Seconds $QuitWaitSec
        }
    }
} finally {
    Stop-OwnedProcesses
    Start-Sleep -Seconds 2
    $left = @(Get-SentinelProcesses)
    Show-Procs $left "after owned cleanup"
    if ($left.Count -eq 0) {
        Pass "owned cleanup left zero sentinel processes"
    } else {
        Fail "$($left.Count) owned process(es) survived cleanup"
        Stop-OwnedProcesses
    }
    foreach ($port in 7842, 8888) {
        $foreign = $false
        foreach ($pidText in @(Get-PortListeners $port)) {
            $id = [int]$pidText
            if ($script:BaselineProcessIds.Contains($id)) { continue }
            $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
            $hay = ([string]$owner.ExecutablePath) + " " + ([string]$owner.CommandLine)
            if ($owner -and (Test-OwnedIdentity $hay $port)) {
                Fail "owned listener still on port $port (pid $id)"
            } else {
                $foreign = $true
            }
        }
        if (-not ($script:Failures | Where-Object { $_ -like "owned listener still on port $port*" })) {
            if ($foreign) { Pass "port $port still has a non-owned listener; left unchanged" }
            else { Pass "port $port has no owned listener after cleanup" }
        }
    }
    Write-CapturedLogs
}

Write-Host "=============================================="
if ($script:Failures.Count -eq 0) {
    Write-Host "[SUCCESS] SMOKE RESULT: ALL GATES PASS"
    exit 0
}
Write-Host "[ERROR] SMOKE RESULT: $($script:Failures.Count) FAILURE(S)"
foreach ($f in $script:Failures) { Write-Host "  - $f" }
exit 1
