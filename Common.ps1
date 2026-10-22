Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:SitlRoot = $PSScriptRoot

function Get-SitlSettings {
    $configPath = Join-Path $script:SitlRoot 'settings.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw 'Local settings.json is missing. Run 0-Configure.cmd, then edit the generated settings before building or starting SITL.'
    }
    Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
}

function Assert-SitlWsl {
    param($Settings)
    $nativeOutput = & wsl.exe --list --quiet 2>&1
    $nativeExitCode = $LASTEXITCODE
    $distroNames = (($nativeOutput | Out-String) -replace "`0", '') -split "`r?`n"
    $distroNames = @($distroNames | ForEach-Object { $_.Trim() })
    $nativeText = (($nativeOutput | Out-String) -replace "`0", '')
    if ($nativeText -match 'E_ACCESSDENIED|Access is denied') {
        throw 'This process cannot access the WSL service (Wsl/E_ACCESSDENIED). Run the launcher from your normal Windows desktop account, not from a sandboxed or service session. This error does not mean WSL needs reinstalling.'
    }
    if ($nativeExitCode -ne 0 -or $distroNames -notcontains $Settings.Distro) {
        throw 'Ubuntu-22.04 is unavailable. Run 1-Install-WSL.cmd as Administrator, restart if requested, then open Ubuntu and create your Linux account.'
    }
    $versionOutput = & wsl.exe --list --verbose 2>&1
    $versionLines = (($versionOutput | Out-String) -replace "`0", '') -split "`r?`n"
    $distroPattern = '^\s*\*?\s*' + [regex]::Escape($Settings.Distro) + '\s+.+\s+2\s*$'
    if (-not ($versionLines | Where-Object { $_ -match $distroPattern })) {
        throw 'This setup requires WSL2. Check wsl --list --verbose; convert Ubuntu-22.04 to version 2 before building.'
    }
    $linuxUser = & wsl.exe -d $Settings.Distro --exec id -u
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu could not start. Finish its first-run setup first.' }
    if ((($linuxUser | Out-String) -replace "`0", '').Trim() -eq '0') {
        throw 'Ubuntu is using root as its default user. Finish Ubuntu setup and select your normal Linux user before building.'
    }
}

function ConvertTo-SitlLinuxPath {
    param([string]$Path, $Settings)
    $linuxPath = & wsl.exe -d $Settings.Distro --exec wslpath -a -u $Path
    if ($LASTEXITCODE -ne 0) { throw "Cannot map this path into Ubuntu: $Path" }
    (($linuxPath | Out-String) -replace "`0", '').Trim()
}

function Invoke-SitlLinux {
    param([ValidateSet('build','check','doctor','run','run-test','stop')][string]$Action)
    $settings = Get-SitlSettings
    Assert-SitlWsl $settings
    $rootInLinux = ConvertTo-SitlLinuxPath $script:SitlRoot $settings
    $configInLinux = "$rootInLinux/settings.json"
    if ($Action -eq 'build') {
        & wsl.exe -d $settings.Distro --exec bash "$rootInLinux/linux/bootstrap.sh" $configInLinux
    } else {
        & wsl.exe -d $settings.Distro --exec python3 "$rootInLinux/linux/sitl.py" $configInLinux $Action
    }
    if ($LASTEXITCODE -ne 0) { throw "SITL '$Action' failed (exit $LASTEXITCODE). Read the message above." }
}
