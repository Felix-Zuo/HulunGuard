$Tool = Join-Path $PSScriptRoot 'hulun.ps1'
& $Tool @args
exit $LASTEXITCODE
