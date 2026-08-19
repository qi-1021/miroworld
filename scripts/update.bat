@echo off
chcp 65001 >nul
setlocal
:: ==============================================================================
:: Miroworld 一键更新脚本 (Windows)
:: 特性：采用 HTTPS 公开拉取，无需 Key，一键从 GitHub 同步最新代码并构建前端
::   - 自动检测代理与本地代理工具，智能选择最快镜像源
::   - 免 Git 模式支持版本检查、断点续传、校验与本地数据保护
::   - 全程写入更新日志 logs\update.log 便于诊断
:: ==============================================================================

echo =================================================================
echo         Miroworld 一键无密更新程序 (GitHub Public Sync)
echo =================================================================

cd /d "%~dp0\.."
set "PROJECT_ROOT=%CD%"
set "LOG_DIR=%PROJECT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\update.log"

call :log "===== 开始更新 ====="

:: 版本文件
if not exist "%PROJECT_ROOT%\VERSION" (
    echo 1.0.0> "%PROJECT_ROOT%\VERSION"
    call :log "已创建版本文件 VERSION (1.0.0)"
)

:: 检测代理环境变量
set "PROXY="
if defined https_proxy set "PROXY=%https_proxy%"
if not defined PROXY if defined HTTPS_PROXY set "PROXY=%HTTPS_PROXY%"
if not defined PROXY if defined http_proxy set "PROXY=%http_proxy%"
if not defined PROXY if defined HTTP_PROXY set "PROXY=%HTTP_PROXY%"
if not defined PROXY if defined all_proxy set "PROXY=%all_proxy%"
if not defined PROXY if defined ALL_PROXY set "PROXY=%ALL_PROXY%"
if defined PROXY (
    echo [INFO] 检测到代理: %PROXY%
    call :log "生效代理: %PROXY%"
    set "http_proxy=%PROXY%"
    set "https_proxy=%PROXY%"
    set "HTTP_PROXY=%PROXY%"
    set "HTTPS_PROXY=%PROXY%"
) else (
    echo [INFO] 未检测到代理，将尝试直连与镜像加速。
)

:: 1. 检查 git 环境（无 Git 则自动通过 PowerShell 下载最新 ZIP 覆盖更新）
where git >nul 2>nul
if not errorlevel 1 goto :gitmode

:: ============================ 免 Git 模式 ============================
echo [提示] 当前机器未安装 Git，自动启用免 Git 原生 ZIP 极速增量更新通道...
call :log "启用免 Git ZIP 更新通道"

:: 生成并执行免 Git 更新 PowerShell 脚本
set "PSFILE=%TEMP%\miroworld-update-nogit.ps1"
if exist "%PSFILE%" del /f /q "%PSFILE%" >nul 2>nul

echo param([string]$ProjectRoot)>> "%PSFILE%"
echo $ErrorActionPreference = 'Stop'>> "%PSFILE%"
echo $logFile = Join-Path $ProjectRoot 'logs\update.log'>> "%PSFILE%"
echo function Log([string]$msg) {>> "%PSFILE%"
echo     $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'>> "%PSFILE%"
echo     Add-Content -Path $logFile -Value "[$ts] $msg" -Encoding UTF8>> "%PSFILE%"
echo }>> "%PSFILE%"
echo $localVersion = ''>> "%PSFILE%"
echo if (Test-Path (Join-Path $ProjectRoot 'VERSION')) {>> "%PSFILE%"
echo     $localVersion = (Get-Content (Join-Path $ProjectRoot 'VERSION') -Raw).Trim()>> "%PSFILE%"
echo }>> "%PSFILE%"
echo $mirrors = @('github.com','ghproxy.net','gh-proxy.com','ghfast.top','mirror.ghproxy.com')>> "%PSFILE%"
echo function MirrorUrl([string]$m, [string]$path) {>> "%PSFILE%"
echo     if ($m -eq 'github.com') { return "https://github.com/$path" }>> "%PSFILE%"
echo     return "https://$m/https://github.com/$path">> "%PSFILE%"
echo }>> "%PSFILE%"
echo $remoteVersion = ''>> "%PSFILE%"
echo foreach ($m in $mirrors) {>> "%PSFILE%"
echo     try {>> "%PSFILE%"
echo         $u = MirrorUrl $m 'qi-1021/miroworld/raw/main/VERSION'>> "%PSFILE%"
echo         $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop>> "%PSFILE%"
echo         $remoteVersion = ($r.Content).Trim()>> "%PSFILE%"
echo         if ($remoteVersion) { break }>> "%PSFILE%"
echo     } catch {}>> "%PSFILE%"
echo }>> "%PSFILE%"
echo if ($remoteVersion) {>> "%PSFILE%"
echo     if ($localVersion -and $remoteVersion -eq $localVersion) {>> "%PSFILE%"
echo         Write-Host "[INFO] 已是最新版本 (v$localVersion)，无需更新">> "%PSFILE%"
echo         Log "已是最新版本 (v$localVersion)，无需更新">> "%PSFILE%"
echo         exit 0>> "%PSFILE%"
echo     }>> "%PSFILE%"
echo     Write-Host "[INFO] 发现新版本: 本地 v$localVersion 到 远端 v$remoteVersion">> "%PSFILE%"
echo     Log "发现新版本: 本地 v$localVersion 到 远端 v$remoteVersion">> "%PSFILE%"
echo } else {>> "%PSFILE%"
echo     Write-Host "[WARN] 无法获取远端版本号，将直接下载更新。">> "%PSFILE%"
echo     Log "WARN: 远端版本获取失败，直接下载">> "%PSFILE%"
echo }>> "%PSFILE%"
echo $zipFile = Join-Path $ProjectRoot 'miroworld-update-temp.zip'>> "%PSFILE%"
echo $tempDir = Join-Path $ProjectRoot 'miroworld-update-temp'>> "%PSFILE%"
echo if (Test-Path $zipFile) { Remove-Item -Force $zipFile }>> "%PSFILE%"
echo if (Test-Path $tempDir) { Remove-Item -Recurse -Force $tempDir }>> "%PSFILE%"
echo $path = 'qi-1021/miroworld/archive/refs/heads/main.zip'>> "%PSFILE%"
echo $candidates = @()>> "%PSFILE%"
echo foreach ($m in $mirrors) { $candidates += (MirrorUrl $m $path) }>> "%PSFILE%"
echo $proxy = $env:https_proxy>> "%PSFILE%"
echo if (-not $proxy) { $proxy = $env:HTTPS_PROXY }>> "%PSFILE%"
echo if (-not $proxy) { $proxy = $env:http_proxy }>> "%PSFILE%"
echo if (-not $proxy) { $proxy = $env:HTTP_PROXY }>> "%PSFILE%"
echo if (-not $proxy) {>> "%PSFILE%"
echo     foreach ($port in @(7890,7897,10809,1080,8888)) {>> "%PSFILE%"
echo         try {>> "%PSFILE%"
echo             $t = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet>> "%PSFILE%"
echo             if ($t) { $proxy = "http://127.0.0.1:$port"; break }>> "%PSFILE%"
echo         } catch {}>> "%PSFILE%"
echo     }>> "%PSFILE%"
echo }>> "%PSFILE%"
echo if ($proxy) {>> "%PSFILE%"
echo     Write-Host "[INFO] 将使用代理: $proxy">> "%PSFILE%"
echo     Log "生效代理: $proxy">> "%PSFILE%"
echo }>> "%PSFILE%"
echo $curl = Get-Command curl.exe -ErrorAction SilentlyContinue>> "%PSFILE%"
echo $tar = Get-Command tar.exe -ErrorAction SilentlyContinue>> "%PSFILE%"
echo $downloaded = $false>> "%PSFILE%"
echo foreach ($u in $candidates) {>> "%PSFILE%"
echo     Write-Host "[INFO] 正在从镜像下载: $u">> "%PSFILE%"
echo     Log "尝试下载: $u">> "%PSFILE%"
echo     $ok = $false>> "%PSFILE%"
echo     if ($curl) {>> "%PSFILE%"
echo         $curlArgs = @('-fSL','-C','-','-s','--retry','3','--retry-delay','2','--connect-timeout','15','-m','60')>> "%PSFILE%"
echo         if ($proxy) { $curlArgs += '--proxy'; $curlArgs += $proxy }>> "%PSFILE%"
echo         $curlArgs += '-o'; $curlArgs += $zipFile; $curlArgs += $u>> "%PSFILE%"
echo         for ($i=0; $i -lt 3; $i++) {>> "%PSFILE%"
echo             curl.exe @curlArgs>> "%PSFILE%"
echo             if ($LASTEXITCODE -eq 0) { $ok = $true; break }>> "%PSFILE%"
echo             Start-Sleep -Seconds 2>> "%PSFILE%"
echo         }>> "%PSFILE%"
echo     } else {>> "%PSFILE%"
echo         try {>> "%PSFILE%"
echo             $params = @{ Uri=$u; OutFile=$zipFile; UseBasicParsing=$true; TimeoutSec=60 }>> "%PSFILE%"
echo             if ($proxy) { $params.Proxy = $proxy }>> "%PSFILE%"
echo             Invoke-WebRequest @params>> "%PSFILE%"
echo             $ok = $true>> "%PSFILE%"
echo         } catch { $ok = $false }>> "%PSFILE%"
echo     }>> "%PSFILE%"
echo     if ($ok) {>> "%PSFILE%"
echo         $valid = $false>> "%PSFILE%"
echo         if ($tar) {>> "%PSFILE%"
echo             tar.exe -tf $zipFile ^| Out-Null>> "%PSFILE%"
echo             if ($LASTEXITCODE -eq 0) { $valid = $true }>> "%PSFILE%"
echo         } else {>> "%PSFILE%"
echo             try { Expand-Archive -Path $zipFile -DestinationPath $tempDir -Force; $valid = $true } catch { $valid = $false }>> "%PSFILE%"
echo         }>> "%PSFILE%"
echo         if ($valid) {>> "%PSFILE%"
echo             Write-Host "[INFO] 下载并校验成功！">> "%PSFILE%"
echo             Log "下载并校验成功: $u">> "%PSFILE%"
echo             $downloaded = $true>> "%PSFILE%"
echo             break>> "%PSFILE%"
echo         } else {>> "%PSFILE%"
echo             Write-Host "[WARN] 校验失败，切换镜像...">> "%PSFILE%"
echo             Remove-Item -Force $zipFile -ErrorAction SilentlyContinue>> "%PSFILE%"
echo         }>> "%PSFILE%"
echo     } else {>> "%PSFILE%"
echo         Write-Host "[WARN] 下载失败，切换镜像...">> "%PSFILE%"
echo         Remove-Item -Force $zipFile -ErrorAction SilentlyContinue>> "%PSFILE%"
echo     }>> "%PSFILE%"
echo }>> "%PSFILE%"
echo if (-not $downloaded) {>> "%PSFILE%"
echo     Write-Host "[ERROR] 所有下载源均失败，请检查网络连接。">> "%PSFILE%"
echo     Log "ERROR: 所有下载源均失败">> "%PSFILE%"
echo     exit 1>> "%PSFILE%"
echo }>> "%PSFILE%"
echo if (-not (Test-Path $tempDir)) { New-Item -ItemType Directory -Path $tempDir ^| Out-Null }>> "%PSFILE%"
echo if ($tar) {>> "%PSFILE%"
echo     tar.exe -xf $zipFile -C $tempDir>> "%PSFILE%"
echo     if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] 解压失败"; Log "ERROR: 解压失败"; exit 1 }>> "%PSFILE%"
echo } else {>> "%PSFILE%"
echo     try { Expand-Archive -Path $zipFile -DestinationPath $tempDir -Force } catch { Write-Host "[ERROR] 解压失败"; Log "ERROR: 解压失败"; exit 1 }>> "%PSFILE%"
echo }>> "%PSFILE%"
echo $srcTree = Join-Path $tempDir 'miroworld-main'>> "%PSFILE%"
echo if (-not (Test-Path $srcTree)) {>> "%PSFILE%"
echo     Write-Host "[ERROR] 未找到源码目录"; Log "ERROR: 未找到源码目录"; exit 1>> "%PSFILE%"
echo }>> "%PSFILE%"
echo $excludes = @('data','neo4j','logs','.env','.venv','node_modules','app\data\model-config','app\backend\data','app\backend\logs','app\frontend\node_modules','app\backend\.venv','app\backend\.venv-simulation')>> "%PSFILE%"
echo function Copy-RecursiveExcluded {>> "%PSFILE%"
echo     param([string]$Src, [string]$Dst, [string[]]$Exc)>> "%PSFILE%"
echo     foreach ($i in Get-ChildItem $Src -Force) {>> "%PSFILE%"
echo         $skip = $false>> "%PSFILE%"
echo         foreach ($e in $Exc) {>> "%PSFILE%"
echo             if ($i.Name -eq $e -or $i.Name -like "$e\*" -or $i.Name -like "$e/*") { $skip = $true; break }>> "%PSFILE%"
echo         }>> "%PSFILE%"
echo         if (-not $skip) {>> "%PSFILE%"
echo             $dp = Join-Path $Dst $i.Name>> "%PSFILE%"
echo             if ($i.PSIsContainer) {>> "%PSFILE%"
echo                 if (-not (Test-Path $dp)) { New-Item -ItemType Directory -Path $dp -Force ^| Out-Null }>> "%PSFILE%"
echo                 Copy-RecursiveExcluded -Src $i.FullName -Dst $dp -Exc $Exc>> "%PSFILE%"
echo             } else {>> "%PSFILE%"
echo                 Copy-Item -Path $i.FullName -Destination $dp -Force>> "%PSFILE%"
echo             }>> "%PSFILE%"
echo         }>> "%PSFILE%"
echo     }>> "%PSFILE%"
echo }>> "%PSFILE%"
echo $robocopy = Get-Command robocopy.exe -ErrorAction SilentlyContinue>> "%PSFILE%"
echo if ($robocopy) {>> "%PSFILE%"
echo     $xd = @(); $xf = @()>> "%PSFILE%"
echo     foreach ($e in $excludes) {>> "%PSFILE%"
echo         if ($e -eq '.env') { $xf += $e } else { $xd += $e }>> "%PSFILE%"
echo     }>> "%PSFILE%"
echo     $robocopyArgs = @($srcTree, $ProjectRoot, '/E', '/XD') + $xd + @('/XF') + $xf + @('/NFL','/NDL','/NJH','/NJS','/NC','/NS')>> "%PSFILE%"
echo     robocopy.exe @robocopyArgs ^| Out-Null>> "%PSFILE%"
echo     if ($LASTEXITCODE -ge 8) { Write-Host "[ERROR] 复制失败"; Log "ERROR: 复制失败"; exit 1 }>> "%PSFILE%"
echo } else {>> "%PSFILE%"
echo     Copy-RecursiveExcluded -Src $srcTree -Dst $ProjectRoot -Exc $excludes>> "%PSFILE%"
echo }>> "%PSFILE%"
echo Write-Host "[INFO] 源码包已自动同步至最新版本！">> "%PSFILE%"
echo Log "源码同步完成">> "%PSFILE%"
echo Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue>> "%PSFILE%"
echo Remove-Item -Force $zipFile -ErrorAction SilentlyContinue>> "%PSFILE%"
echo if (Test-Path (Join-Path $ProjectRoot 'VERSION')) {>> "%PSFILE%"
echo     $localVersion = (Get-Content (Join-Path $ProjectRoot 'VERSION') -Raw).Trim()>> "%PSFILE%"
echo     Log "更新后版本: $localVersion">> "%PSFILE%"
echo }>> "%PSFILE%"
echo Log "===== 更新完成 =====">> "%PSFILE%"
echo exit 0>> "%PSFILE%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PSFILE%" "%PROJECT_ROOT%"
if errorlevel 1 (
    echo [ERROR] 免 Git 更新失败，请检查网络连接。
    call :log "ERROR: 免 Git 更新失败"
    echo 更新日志：%LOG_FILE%
    exit /b 1
)
del /f /q "%PSFILE%" >nul 2>nul
goto :afterupdate

:: ============================ Git 模式 ============================
:gitmode
echo [STEP] 正在通过 Git 极速同步最新版本代码...
git remote set-url origin https://github.com/qi-1021/miroworld.git >nul 2>nul
set "PULL_OK=0"

:: 官方源尝试：先直接 git pull，若因本地修改失败则暂存后重试（绝不丢失本地改动）
call :git_pull origin main
if not errorlevel 1 (
    set "PULL_OK=1"
    echo [INFO] 代码已同步至 GitHub 最新版本！
    call :log "git pull 成功 (origin/main)"
) else (
    echo [提示] 检测到本地修改，暂存后自动重试同步...
    call :log "git pull 失败，暂存本地修改后重试"
    git stash >nul 2>nul
    call :git_pull origin main
    if not errorlevel 1 (
        set "PULL_OK=1"
        git stash pop >nul 2>nul
        echo [INFO] 代码已同步至 GitHub 最新版本！
        call :log "git pull 成功 (origin/main, 本地修改已恢复)"
    ) else (
        git stash pop >nul 2>nul
        echo [WARN] 官方源仍失败，尝试镜像源...
        call :log "官方源失败，尝试镜像源"
        for %%m in (ghproxy.net gh-proxy.com ghfast.top mirror.ghproxy.com) do (
            git remote remove mirror >nul 2>nul
            git remote add mirror https://%%m/https://github.com/qi-1021/miroworld.git >nul 2>nul
            call :git_pull mirror main
            if not errorlevel 1 (
                set "PULL_OK=1"
                echo [INFO] 已通过镜像源同步至最新版本！
                call :log "git pull 成功 (mirror: %%m)"
                goto :gitpulldone
            )
        )
    )
)
:gitpulldone
if not "%PULL_OK%"=="1" (
    echo [ERROR] Git 同步失败，请检查网络连接。
    call :log "ERROR: git 同步失败"
    echo 更新日志：%LOG_FILE%
    exit /b 1
)
echo [INFO] 代码已同步至 GitHub 最新版本！
call :log "git 同步成功"

:afterupdate
:: 3. 检查后端依赖
echo [STEP] 检查并更新后端依赖 (启用国内镜像加速)...
if exist "app\backend\.venv-simulation" (
    rmdir /s /q "app\backend\.venv-simulation" >nul 2>nul
)

if exist "app\backend\.venv\Scripts\python.exe" (
    where uv >nul 2>nul
    if not errorlevel 1 (
        call uv pip install -r app\backend\requirements.txt --python app\backend\.venv\Scripts\python.exe --index-url https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ >nul 2>nul
    ) else (
        app\backend\.venv\Scripts\python.exe -m pip install -r app\backend\requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ -q --disable-pip-version-check
    )
)

:: 4. 构建前端
echo [STEP] 构建前端生产包...
where npm >nul 2>nul
if %ERRORLEVEL% equ 0 (
    cd app\frontend
    call npm run build
    cd ..\..
)

call :log "===== 更新完成 ====="
echo =================================================================
echo [INFO] Miroworld 更新完成！
echo 双击 scripts\start.bat 即可启动最新版本。
echo =================================================================
pause
exit /b 0

:: 执行 git pull（自动应用检测到的代理设置）
:git_pull
if defined PROXY (
    git -c http.proxy=%PROXY% -c https.proxy=%PROXY% pull %1 %2 >nul 2>nul
) else (
    git pull %1 %2 >nul 2>nul
)
exit /b %ERRORLEVEL%

:: 日志函数（置于文件末尾，仅供 call 调用）
:log
echo [%date% %time%] %~1>> "%LOG_FILE%"
exit /b 0
