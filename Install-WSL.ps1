Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Right-click 1-Install-WSL.cmd and choose Run as administrator. Installing WSL changes Windows features and requires administrator rights.'
}
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$versionOutput = & wsl.exe --version 2>&1
$versionExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($versionExitCode -ne 0) {
    Write-Host 'Installing the WSL runtime without placing a default distribution on C:...'
    & wsl.exe --install --no-distribution
    $runtimeExitCode = $LASTEXITCODE
    if ($runtimeExitCode -eq 3010) {
        Write-Host 'Restart Windows, then run 1-Install-WSL.cmd as Administrator again to install Ubuntu beside this project.'
        exit 3010
    }
    if ($runtimeExitCode -ne 0) { throw "WSL runtime installation failed (exit $runtimeExitCode). Restart Windows if requested and rerun this installer." }
}
& wsl.exe --set-default-version 2
if ($LASTEXITCODE -ne 0) { throw 'WSL2 is not ready. Restart Windows if requested, then rerun this installer.' }
$distributionLocation = Join-Path $PSScriptRoot 'wsl\Ubuntu-22.04'
Write-Host ('Ubuntu virtual disk location: ' + $distributionLocation)
& wsl.exe --install -d Ubuntu-22.04 --location $distributionLocation --no-launch
$installExitCode = $LASTEXITCODE
if ($installExitCode -notin @(0,3010)) { throw "Ubuntu installer exited with code $installExitCode. Restart Windows if the WSL runtime requested it, then rerun this installer. If --location is unsupported, run wsl --update first. Requested disk location: $distributionLocation" }
Write-Host 'Restart Windows if requested. Then open Ubuntu 22.04 from Start and create a Linux username and password.'
Write-Host 'Next, double-click 2-Build-SITL.cmd using your normal Windows account.'
