. (Join-Path $PSScriptRoot 'Common.ps1')
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'logs') -Force | Out-Null
$transcriptFile = Join-Path $PSScriptRoot 'logs/build-latest.txt'
Remove-Item -LiteralPath $transcriptFile -Force -ErrorAction SilentlyContinue
Start-Transcript -LiteralPath $transcriptFile | Out-Null
try { Invoke-SitlLinux build } finally { Stop-Transcript | Out-Null }
