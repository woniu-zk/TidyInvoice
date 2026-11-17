@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [InvoiceFlowAI] 未找到 .venv 虚拟环境。
    echo 请先在本目录执行：
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo     .venv\Scripts\python.exe -m playwright install chromium
    echo.
    pause
    exit /b 1
)

echo [InvoiceFlowAI] 正在启动...
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 (
    echo.
    echo [InvoiceFlowAI] 程序异常退出，错误码 %errorlevel%。
    pause
)
endlocal
