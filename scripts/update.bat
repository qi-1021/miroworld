@echo off
chcp 65001 >nul
:: ==============================================================================
:: Miroworld 一键更新脚本 (Windows)
:: 特性：采用 HTTPS 公开拉取，无需 Key，一键从 GitHub 同步最新代码并构建前端
:: ==============================================================================

echo =================================================================
echo         Miroworld 一键无密更新程序 (GitHub Public Sync)
echo =================================================================

cd /d "%~dp0\.."

:: 1. 检查 git
where git >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 未找到 git 命令，请先安装 Git for Windows。
    pause
    exit /b 1
)

:: 2. 拉取最新代码
echo [STEP] 正在从 GitHub 获取最新版本代码...
git remote set-url origin https://github.com/qi-1021/miroworld.git >nul 2>nul
git pull origin main
if %ERRORLEVEL% neq 0 (
    echo [WARN] 检测到本地修改冲突，尝试暂存更新...
    git stash
    git pull origin main
    git stash pop
)
echo [INFO] 代码已成功同步至最新版本！

:: 3. 检查后端依赖
echo [STEP] 检查并更新后端依赖...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m pip install -r app\backend\requirements.txt -q --disable-pip-version-check
) else if exist "app\backend\venv\Scripts\python.exe" (
    app\backend\venv\Scripts\python.exe -m pip install -r app\backend\requirements.txt -q --disable-pip-version-check
)

:: 4. 构建前端
echo [STEP] 构建前端生产包...
where npm >nul 2>nul
if %ERRORLEVEL% equ 0 (
    cd app\frontend
    call npm run build
    cd ..\..
)

echo =================================================================
echo [INFO] Miroworld 更新完成！
echo 双击 scripts\start.bat 即可启动最新版本。
echo =================================================================
pause
