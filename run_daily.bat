@echo off
chcp 65001 >nul
cd /d F:\AI\Workspace\douyin-im-grabber

echo.
echo ╔══════════════════════════════════════════╗
echo ║   财富自由团日报 · 一键执行流水线      ║
echo ╚══════════════════════════════════════════╝
echo.

REM 检查 Chrome CDP 是否就绪
echo [检查] Chrome CDP 端口 9222...
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [警告] Chrome CDP 未就绪，请确认 Chrome 已用调试模式启动
    echo        --remote-debugging-port=9222
    echo.
)

REM 执行流水线
python run_daily.py %*

echo.
echo 按任意键关闭...
pause >nul
