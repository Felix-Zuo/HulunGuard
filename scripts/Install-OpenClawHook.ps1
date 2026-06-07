$ErrorActionPreference = 'Stop'

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$Source = Join-Path $ProjectRoot 'integrations\openclaw\hulunguard'
$OpenClawBase = if ($env:OPENCLAW_HOME) { $env:OPENCLAW_HOME } else { 'D:\OpenClawHome' }
$OpenClawHome = if ((Split-Path $OpenClawBase -Leaf) -eq '.openclaw') { $OpenClawBase } else { Join-Path $OpenClawBase '.openclaw' }
$Target = Join-Path $OpenClawHome 'hooks\hulunguard'

New-Item -ItemType Directory -Path $Target -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Source 'HOOK.md') -Destination (Join-Path $Target 'HOOK.md') -Force
Copy-Item -LiteralPath (Join-Path $Source 'handler.js') -Destination (Join-Path $Target 'handler.js') -Force

Write-Host "Installed HulunGuard OpenClaw hook to $Target"
Write-Host "Check with: openclaw hooks list --json"
