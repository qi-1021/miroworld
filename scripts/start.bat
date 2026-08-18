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

REM 设置国内多镜像自动加速与容灾备选（阿里云 / 清华大学 / 华为云 / 腾讯云 / 中科大）
if "%UV_INDEX_URL%"=="" set UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
if "%UV_EXTRA_INDEX_URL%"=="" set UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/
if "%PIP_INDEX_URL%"=="" set PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
if "%PIP_EXTRA_INDEX_URL%"=="" set PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/
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
    where winget >nul 2>nul
    if not errorlevel 1 (
        winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements >nul 2>nul
    )
    if not exist "C:\Program Files\nodejs\node.exe" (
        echo [INFO] 正在通过国内镜像自动下载 Node.js 便携版...
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
            "$nodeZip = 'node-v20-win-x64.zip'; " ^
            "$nodeDir = '%PROJECT_ROOT%\.node'; " ^
            "if (-not (Test-Path $nodeDir)) { " ^
            "  try { Invoke-WebRequest -Uri 'https://npmmirror.com/mirrors/node/v20.18.0/node-v20.18.0-win-x64.zip' -OutFile $nodeZip -UseBasicParsing -TimeoutSec 60 } " ^
            "  catch { Invoke-WebRequest -Uri 'https://nodejs.org/dist/v20.18.0/node-v20.18.0-win-x64.zip' -OutFile $nodeZip -UseBasicParsing -TimeoutSec 60 }; " ^
            "  Expand-Archive -Path $nodeZip -DestinationPath '%PROJECT_ROOT%\.node-temp' -Force; " ^
            "  Move-Item '%PROJECT_ROOT%\.node-temp\node-v20.18.0-win-x64' $nodeDir; " ^
            "  Remove-Item -Recurse -Force '%PROJECT_ROOT%\.node-temp' -ErrorAction SilentlyContinue; " ^
            "  Remove-Item -Force $nodeZip -ErrorAction SilentlyContinue; " ^
            "}"
    )
    set "PATH=C:\Program Files\nodejs;%PROJECT_ROOT%\.node;!PATH!"
)
where node >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('node --version 2^>nul') do echo [INFO] ✓ Node.js %%i
) else (
    echo [ERROR] Node.js 自动准备失败。请访问 https://nodejs.org 安装 Node.js 18+ 后重新运行
    pause
    exit /b 1
)

REM 4. 检查/自动准备 Java (Neo4j 所需 JVM)
where java >nul 2>nul
if errorlevel 1 (
    if exist "%PROJECT_ROOT%\.jdk\bin\java.exe" (
        set "JAVA_HOME=%PROJECT_ROOT%\.jdk"
        set "PATH=%PROJECT_ROOT%\.jdk\bin;!PATH!"
    )
)
where java >nul 2>nul
if errorlevel 1 (
    echo [INFO] 未检测到 Java，正在尝试自动准备 OpenJDK 17...
    where winget >nul 2>nul
    if not errorlevel 1 (
        winget install -e --id EclipseAdoptium.Temurin.17.JRE --accept-source-agreements --accept-package-agreements >nul 2>nul
    )
    where java >nul 2>nul
    if errorlevel 1 (
        echo [INFO] 正在通过国内镜像自动下载 OpenJDK 17 便携版...
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
            "$jdkZip = 'jdk-17-win-x64.zip'; " ^
            "$jdkDir = '%PROJECT_ROOT%\.jdk'; " ^
            "if (-not (Test-Path $jdkDir)) { " ^
            "  $urls = @('https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jre/x64/windows/OpenJDK17U-jre_x64_windows_hotspot_17.0.12_7.zip', " ^
            "            'https://mirrors.huaweicloud.com/openjdk/17.0.2/openjdk-17.0.2_windows-x64_bin.zip', " ^
            "            'https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.12%%2B7/OpenJDK17U-jre_x64_windows_hotspot_17.0.12_7.zip'); " ^
            "  $downloaded = $false; " ^
            "  foreach ($u in $urls) { " ^
            "    try { " ^
            "      Write-Host \"尝试下载 Java JRE: $u\"; " ^
            "      Invoke-WebRequest -Uri $u -OutFile $jdkZip -UseBasicParsing -TimeoutSec 120; " ^
            "      if ((Test-Path $jdkZip) -and ((Get-Item $jdkZip).Length -gt 10000000)) { $downloaded = $true; break; } " ^
            "    } catch { if (Test-Path $jdkZip) { Remove-Item $jdkZip -Force } } " ^
            "  }; " ^
            "  if ($downloaded) { " ^
            "    Expand-Archive -Path $jdkZip -DestinationPath '%PROJECT_ROOT%\.jdk-temp' -Force; " ^
            "    $extracted = Get-ChildItem '%PROJECT_ROOT%\.jdk-temp' | Where-Object { $_.PSIsContainer } | Select-Object -First 1; " ^
            "    Move-Item $extracted.FullName $jdkDir; " ^
            "    Remove-Item -Recurse -Force '%PROJECT_ROOT%\.jdk-temp' -ErrorAction SilentlyContinue; " ^
            "    Remove-Item -Force $jdkZip -ErrorAction SilentlyContinue; " ^
            "  } " ^
            "}"
        if exist "%PROJECT_ROOT%\.jdk\bin\java.exe" (
            set "JAVA_HOME=%PROJECT_ROOT%\.jdk"
            set "PATH=%PROJECT_ROOT%\.jdk\bin;!PATH!"
        )
    )
)
where java >nul 2>nul
if not errorlevel 1 (
    echo [INFO] ✓ Java 已就绪
) else (
    echo [ERROR] Java 17+ 自动准备失败。Neo4j 需要 JVM，请访问 https://adoptium.net 安装 Java 17+ 后重新运行
    pause
    exit /b 1
)

REM 清理上次残留（避免端口占用、虚拟盘符堆积与旧环境冲突）
echo [INFO] 清理上次运行残留...
for %%p in (3000 5001) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr "LISTENING"') do (
        taskkill /F /PID %%a /T >nul 2>nul
    )
)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_world_simulation*' -or $_.CommandLine -like '*run_parallel_simulation*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul

REM 强制彻底清理可能遗留的旧模拟环境
if exist "%APP_DIR%\backend\.venv-simulation" (
    rmdir /s /q "%APP_DIR%\backend\.venv-simulation" >nul 2>nul
)
if exist "%PROJECT_ROOT%\.venv-simulation" (
    rmdir /s /q "%PROJECT_ROOT%\.venv-simulation" >nul 2>nul
)

REM 扫描并释放属于本项目的旧虚拟盘符，避免重复累计创建
for %%d in (Z Y X W V U T S R Q P) do (
    if exist "%%d:\scripts\start.bat" (
        subst %%d: /d >nul 2>nul
    )
)

echo.
echo [INFO] 检查与启动 Neo4j 知识图谱数据库...

REM ---- 中文/特殊路径自动适配 (Windows subst 虚拟盘符自愈) ----
REM Neo4j JVM 与 Log4j 无法正确解析含非 ASCII（中文用户名如成昊翰）或空格的路径
REM 解决方案：通过 Windows subst 挂载一个纯 ASCII 独立虚拟盘符（优先固定使用 Z:），让 Neo4j 在纯英文路径下运行
set REAL_PROJECT_ROOT=%PROJECT_ROOT%
set SAFE_PROJECT_ROOT=%PROJECT_ROOT%

REM 检测路径是否包含非 ASCII 字符或空格
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "if ('%PROJECT_ROOT%' -match '[^\x00-\x7F]| ') { exit 10 } else { exit 0 }"
if errorlevel 10 (
    echo [INFO] 检测到项目路径包含中文或空格，正在自动建立纯英文虚拟磁盘映射...
    set "MAPPED_DRIVE="
    for %%d in (Z Y X W V U T S R Q P) do (
        if not defined MAPPED_DRIVE (
            if not exist "%%d:\" (
                subst %%d: "%PROJECT_ROOT%" >nul 2>nul
                if exist "%%d:\scripts\start.bat" (
                    set "MAPPED_DRIVE=%%d:"
                    set "SAFE_PROJECT_ROOT=%%d:"
                    echo [INFO] ✓ 已成功映射虚拟运行盘: %%d:
                )
            )
        )
    )
    if defined MAPPED_DRIVE (
        set "NEO4J_DIR=!SAFE_PROJECT_ROOT!\neo4j"
    )
)

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

REM 确保核心子目录（logs, conf, data, run, import）预先存在
if not exist "%NEO4J_HOME%\logs" mkdir "%NEO4J_HOME%\logs" >nul 2>nul
if not exist "%NEO4J_HOME%\conf" mkdir "%NEO4J_HOME%\conf" >nul 2>nul
if not exist "%NEO4J_HOME%\data" mkdir "%NEO4J_HOME%\data" >nul 2>nul
if not exist "%NEO4J_HOME%\run" mkdir "%NEO4J_HOME%\run" >nul 2>nul
if not exist "%NEO4J_HOME%\conf\neo4j.conf" (
    echo dbms.security.auth_enabled=true > "%NEO4J_HOME%\conf\neo4j.conf"
    echo dbms.default_listen_address=0.0.0.0 >> "%NEO4J_HOME%\conf\neo4j.conf"
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
    cd /d "%APP_DIR%\frontend"
    call npm config set registry https://registry.npmmirror.com >nul 2>nul
    call npm install --no-audit --no-fund
    call npm run build
    cd /d "%APP_DIR%"
)

REM 清理历史遗留的损坏模拟环境（若存在）
if exist "%APP_DIR%\backend\.venv-simulation" (
    rmdir /s /q "%APP_DIR%\backend\.venv-simulation" >nul 2>nul
)

REM 检查并安装主后端虚拟环境与 Flask/Graphiti 依赖
set NEED_BACKEND_INSTALL=0
if not exist "%APP_DIR%\backend\.venv\Scripts\python.exe" set NEED_BACKEND_INSTALL=1
if exist "%APP_DIR%\backend\.venv\Scripts\python.exe" (
    "%APP_DIR%\backend\.venv\Scripts\python.exe" -c "import flask" >nul 2>nul
    if errorlevel 1 set NEED_BACKEND_INSTALL=1
)

if "!NEED_BACKEND_INSTALL!"=="1" (
    echo [INFO] 正在全自动安装主后端核心依赖 Flask, OpenAI, Graphiti...
    cd /d "%APP_DIR%\backend"
    
    if not exist "%APP_DIR%\backend\.venv\Scripts\python.exe" (
        where uv >nul 2>nul
        if not errorlevel 1 (
            call uv venv "%APP_DIR%\backend\.venv"
        ) else (
            python -m venv "%APP_DIR%\backend\.venv"
        )
    )
    
    where uv >nul 2>nul
    if not errorlevel 1 (
        call uv pip install -r "%APP_DIR%\backend\requirements.txt" --python "%APP_DIR%\backend\.venv\Scripts\python.exe" --index-url https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/
    ) else (
        "%APP_DIR%\backend\.venv\Scripts\python.exe" -m ensurepip >nul 2>nul
        "%APP_DIR%\backend\.venv\Scripts\python.exe" -m pip install -r "%APP_DIR%\backend\requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/
    )
    cd /d "%APP_DIR%"
)

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
echo =================================================================
echo  🎉 Miroworld 所有服务已成功启动！
echo  - 前端界面:   http://localhost:3000 (已自动在浏览器打开)
echo  - 后端服务:   http://localhost:5001
echo  - Neo4j 图库: http://localhost:7474 (neo4j/password)
echo  - 停止服务:   双击 stop.bat (加 --all 连图数据库一起停止)
echo =================================================================
echo.

REM 自动唤起默认浏览器访问前端
start http://localhost:3000

echo 按任意键可关闭此命令行监控窗口（后台服务仍将持续运行）...
pause >nul
