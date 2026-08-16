@echo off
REM Miroworld 模型配置初始化 (Windows)
REM 用途：在启动前后端之前运行，完成两件事：
REM   1. 首次运行时把旧 .env 的 LLM 配置导入模型注册表（幂等，不会覆盖已有配置）
REM   2. 检查模型库状态，并提示如何配置模型
REM 用法：call init-models.bat    （start.bat 会自动调用，也可单独运行）

setlocal

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set APP_DIR=%PROJECT_ROOT%\app

REM 后端环境未安装时跳过（首次启动 start.bat 会先完成安装）
if not exist "%APP_DIR%\backend\.venv\Scripts\python.exe" (
    echo [WARN] 后端环境未安装，跳过模型配置初始化
    exit /b 0
)

set PYTHON=%APP_DIR%\backend\.venv\Scripts\python.exe
set CLI=%APP_DIR%\backend\scripts\mirofish_models.py

cd /d "%APP_DIR%"

echo [INFO] 检查并导入 .env 中的旧 LLM 配置...
"%PYTHON%" "%CLI%" --json env import >nul 2>nul
if errorlevel 1 (
    echo [WARN] .env 旧配置导入未完成（可稍后在网页中手动配置）
) else (
    echo [INFO] .env 旧配置导入完成（如为首次运行）
)

echo [INFO] 当前模型库状态：
"%PYTHON%" "%CLI%" models list

endlocal
