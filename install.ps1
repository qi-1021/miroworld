# ==============================================================================
# 🐟 Miroworld Windows PowerShell 一键傻瓜式全自动安装程序
# 用法：
#   irm https://raw.githubusercontent.com/qi-1021/miroworld/main/install.ps1 | iex
# 或者（国内加速）：
#   irm https://ghproxy.net/https://raw.githubusercontent.com/qi-1021/miroworld/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "       🐟 Miroworld 一键全自动傻瓜式安装程序 (Windows)               " -ForegroundColor Cyan
Write-Host "        (开箱即用 · 零配置依赖门槛 · 国内全生态智能加速)            " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

$targetDir = "miroworld"
$repoUrl = "https://github.com/qi-1021/miroworld.git"
$proxyRepoUrl = "https://ghproxy.net/https://github.com/qi-1021/miroworld.git"

# 1 & 2. 检测 Git 或自动降级为原生 ZIP 包极速解压
Write-Host "[1/4] 检查源码同步环境..." -ForegroundColor Blue

$hasGit = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
$zipUrl = "https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
$proxyZipUrl = "https://ghproxy.net/https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"

if ($hasGit) {
    Write-Host "[INFO] 检测到系统已安装 Git，使用 Git 协议同步..." -ForegroundColor Green
    if (Test-Path "$targetDir\.git") {
        Write-Host "[INFO] 检测到已存在 $targetDir 目录，正在同步至最新..." -ForegroundColor Green
        Set-Location $targetDir
        git pull origin main
    } else {
        try {
            git clone $repoUrl $targetDir
        } catch {
            Write-Host "[提示] 直连较慢，切换至国内镜像通道拉取..." -ForegroundColor Yellow
            git clone $proxyRepoUrl $targetDir
        }
        Set-Location $targetDir
    }
} else {
    Write-Host "[提示] 系统未安装 Git，自动启用免 Git 原生 ZIP 极速下载与解压通道..." -ForegroundColor Yellow
    $zipFile = "miroworld-main.zip"
    $downloadSuccess = $false
    
    # 尝试国内高速镜像下载
    try {
        Write-Host "[STEP] 正在从高速镜像节点下载源码归档包..." -ForegroundColor Blue
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $proxyZipUrl -OutFile $zipFile -UseBasicParsing -TimeoutSec 30
        $downloadSuccess = $true
    } catch {
        Write-Host "[提示] 镜像节点重试，尝试官方直连下载..." -ForegroundColor Yellow
        try {
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing -TimeoutSec 60
            $downloadSuccess = $true
        } catch {
            Write-Host "[ERROR] 源码包下载失败，请检查网络连接。" -ForegroundColor Red
            exit 1
        }
    }
    
    if ($downloadSuccess) {
        Write-Host "[STEP] 正在自动解压源码包..." -ForegroundColor Blue
        $tempExtract = "miroworld-extract-temp"
        if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract }
        Expand-Archive -Path $zipFile -DestinationPath $tempExtract -Force
        
        if (Test-Path "$tempExtract\miroworld-main") {
            if (-not (Test-Path $targetDir)) { New-Item -ItemType Directory -Path $targetDir | Out-Null }
            Copy-Item -Path "$tempExtract\miroworld-main\*" -Destination $targetDir -Recurse -Force
        }
        
        Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
        Remove-Item -Force $zipFile -ErrorAction SilentlyContinue
        Write-Host "[INFO] 源码包自动解压释放成功！" -ForegroundColor Green
        Set-Location $targetDir
    }
}

# 3. 运行环境配置脚本
Write-Host "[3/4] 正在全自动配置 Python 依赖、Node.js 前端环境与 Neo4j 数据库..." -ForegroundColor Blue
if (Test-Path "scripts\setup-env.bat") {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c scripts\setup-env.bat" -Wait -NoNewWindow
}

# 4. 完成
Write-Host "`n=====================================================================" -ForegroundColor Green
Write-Host "  🎉 恭喜！Miroworld 已在当前机器全部配置就绪！" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "👉 运行启动服务：" -ForegroundColor Yellow
Write-Host "   cd $targetDir ; .\start.bat" -ForegroundColor Cyan
Write-Host "`n🌐 启动后浏览器访问：http://localhost:3000" -ForegroundColor Yellow
Write-Host "=====================================================================" -ForegroundColor Green
