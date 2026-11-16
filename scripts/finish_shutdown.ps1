# Detached: close OpenCode, then reissue the shutdown after the analysis.
$ErrorActionPreference = 'SilentlyContinue'
$log = Join-Path $env:TEMP 'vi3ion-finish-shutdown.log'
function L([string]$m) { Add-Content $log ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) }

L 'finisher started'
Start-Sleep -Seconds 20

Push-Location 'D:\PROJECTS\VI3ION'
git add -A 2>&1 | Out-Null
git -c user.name=Subadeepan-Y -c user.email=subadeepan_y@gmail.com commit -q -m 'chore: save state before shutdown' 2>&1 | Out-Null
git push -q origin main 2>&1 | Out-Null
Pop-Location

Get-Process | Where-Object { $_.ProcessName -match 'opencode' } | ForEach-Object {
    $null = $_.CloseMainWindow()
    L "close requested for $($_.ProcessName) pid $($_.Id)"
}
Start-Sleep -Seconds 8
Get-Process | Where-Object { $_.ProcessName -match 'opencode' } | ForEach-Object {
    Stop-Process -Id $_.Id -Force
    L "forced $($_.ProcessName) pid $($_.Id)"
}

shutdown /a 2>&1 | Out-Null
Start-Sleep -Seconds 2
shutdown /s /t 30 /c 'VI3ION analysis complete - final shutdown' 2>&1 | Out-Null
L 'shutdown issued'
