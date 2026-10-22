. (Join-Path $PSScriptRoot 'Common.ps1')
$settings = Get-SitlSettings
$reportDirectory = Join-Path $PSScriptRoot 'reports'
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$windowsObservations = [ordered]@{
    checked_at = (Get-Date).ToString('o')
    qgc_process_running = [bool](Get-Process -Name QGroundControl -ErrorAction SilentlyContinue)
    realflight_process_running = [bool](Get-Process -Name RealFlight64,RealFlight -ErrorAction SilentlyContinue)
}
$windowsObservations | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDirectory 'windows-apps.json') -Encoding UTF8
Assert-SitlWsl $settings
$linuxRoot = ConvertTo-SitlLinuxPath $PSScriptRoot $settings
Write-Host 'Collecting live SITL diagnostics. This does not arm, move controls, change parameters, or upload a mission.'
Write-Host 'The checker allows up to 60 seconds for EKF attitude output to begin advancing, then saves the full report. Leave this window open until Diagnostic result appears.'
& wsl.exe -d $settings.Distro --exec python3 "$linuxRoot/linux/smoke_test.py" "$linuxRoot/settings.json" "$linuxRoot/reports"
$testExitCode = $LASTEXITCODE
Write-Host ('Report: ' + (Join-Path $reportDirectory 'sitl-smoke-test.md'))
if ($testExitCode -ne 0) { throw 'The live check did not pass. See reports\sitl-smoke-test.md and reports\sitl-smoke-test.json for the failed checks and evidence.' }
