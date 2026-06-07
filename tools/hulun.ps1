$Root = (Get-Location).Path
$CommandArgs = New-Object System.Collections.Generic.List[string]

for ($i = 0; $i -lt $args.Count; $i++) {
  $arg = [string]$args[$i]
  if (($arg -eq '-Root' -or $arg -eq '--root') -and ($i + 1 -lt $args.Count)) {
    $Root = [string]$args[$i + 1]
    $i++
  } else {
    $CommandArgs.Add($arg)
  }
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$Entry = Join-Path $ProjectRoot 'hulun.py'
python $Entry --root $Root @CommandArgs
exit $LASTEXITCODE
