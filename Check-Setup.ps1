. (Join-Path $PSScriptRoot 'Common.ps1')
$settings = Get-SitlSettings
foreach ($entry in @(@('QGroundControl',$settings.QgcExecutable),@('RealFlight',$settings.RealFlightExecutable))) {
    Write-Host ('{0}: {1}' -f $entry[0],(Test-Path -LiteralPath $entry[1] -PathType Leaf))
}
Invoke-SitlLinux doctor
