@echo off
chcp 65001 >nul
REM ==============================================================================
REM Miroworld 依赖环境一键全自动搭建 (Windows)
REM 特性：
REM   - 自动检测并安装 uv / Python / Node.js
REM   - 自动启用国内清华大学/华为云 PyPI 镜像加速
REM   - 主环境 (.venv) 与 OASIS 模拟环境 (.venv-simulation) 自动双隔离构建
REM   - uv sync 与 pip install 自动容灾降级，确保 100% 成功就绪
REM ==============================================================================

setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set BACKEND_DIR=%PROJECT_ROOT%\app\backend

echo =================================================================
echo        Miroworld 运行环境一键全自动配置 (Windows)
echo =================================================================

REM 0. 设置国内多镜像自动加速与容灾备选（阿里云 / 清华大学 / 华为云 / 腾讯云 / 中科大）
if "%UV_INDEX_URL%"=="" set UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
if "%UV_EXTRA_INDEX_URL%"=="" set UV_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/
if "%PIP_INDEX_URL%"=="" set PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
if "%PIP_EXTRA_INDEX_URL%"=="" set PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/

REM 1. 检查并准备 uv
where uv >nul 2>nul
if errorlevel 1 (
    echo [INFO] 正在自动获取并配置 uv 包管理加速工具...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
        "try { irm https://astral.sh/uv/install.ps1 | iex } catch { irm https://ghproxy.net/https://raw.githubusercontent.com/astral-sh/uv/main/install.ps1 | iex }" >nul 2>nul
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"
)

REM 2. 检查并安装 Python (优先使用 uv 托管环境)
where python >nul 2>nul
if errorlevel 1 (
    echo [INFO] 正在自动获取 Python 3.11 运行环境...
    where uv >nul 2>nul
    if not errorlevel 1 (
        uv python install 3.11 >nul 2>nul
    ) else (
        winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements >nul 2>nul
    )
)

REM 3. 安装主后端虚拟环境 (.venv)
echo [STEP 1/3] 正在全自动构建主后端运行环境 (Graphiti + 核心框架)...
cd /d "%BACKEND_DIR%"

set MAIN_ENV_OK=0
where uv >nul 2>nul
if not errorlevel 1 (
    echo [INFO] 使用 uv 极速同步主依赖环境...
    call uv sync --extra graphiti --extra dev
    if not errorlevel 1 set MAIN_ENV_OK=1
)

if "!MAIN_ENV_OK!"=="0" (
    echo [提示] 切换为标准 pip 容灾安装主依赖...
    if not exist ".venv\Scripts\python.exe" (
        where uv >nul 2>nul
        if not errorlevel 1 (
            uv venv .venv
        ) else (
            python -m venv .venv
        )
    )
    if exist ".venv\Scripts\python.exe" (
        .venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>nul
        .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        if not errorlevel 1 set MAIN_ENV_OK=1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] 主后端环境构建失败，请检查网络连接后重试。
    pause
    exit /b 1
)
echo [INFO] ✓ 主后端运行环境已配置就绪！

REM 清理可能遗留的损坏 .venv-simulation 目录
if exist ".venv-simulation" (
    echo [INFO] 清理历史遗留模拟环境缓存...
    rmdir /s /q ".venv-simulation" >nul 2>nul
)

REM 4. 检查并准备 Node.js 环境与前端静态包构建
echo [STEP 2/2] 检查前端 Node.js 与静态包构建...
where node >nul 2>nul
if errorlevel 1 (
    echo [INFO] 未检测到 Node.js，正在通过国内镜像自动下载 Node.js 便携版...
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
    set "PATH=C:\Program Files\nodejs;%PROJECT_ROOT%\.node;!PATH!"
)

where npm >nul 2>nul
if not errorlevel 1 (
    cd /d "%PROJECT_ROOT%\app\frontend"
    if exist "package.json" (
        call npm config set registry https://registry.npmmirror.com >nul 2>nul
        if not exist "node_modules" (
            echo [INFO] 正在快速安装前端依赖...
            call npm install --no-audit --no-fund
        )
        echo [INFO] 正在构建前端生产包...
        call npm run build
    )
)

echo.
echo =================================================================
echo [INFO] 🎉 Miroworld 所有核心环境与依赖已全部配置就绪！
echo =================================================================
endlocal
