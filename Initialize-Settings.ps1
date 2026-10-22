param([switch]$NoEditor)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot 'settings.json'
if (Test-Path -LiteralPath $destination) {
    Write-Host 'Existing settings.json preserved. Edit it to change your app paths, aircraft profile or simulated origin.'
} else {
    $example = Join-Path $PSScriptRoot 'settings.example.json'
    if (-not (Test-Path -LiteralPath $example -PathType Leaf)) { throw 'settings.example.json is missing. Restore it from the repository.' }
    Copy-Item -LiteralPath $example -Destination $destination
    Write-Host ('Created local configuration: ' + $destination)
}
Write-Host 'Edit settings.json before building. Confirm installed app paths, aircraft profile and simulated field coordinates.'
Write-Host 'For the HobbyZone AeroScout APM variant, set AircraftProfile to AeroScoutAPM. The generic profile is the default.'
Write-Host 'Existing WSL installations are reused; do not reinstall or unregister a distribution that contains your work.'
if (-not $NoEditor) {
    Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $destination + '"')
}
