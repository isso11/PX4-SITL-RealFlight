param([switch]$TestAfterStart)

. (Join-Path $PSScriptRoot 'Common.ps1')
$transcriptStarted = $false
try {
if ($TestAfterStart) {
    $logDirectory = Join-Path $PSScriptRoot 'logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $transcriptPath = Join-Path $logDirectory 'start-test-latest.txt'
    Remove-Item -LiteralPath $transcriptPath -Force -ErrorAction SilentlyContinue
    Start-Transcript -LiteralPath $transcriptPath | Out-Null
    $transcriptStarted = $true
    Write-Host ('Startup and diagnostic transcript: ' + $transcriptPath)
}
Invoke-SitlLinux check
$settings = Get-SitlSettings
if ($settings.PSObject.Properties.Name -contains 'AircraftProfile' -and $settings.AircraftProfile -eq 'AeroScoutAPM') {
    Write-Host 'Aircraft profile: HobbyZone AeroScout APM. Select that model in RealFlight; its channel 5 steering will be held neutral.'
}
if (-not (Test-Path -LiteralPath $settings.QgcExecutable -PathType Leaf)) { throw 'QGC executable not found. Correct QgcExecutable in settings.json.' }
if (-not (Get-Process -Name QGroundControl -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $settings.QgcExecutable -WorkingDirectory (Split-Path $settings.QgcExecutable)
}
if (-not (Get-Process -Name RealFlight64,RealFlight -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path -LiteralPath $settings.SteamExecutable -PathType Leaf)) { throw 'Steam executable not found. Correct SteamExecutable in settings.json.' }
    Start-Process -FilePath $settings.SteamExecutable -ArgumentList @('-applaunch',$settings.SteamAppId)
}
Write-Host 'In RealFlight, load a conventional fixed-wing plane and enable RealFlight Link. Keep this console open; Ctrl+C stops the simulation.'
if ($TestAfterStart) {
    $reportDirectory = Join-Path $PSScriptRoot 'reports'
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    [ordered]@{
        checked_at = (Get-Date).ToString('o')
        qgc_process_running = [bool](Get-Process -Name QGroundControl -ErrorAction SilentlyContinue)
        realflight_process_running = [bool](Get-Process -Name RealFlight64,RealFlight -ErrorAction SilentlyContinue)
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDirectory 'windows-apps.json') -Encoding UTF8
    Write-Host 'Restarting this project SITL: stopping its tracked launcher and leftover plane processes before starting one PX4/bridge pair. Parameters and missions are preserved.'
    Write-Host 'A read-only diagnostic will run automatically after PX4 and the bridge have stayed running for 15 seconds. Keep the aircraft stationary and disarmed.'
    Invoke-SitlLinux run-test
} else {
    Invoke-SitlLinux run
}
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
