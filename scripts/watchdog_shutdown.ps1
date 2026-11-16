# Last-resort watchdog: save progress, close OpenCode, shut down at 01:58 IST
# on 17 Nov 2026 (ahead of the user's 02:02 timer). Runs detached, independent
# of OpenCode. Idempotent: a marker file prevents a second shutdown request.

$ErrorActionPreference = 'SilentlyContinue'
$repo = 'D:\PROJECTS\VI3ION'
$marker = Join-Path $env:TEMP 'vi3ion-shutdown-marker.txt'
$deadline = [datetime]'2026-11-17 01:58:00'
$log = Join-Path $env:TEMP 'vi3ion-watchdog.log'

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line
}

Write-Log "watchdog started; deadline $deadline"

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 30
}

if (Test-Path $marker) {
    Write-Log 'marker exists - analysis already shut down; nothing to do'
    exit 0
}

Write-Log 'deadline reached - saving progress'

# Save any pending repo work (progress JSONL, reports, docs).
Push-Location $repo
git add -A 2>&1 | Out-Null
git -c user.name=Subadeepan-Y -c user.email=subadeepan_y@gmail.com commit -q -m 'watchdog: save analysis progress' 2>&1 | Out-Null
git push -q origin main 2>&1 | Out-Null
Pop-Location

# Stop the long analysis cleanly; it writes a JSONL row after every image.
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*full_analysis.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Log "stopped analysis pid $($_.ProcessId)" }

# Close OpenCode politely first, then force if it did not exit.
$editors = Get-Process | Where-Object { $_.ProcessName -match 'opencode' }
foreach ($p in $editors) {
    $null = $p.CloseMainWindow()
    Write-Log "asked OpenCode pid $($p.Id) to close"
}
Start-Sleep -Seconds 10
Get-Process | Where-Object { $_.ProcessName -match 'opencode' } |
  ForEach-Object { Stop-Process -Id $_.Id -Force; Write-Log "forced OpenCode pid $($_.Id)" }

Set-Content -Path $marker -Value "watchdog $(Get-Date)" -Encoding UTF8
Write-Log 'requesting shutdown'
shutdown /s /t 20 /c 'VI3ION watchdog: 02:00 deadline'
