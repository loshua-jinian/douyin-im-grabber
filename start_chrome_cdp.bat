@echo off
title Chrome CDP Launcher

REM === Step 1: find Chrome ===
set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

if not exist "%CHROME%" (
    echo [ERROR] Chrome not found: %CHROME%
    pause
    exit /b 1
)

REM === Step 2: check if CDP already running ===
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Chrome CDP already running on port 9222
    echo.
    pause
    exit /b 0
)

REM === Step 3: launch Chrome with debugging ===
set USER_DATA=%TEMP%\chrome_cdp_9222

echo Starting Chrome with debug port 9222...
echo   Chrome: %CHROME%
echo   Profile: %USER_DATA%
echo.

start "" "%CHROME%" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%USER_DATA%"

echo Waiting for Chrome to start...
timeout /t 3 >nul

REM === Step 4: auto-open Douyin chat page ===
echo Opening Douyin chat page...
start "" "%CHROME%" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%USER_DATA%" "https://www.douyin.com/chat?isPopup=1"

timeout /t 2 >nul

REM === Step 5: verify ===
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] CDP port 9222 is ready!
    echo.
    echo Chrome should now show the Douyin chat page.
    echo First time: scan QR code to log in.
    echo After login: find your group chat, then run run_daily.bat
) else (
    echo [WARN] CDP port not responding yet, Chrome may still be starting...
)

echo.
pause
