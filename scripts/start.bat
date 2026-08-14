@echo off
REM MiroFish 可移植部署 - Windows 启动脚本

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set APP_DIR=%PROJECT_ROOT%\app
set NEO4J_DIR=%PROJECT_ROOT%\neo4j

echo ================================================
echo    MiroFish 可移植部署启动脚本 (Windows)
echo ================================================
echo.

REM 检查依赖
echo [INFO] 检查前置依赖...

where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js 未安装。请访问 https://nodejs.org 安装
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do set NODE_VER=%%i
echo [INFO] ✓ Node.js %NODE_VER%

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 未安装。请访问 https://python.org 安装
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PY_VER=%%i
echo [INFO] ✓ Python %PY_VER%

where uv >nul 2>nul
if errorlevel 1 (
    echo [WARN] uv 未安装，启动脚本会自动尝试安装
)

echo.
echo [INFO] 启动 Neo4j...

REM 检查 Neo4j 是否存在
if not exist "%NEO4J_DIR%\neo4j\bin\neo4j.bat" (
    echo [ERROR] Neo4j 未安装。请运行 install-neo4j.bat
    pause
    exit /b 1
)

REM 启动 Neo4j
cd /d "%NEO4J_DIR%\neo4j\bin"
start "" neo4j.bat console

echo [INFO] Neo4j 启动中... (请稍候 10 秒初始化)
timeout /t 10 /nobreak

echo.
echo [INFO] 启动 MiroFish 应用...

cd /d "%APP_DIR%"

REM 检查并安装前端依赖
if not exist "frontend\node_modules" (
    echo [INFO] 安装前端依赖...
    call npm run setup
)

REM 检查并安装后端依赖
if not exist "backend\.venv" (
    echo [INFO] 安装后端依赖...
    call npm run setup:backend
)

REM 创建模拟环境
if not exist "backend\.venv-simulation" (
    echo [INFO] 创建模拟环境...
    cd /d "%APP_DIR%\backend"
    call uv venv .venv-simulation --python 3.11
    call .venv-simulation\Scripts\activate.bat
    call uv pip install camel-oasis==0.2.5 openai python-dotenv
    call .venv-simulation\Scripts\deactivate.bat
    cd /d "%APP_DIR%"
)

echo [INFO] 启动前端和后端...
call npm run dev

echo.
echo [INFO] 所有服务已启动！
echo [INFO] 前端: http://localhost:3000
echo [INFO] 后端: http://localhost:5001
echo [INFO] Neo4j: http://localhost:7474
echo [INFO] 按 CTRL+C 停止服务

pause
