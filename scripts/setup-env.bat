@echo off
REM Miroworld 依赖环境一键搭建（Windows）
REM 主环境：Graphiti + Neo4j 本地优先；OASIS 隔离到 .venv-simulation
REM 用法：setup-env.bat

setlocal
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set BACKEND_DIR=%PROJECT_ROOT%\app\backend

echo [1/2] 安装主环境（Graphiti + Neo4j 本地优先 + 开发工具）...
cd /d "%BACKEND_DIR%"
call uv sync --extra graphiti --extra dev
if errorlevel 1 (
    echo [ERROR] 主环境安装失败
    pause
    exit /b 1
)

echo [2/2] 创建/更新 OASIS 隔离模拟环境 (.venv-simulation)...
if not exist "%BACKEND_DIR%\.venv-simulation\Scripts\python.exe" (
    call uv venv "%BACKEND_DIR%\.venv-simulation"
)
"%BACKEND_DIR%\.venv-simulation\Scripts\python.exe" -m pip install --upgrade pip
"%BACKEND_DIR%\.venv-simulation\Scripts\python.exe" -m pip install -r "%BACKEND_DIR%\requirements-oasis.txt"
if errorlevel 1 (
    echo [ERROR] OASIS 模拟环境安装失败
    pause
    exit /b 1
)

echo.
echo 完成。
echo 启动：start.bat
echo 测试：cd app\backend ^&^& uv run pytest
endlocal
