# TKC Studio - Auto Trader Setup
# Run as Administrator in PowerShell

$projectFolder = Split-Path -Parent $MyInvocation.MyCommand.Path
$batFile = Join-Path $projectFolder "run_trader.bat"

Write-Host "Setting up TKC Auto Trader..." -ForegroundColor Cyan
Write-Host "Project folder: $projectFolder"

# Remove existing tasks if present
Unregister-ScheduledTask -TaskName "TKC_StockTrader_Open" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "TKC_StockTrader_Midday" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "TKC_StockTrader_Close" -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batFile`"" -WorkingDirectory $projectFolder
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# 8:30 AM CT - Market open
$trigger1 = New-ScheduledTaskTrigger -Daily -At 8:30AM
Register-ScheduledTask -TaskName "TKC_StockTrader_Open" -Action $action -Trigger $trigger1 -Settings $settings -RunLevel Highest -Force
Write-Host "Created: 8:30 AM task (market open)" -ForegroundColor Green

# 11:00 AM CT - Midday
$trigger2 = New-ScheduledTaskTrigger -Daily -At 11:00AM
Register-ScheduledTask -TaskName "TKC_StockTrader_Midday" -Action $action -Trigger $trigger2 -Settings $settings -RunLevel Highest -Force
Write-Host "Created: 11:00 AM task (midday)" -ForegroundColor Green

# 2:00 PM CT - End of day
$trigger3 = New-ScheduledTaskTrigger -Daily -At 2:00PM
Register-ScheduledTask -TaskName "TKC_StockTrader_Close" -Action $action -Trigger $trigger3 -Settings $settings -RunLevel Highest -Force
Write-Host "Created: 2:00 PM task (end of day)" -ForegroundColor Green

Write-Host ""
Write-Host "All done! Trader will run at 8:30 AM, 11:00 AM and 2:00 PM CT daily." -ForegroundColor Cyan
Read-Host "Press Enter to close"
