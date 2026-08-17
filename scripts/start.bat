@echo off
REM Miroworld 可移植部署 - Windows 启动脚本
REM
REM 统一入口逻辑与 start.sh 一致：前端/后端各自独立启动并写入独立日志，
REM 逐服务校验端口，失败即提示日志路径与排查引导（避免"提示已就绪但打不开"的端口失效）。
REM 日志目录：app\backend\logs\start-backend.log / start-frontend.log

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set APP_DIR=%PROJECT_ROOT%\app
set NEO4J_DIR=%PROJECT_ROOT%\neo4j
set LOG_DIR=%APP_DIR%\backend\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set BACKEND_LOG=%LOG_DIR%\start-backend.log
set FRONTEND_LOG=%LOG_DIR%\start-frontend.log

echo ================================================
echo    Miroworld 可移植部署启动脚本 (Windows)
echo ================================================
echo.

REM 设置国内镜像自动加速环境变量（清华源/华为源/npmmirror）
if "%UV_INDEX_URL%"=="" set UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
if "%PIP_INDEX_URL%"=="" set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
if "%NPM_CONFIG_REGISTRY%"=="" set NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

REM 检查与自动准备依赖
echo [INFO] 检查并自动准备运行环境 (已启用国内镜像自动加速)...

REM 1. 检查/自动安装 uv
where uv >nul 2>nul
if errorlevel 1 (
    echo [INFO] 正在自动获取 uv 包管理工具...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "try { irm https://astral.sh/uv/install.ps1 | iex } catch { irm https://mirror.ghproxy.com/https://raw.githubusercontent.com/astral-sh/uv/main/install.ps1 | iex }" >nul 2>nul
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"
)
where uv >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('uv --version 2^>nul') do echo [INFO] ✓ uv %%i
)

REM 2. 检查/自动准备 Python
where python >nul 2>nul
if errorlevel 1 (
    echo [INFO] 系统未找到 Python，正在尝试自动准备 Python 3.11...
    where uv >nul 2>nul
    if not errorlevel 1 (
        uv python install 3.11 >nul 2>nul
    ) else (
        winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements >nul 2>nul
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('python --version 2^>nul') do echo [INFO] ✓ Python %%i
) else (
    echo [INFO] ✓ Python 将由 uv 自动托管运行
)

REM 3. 检查/自动准备 Node.js
where node >nul 2>nul
if errorlevel 1 (
    echo [INFO] 未检测到 Node.js，正在尝试自动安装 Node.js LTS...
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements >nul 2>nul
    set "PATH=C:\Program Files\nodejs;!PATH!"
)
where node >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('node --version 2^>nul') do echo [INFO] ✓ Node.js %%i
) else (
    echo [ERROR] Node.js 自动准备失败。请访问 https://nodejs.org 安装 Node.js (>=18.0) 后重新运行
    pause
    exit /b 1
)

REM 4. 检查/自动准备 Java (Neo4j 所需 JVM)
where java >nul 2>nul
if errorlevel 1 (
    echo [INFO] 未检测到 Java，正在尝试自动准备 OpenJDK 17...
    winget install -e --id EclipseAdoptium.Temurin.17.JRE --accept-source-agreements --accept-package-agreements >nul 2>nul
)
where java >nul 2>nul
if not errorlevel 1 (
    echo [INFO] ✓ Java 已就绪
) else (
    echo [ERROR] Java 17+ 自动准备失败。Neo4j 需要 JVM，请访问 https://adoptium.net 安装 Java 17+
    pause
    exit /b 1
)

REM 清理上次残留（避免端口占用导致启动失败）
echo [INFO] 清理上次运行残留...
call "%SCRIPT_DIR%stop.bat" >nul 2>nul

echo.
echo [INFO] 检查与启动 Neo4j 知识图谱数据库...

REM 兼容两种安装布局：neo4j\neo4j（安装脚本默认）或 neo4j\neo4j-program（已有便携部署）
set NEO4J_HOME=%NEO4J_DIR%\neo4j
if not exist "%NEO4J_HOME%\bin\neo4j.bat" (
    if exist "%NEO4J_DIR%\neo4j-program\bin\neo4j.bat" (
        set NEO4J_HOME=%NEO4J_DIR%\neo4j-program
        echo [INFO] 检测到 Neo4j 安装在 %NEO4J_HOME%
    )
)

REM 自动傻瓜式下载与安装 Neo4j（用户第一次运行无需手动执行 install-neo4j.bat）
if not exist "%NEO4J_HOME%\bin\neo4j.bat" (
    echo [INFO] 未检测到本地 Neo4j，正在自动一键下载并部署 Neo4j 5.26.0 便携版...
    call "%SCRIPT_DIR%install-neo4j.bat"
    if not exist "%NEO4J_HOME%\bin\neo4j.bat" (
        echo [ERROR] Neo4j 便携版自动下载失败，请检查网络连接
        pause
        exit /b 1
    )
    echo [INFO] ✓ Neo4j 便携版自动安装就绪
)

REM 数据目录跟随便携文件夹（存在持久化数据时使用）
if exist "%NEO4J_DIR%\neo4j-data-persistent" (
    set NEO4J_server_directories_data=%NEO4J_DIR%\neo4j-data-persistent
    echo [INFO] 使用便携数据目录: neo4j-data-persistent
)

REM Neo4j 已在监听则跳过
netstat -ano | findstr ":7687" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [INFO] Neo4j 已在监听端口 7687，跳过启动
) else (
    REM 启动 Neo4j（独立最小化窗口，输出写入日志）
    start "Miroworld-Neo4j" /min cmd /c "cd /d "%NEO4J_HOME%\bin" && neo4j.bat console > "%LOG_DIR%\neo4j-console.log" 2>&1"
    echo [INFO] Neo4j 启动中... (请稍候 10 秒初始化)
    timeout /t 10 /nobreak
)

REM 校验 Neo4j
netstat -ano | findstr ":7687" | findstr "LISTENING" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Neo4j 启动失败。查看日志：
    if exist "%LOG_DIR%\neo4j-console.log" type "%LOG_DIR%\neo4j-console.log"
    pause
    exit /b 1
)
echo [INFO] ✓ Neo4j 已就绪 (neo4j/password)

echo.
echo [INFO] 启动 Miroworld 应用...

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

echo [INFO] 启动后端 (Flask) → 日志 %BACKEND_LOG%
REM 启动后端 (Flask)：直接使用 .venv 解释器，避免 uv run 触发 graphiti/oasis
REM 冲突导致的 "No solution found" 解析失败。
start "Miroworld-Backend" /min cmd /c "cd /d "%APP_DIR%\backend" && .venv\Scripts\python run.py > "%BACKEND_LOG%" 2>&1"

REM 等待后端端口 5001（最多 20 秒）
set READY=0
for /l %%i in (1,1,20) do (
    netstat -ano | findstr ":5001" | findstr "LISTENING" >nul 2>nul
    if not errorlevel 1 (
        set READY=1
        goto backend_ready
    )
    timeout /t 1 /nobreak >nul
)
:backend_ready
if "%READY%"=="0" (
    echo [ERROR] 后端启动失败（端口 5001 未监听）。最近日志：
    if exist "%BACKEND_LOG%" powershell -NoProfile -Command "Get-Content -Tail 40 '%BACKEND_LOG%'"
    echo 实时查看:   powershell -NoProfile -Command "Get-Content -Wait '%BACKEND_LOG%'"
    echo 常见原因:
    echo   1. 端口 5001 被无关进程占用 → netstat -ano ^| findstr :5001
    echo   2. 依赖不完整 → 运行 scripts\setup-env.bat 重新搭建
    echo   3. Neo4j 未就绪/配置错误 → 检查 app\.env
    pause
    exit /b 1
)
echo [INFO] ✓ 后端就绪 (http://localhost:5001)

echo [INFO] 启动前端 (Vue3) → 日志 %FRONTEND_LOG%
start "Miroworld-Frontend" /min cmd /c "cd /d "%APP_DIR%\frontend" && npm run dev > "%FRONTEND_LOG%" 2>&1"

REM 等待前端端口 3000（最多 30 秒）
set READY2=0
for /l %%i in (1,1,30) do (
    netstat -ano | findstr ":3000" | findstr "LISTENING" >nul 2>nul
    if not errorlevel 1 (
        set READY2=1
        goto frontend_ready
    )
    timeout /t 1 /nobreak >nul
)
:frontend_ready
if "%READY2%"=="0" (
    echo [ERROR] 前端启动失败（端口 3000 未监听）。最近日志：
    if exist "%FRONTEND_LOG%" powershell -NoProfile -Command "Get-Content -Tail 40 '%FRONTEND_LOG%'"
    echo 实时查看:   powershell -NoProfile -Command "Get-Content -Wait '%FRONTEND_LOG%'"
    echo 常见原因:
    echo   1. 端口 3000 被无关进程占用 → netstat -ano ^| findstr :3000
    echo   2. 前端依赖不完整 → 在 app\frontend 下运行 npm install
    pause
    exit /b 1
)
echo [INFO] ✓ 前端就绪 (http://localhost:3000)

echo.
echo [INFO] 所有服务已就绪！
echo [INFO] 前端:   http://localhost:3000
echo [INFO] 后端:   http://localhost:5001
echo [INFO] Neo4j:  http://localhost:7474 (neo4j/password)
echo [INFO] 模型设置: 打开前端后点击右下角「模型设置」
echo [INFO] 日志（失败/异常时查看）:
echo [INFO]   后端: powershell -NoProfile -Command "Get-Content -Wait '%BACKEND_LOG%'"
echo [INFO]   前端: powershell -NoProfile -Command "Get-Content -Wait '%FRONTEND_LOG%'"
echo [INFO] 停止服务: 运行 scripts\stop.bat（可加 --all 连 Neo4j 一起停）
echo.

pause
