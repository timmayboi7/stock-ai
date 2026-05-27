@echo off
title TKC Studio Stock AI — Uninstaller
color 0C
cls

echo.
echo  ================================================
echo   TKC Studio Stock AI — Uninstaller
echo  ================================================
echo.
echo  This will remove the app and all scheduled tasks.
echo  Your Alpaca account will NOT be affected.
echo.
set /p CONFIRM="  Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo.
    echo  Cancelled. Nothing was removed.
    echo.
    pause
    exit /b 0
)

echo.
echo  Removing scheduled tasks...
schtasks /delete /tn "TKC_StockTrader_Open"   /f >nul 2>&1
schtasks /delete /tn "TKC_StockTrader_Midday" /f >nul 2>&1
schtasks /delete /tn "TKC_StockTrader_Close"  /f >nul 2>&1
schtasks /delete /tn "TKC_OllamaServer"       /f >nul 2>&1
echo  [OK] Scheduled tasks removed.

echo.
echo  Stopping Ollama if running...
taskkill /IM ollama.exe /F >nul 2>&1
echo  [OK] Done.

echo.
echo  ================================================
echo   Scheduled tasks removed successfully.
echo.
echo   Optional cleanup:
echo   - Uninstall Ollama via Windows Settings - Apps
echo   - Uninstall Python via Windows Settings - Apps
echo   - Delete the desktop shortcut manually
echo  ================================================
echo.
set /p DELFOLDER="  Delete the project folder now? (YES/NO): "
if /i "%DELFOLDER%"=="YES" (
    echo.
    echo  Deleting project folder...
    cd /d "%USERPROFILE%"
    rmdir /s /q "%~dp0"
    echo  [OK] Project folder deleted.
) else (
    echo.
    echo  Project folder kept. Delete it manually when ready.
)

echo.
echo  Uninstall complete.
echo.
pause
