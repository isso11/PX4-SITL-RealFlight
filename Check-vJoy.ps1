. (Join-Path $PSScriptRoot 'Common.ps1')
$settings = Get-SitlSettings
Assert-SitlWsl $settings
$linuxRoot = ConvertTo-SitlLinuxPath $PSScriptRoot $settings
Write-Host 'Keep RealFlight and this project SITL running, with the virtual aircraft disarmed.'
Write-Host 'Follow the four axis prompts. RC-only input is enabled only after all four pass.'
& wsl.exe -d $settings.Distro --exec python3 "$linuxRoot/linux/check_vjoy.py" "$linuxRoot/settings.json" "$linuxRoot/reports" --enable-rc
if ($LASTEXITCODE -ne 0) { throw 'vJoy check stopped. The evidence is in reports\vjoy-check.json if Linux collection started.' }
