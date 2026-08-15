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

REM 检查 Java（Neo4j 需要 JVM）
where java >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Java 未安装。Neo4j 需要 JVM，请先安装 Java 17+
    pause
    exit /b 1
)
echo [INFO] ✓ Java 已就绪

REM 清理上次残留（避免端口占用导致启动失败）
echo [INFO] 清理上次运行残留...
call "%SCRIPT_DIR%stop.bat" >nul 2>nul

echo.
echo [INFO] 启动 Neo4j...

REM 兼容两种安装布局：neo4j\neo4j（安装脚本默认）或 neo4j\neo4j-program（已有便携部署）
set NEO4J_HOME=%NEO4J_DIR%\neo4j
if not exist "%NEO4J_HOME%\bin\neo4j.bat" (
    if exist "%NEO4J_DIR%\neo4j-program\bin\neo4j.bat" (
        set NEO4J_HOME=%NEO4J_DIR%\neo4j-program
        echo [INFO] 检测到 Neo4j 安装在 %NEO4J_HOME%
    )
)

REM 检查 Neo4j 是否存在
if not exist "%NEO4J_HOME%\bin\neo4j.bat" (
    REM 自修复：Homebrew 拷贝布局下从 libexec 复制启动脚本
    if exist "%NEO4J_HOME%\libexec\bin\neo4j.bat" (
        echo [INFO] 检测到缺失的 bin 启动脚本，正在从 libexec 恢复...
        copy /y "%NEO4J_HOME%\libexec\bin\neo4j.bat" "%NEO4J_HOME%\bin\neo4j.bat" >nul
        copy /y "%NEO4J_HOME%\libexec\bin\neo4j-admin.bat" "%NEO4J_HOME%\bin\neo4j-admin.bat" >nul
    ) else (
        echo [ERROR] Neo4j 未安装。请运行 install-neo4j.bat
        pause
        exit /b 1
    )
)

REM 数据目录跟随便携文件夹（存在持久化数据时使用）
if exist "%NEO4J_DIR%\neo4j-data-persistent" (
    set NEO4J_server_directories_data=%NEO4J_DIR%\neo4j-data-persistent
    echo [INFO] 使用便携数据目录: neo4j-data-persistent
)

REM 启动 Neo4j
cd /d "%NEO4J_HOME%\bin"
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

REM 创建模拟环境（OASIS 与 Graphiti 依赖隔离）
if not exist "backend\.venv-simulation\Scripts\python.exe" (
    echo [INFO] 创建模拟环境...
    cd /d "%APP_DIR%\backend"
    call uv venv .venv-simulation
    if errorlevel 1 exit /b 1
)
if not exist "backend\.venv-simulation\Scripts\python.exe" (
    echo [ERROR] 模拟环境创建失败
    pause
    exit /b 1
)
echo [INFO] 检查/安装 OASIS 模拟依赖...
"%APP_DIR%\backend\.venv-simulation\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
"%APP_DIR%\backend\.venv-simulation\Scripts\python.exe" -m pip install -r "%APP_DIR%\backend\requirements-oasis.txt"
if errorlevel 1 (
    echo [ERROR] OASIS 模拟依赖安装失败
    pause
    exit /b 1
)
cd /d "%APP_DIR%"

REM 初始化模型配置（导入旧 .env、检查模型库状态）
if exist "%SCRIPT_DIR%init-models.bat" (
    echo [INFO] 初始化模型配置...
    call "%SCRIPT_DIR%init-models.bat"
)

echo [INFO] 启动前端和后端...
call npm run dev

echo.
echo [INFO] 所有服务已启动！
echo [INFO] 前端: http://localhost:3000
echo [INFO] 后端: http://localhost:5001
echo [INFO] Neo4j: http://localhost:7474
echo [INFO] 模型设置: 打开前端后点击右下角「模型设置」
echo [INFO] 按 CTRL+C 停止服务

pause
