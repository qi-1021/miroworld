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

# 1. 检测 Git
Write-Host "[1/4] 检查基础运行环境..." -ForegroundColor Blue
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] 检测到系统中尚未安装 Git。请先前往 https://git-scm.com/download/win 安装 Git for Windows 后重试。" -ForegroundColor Red
    exit 1
}

# 2. 拉取仓库
Write-Host "[2/4] 正在从 GitHub 同步最新版本系统源码..." -ForegroundColor Blue
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
Write-Host "   cd $targetDir ; .\scripts\start.bat" -ForegroundColor Cyan
Write-Host "`n🌐 启动后浏览器访问：http://localhost:3000" -ForegroundColor Yellow
Write-Host "=====================================================================" -ForegroundColor Green
