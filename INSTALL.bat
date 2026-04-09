@echo off
title TKC Studio Stock AI — Installer
color 0B
cls

echo.
echo  ================================================
echo   TKC Studio Stock AI — Installer
echo  ================================================
echo.
echo  Checking your system...
echo.

:: ── Check if Python is installed ─────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] Python found.
    goto :run_installer
)

:: Python not found — try py launcher
py --version >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] Python found via py launcher.
    set PYTHON_CMD=py
    goto :run_installer
)

:: ── Python not installed — download it ───────────────────────────────
echo  Python is not installed. Downloading now...
echo  This will take a minute — please wait.
echo.

:: Use PowerShell to download Python installer
powershell -Command "& {$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe' -OutFile '%TEMP%\python_installer.exe'}"

if not exist "%TEMP%\python_installer.exe" (
    echo.
    echo  ERROR: Could not download Python.
    echo  Please check your internet connection and try again.
    echo.
    pause
    exit /b 1
)

echo  Installing Python 3.12...
"%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

:: Refresh environment so python is now in PATH
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%PATH%"

:: Verify
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Python was installed but needs a restart to be recognized.
    echo  Please restart your computer and run this installer again.
    echo.
    pause
    exit /b 1
)

echo  [OK] Python installed successfully.
echo.

:run_installer
:: ── Run the Python installer with Rich UI ────────────────────────────

:: Set working directory to the folder containing this .bat
cd /d "%~dp0"

:: Install rich first so the installer UI works
python -m pip install rich -q --exists-action i >nul 2>&1

:: Launch the installer
python installer.py

:: If installer exits with error, pause so user can read it
if %errorlevel% neq 0 (
    echo.
    echo  The installer encountered an error.
    echo  Please take a screenshot and send it to Tim.
    echo.
    pause
)
