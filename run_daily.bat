@echo off
chcp 65001 >nul 2>&1
title Daily Pipeline

cd /d F:\AI\Workspace\douyin-im-grabber

echo ==================================================
echo   Daily Pipeline - Cai Fu Zi You Tuan
echo ==================================================
echo.

REM === Check Chrome CDP ===
echo [Check] Chrome CDP port 9222...
curl -s http://localhost:9222/json/version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ==================================================
    echo   [ERROR] Chrome CDP port 9222 is NOT ready!
    echo.
    echo   Please run start_chrome_cdp.bat first.
    echo ==================================================
    echo.
    pause
    exit /b 1
)
echo [Check] Chrome CDP: OK
echo.

REM === Check Douyin tab ===
echo [Check] Douyin chat tab...
curl -s http://localhost:9222/json | findstr /c:"douyin.com/chat" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ==================================================
    echo   [ERROR] No douyin.com/chat tab found!
    echo.
    echo   Make sure you have opened:
    echo   https://www.douyin.com/chat?isPopup=1
    echo   in the Chrome CDP window.
    echo ==================================================
    echo.
    pause
    exit /b 1
)
echo [Check] Douyin tab: OK
echo.

REM === Run pipeline ===
echo [Run] Starting pipeline...
echo.
python run_daily.py %*
set PIPELINE_EXIT=%ERRORLEVEL%

echo.
if %PIPELINE_EXIT% NEQ 0 goto :pipeline_fail
goto :pipeline_ok

:pipeline_fail
echo ==================================================
echo   [FAIL] Pipeline failed with error code: %PIPELINE_EXIT%
echo   Check the output above for details.
echo.
echo   Common issues:
echo   - Douyin page not fully loaded
echo   - Not logged in (scan QR code in Chrome)
echo   - Target group chat not visible
echo ==================================================
goto :end

:pipeline_ok
echo ==================================================
echo   [DONE] Pipeline completed successfully!
echo ==================================================
goto :end

:end
echo.
echo Press any key to close...
pause >nul
