# ==============================================================================
# 🐟 Miroworld Windows PowerShell 一键傻瓜式全自动安装程序
# 用法：
#   irm https://raw.githubusercontent.com/qi-1021/miroworld/main/install.ps1 | iex
# 或者（国内加速）：
#   irm https://ghproxy.net/https://raw.githubusercontent.com/qi-1021/miroworld/main/install.ps1 | iex
#
# 特性：
#   - 全流程写入安装日志 logs/install.log，方便诊断
#   - 下载自动重试（指数退避），网络抖动不再中断安装
#   - 安装前自动体检（磁盘 / 网络 / 端口）
#   - 失败时给出友好中文提示与下一步指引
# ==============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "       🐟 Miroworld 一键全自动傻瓜式安装程序 (Windows)               " -ForegroundColor Cyan
Write-Host "        (开箱即用 · 零配置依赖门槛 · 国内全生态智能加速)            " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

# ------------------------------------------------------------------------------
# 安装日志（logs/install.log）
# ------------------------------------------------------------------------------
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$LogFile = Join-Path $ScriptRoot "logs\install.log"
$LogDir = Split-Path $LogFile -Parent
try {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force -ErrorAction Stop | Out-Null
    }
    Write-Host "[STEP] 安装日志将写入: $LogFile" -ForegroundColor Blue
} catch {
    Write-Host "[WARN] 无法创建日志目录: $LogDir（将继续安装，但无法保存日志）" -ForegroundColor Yellow
}

function Write-LogToFile {
    param([string]$Message)
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $LogFile -Value "[$timestamp] $Message" -Encoding UTF8 -ErrorAction Stop
    } catch {}
}

function Write-LogStep {
    param([string]$Step, [string]$Status = "")
    Write-Host "[STEP] $Step" -ForegroundColor Blue
    if ($Status) { Write-LogToFile "[STEP] $Step [$Status]" } else { Write-LogToFile "[STEP] $Step" }
}

function Write-LogInfo {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
    Write-LogToFile "[INFO] $Message"
}

function Write-LogWarn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
    Write-LogToFile "[WARN] $Message"
}

function Write-LogError {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    Write-LogToFile "[ERROR] $Message"
}

# 友好失败出口：打印原因 / 日志路径 / 下一步指引
function Show-FriendlyError {
    param([string]$Reason, [string]$Detail = "")
    Write-LogToFile "[ERROR] 安装失败: $Reason $Detail"
    Write-Host ""
    Write-Host "=====================================================================" -ForegroundColor Red
    Write-Host "  ❌ 安装失败: $Reason" -ForegroundColor Red
    if ($Detail) {
        Write-Host "  原因: $Detail" -ForegroundColor Yellow
    }
    Write-Host "  📄 详细日志: $LogFile" -ForegroundColor Yellow
    Write-Host "  📮 请将此日志文件发送给维护者（微信/邮件均可），我们会帮您尽快解决。" -ForegroundColor Yellow
    Write-Host "=====================================================================" -ForegroundColor Red
    exit 1
}

# 兜底：任何未捕获的意外失败也会给出友好提示
trap {
    Write-LogToFile "[ERROR] 安装过程遇到意外错误: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "=====================================================================" -ForegroundColor Red
    Write-Host "  ❌ 安装失败: 安装过程遇到意外错误" -ForegroundColor Red
    Write-Host "  原因: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  📄 详细日志: $LogFile" -ForegroundColor Yellow
    Write-Host "  📮 请将此日志文件发送给维护者（微信/邮件均可），我们会帮您尽快解决。" -ForegroundColor Yellow
    Write-Host "=====================================================================" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------------------------
# 下载重试：3 次尝试 + 指数退避
# 用法：Invoke-WebRequestWithRetry -Uri <url> -OutFile <文件> [-MaxAttempts 3] [-TimeoutSec 60]
# ------------------------------------------------------------------------------
function Invoke-WebRequestWithRetry {
    param(
        [string]$Uri,
        [string]$OutFile,
        [int]$MaxAttempts = 3,
        [int]$TimeoutSec = 60
    )
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Write-LogStep "正在下载（第 $attempt/$MaxAttempts 次尝试）..."
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
            Write-LogStep "下载完成: $OutFile" "ok"
            return $true
        } catch {
            $errMsg = $_.Exception.Message
            Write-LogToFile "[CMD] 下载失败（第 $attempt/$MaxAttempts 次）: $errMsg"
            if ($attempt -lt $MaxAttempts) {
                $wait = [int][Math]::Pow(2, $attempt)
                Write-LogWarn "下载失败，${attempt}/${MaxAttempts}，$wait 秒后自动重试..."
                Start-Sleep -Seconds $wait
            }
        }
    }
    Write-LogError "下载失败: $Uri（已重试 $MaxAttempts 次）"
    return $false
}

# ------------------------------------------------------------------------------
# 安装前环境体检（磁盘 / 网络 / 端口）
# ------------------------------------------------------------------------------
function Invoke-PreflightCheck {
    Write-LogStep "环境体检（磁盘 / 网络 / 端口）..."
    $issues = 0

    # 磁盘空间（建议 ≥ 2GB）
    try {
        $drive = Get-PSDrive -Name ($PWD.Drive.Name) -ErrorAction Stop
        $freeGB = [math]::Round($drive.Free / 1GB, 2)
        if ($drive.Free -lt (2GB)) {
            Write-LogWarn "磁盘剩余空间仅 $freeGB GB（建议至少 2GB），安装可能因空间不足失败"
            $issues++
        } else {
            Write-LogInfo "磁盘剩余空间充足: $freeGB GB"
        }
    } catch {
        Write-LogWarn "无法读取磁盘剩余空间"
    }

    # 网络连通性（GitHub 直连）
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://github.com" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop | Out-Null
        Write-LogInfo "网络连通性良好（GitHub 直连可达）"
    } catch {
        Write-LogWarn "GitHub 直连不可达，将自动启用国内镜像加速节点"
    }

    # 常用端口占用检查
    foreach ($port in @(3000, 5001, 7687)) {
        try {
            $portOpen = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet
            if ($portOpen) {
                Write-LogWarn "端口 $port 已被占用（若有旧版服务在运行，可能造成冲突）"
                $issues++
            } else {
                Write-LogInfo "端口 $port 空闲"
            }
        } catch {
            Write-LogWarn "无法检测端口 $port"
        }
    }

    Write-LogStep "环境体检完成" "ok"
    if ($issues -gt 0) {
        Write-LogWarn "体检发现 $issues 项提示，将自动继续安装（若中途失败请查看上方提示与安装日志）"
    }
}

# 安装计时与日志起点
Write-LogToFile "===== Miroworld 一键安装开始 ====="
Write-LogToFile "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-LogToFile "安装目录: $((Get-Location).Path)"
Write-LogToFile "PowerShell 版本: $($PSVersionTable.PSVersion.ToString())"

$targetDir = "miroworld"
$repoUrl = "https://github.com/qi-1021/miroworld.git"
$proxyRepoUrl = "https://ghproxy.net/https://github.com/qi-1021/miroworld.git"

# 0. 安装前环境体检
Invoke-PreflightCheck

# 1 & 2. 检测 Git 或自动降级为原生 ZIP 包极速解压
Write-Host "[1/4] 检查源码同步环境..." -ForegroundColor Blue
Write-LogStep "检查源码同步环境..."

$hasGit = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
$zipUrl = "https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
$proxyZipUrl = "https://ghproxy.net/https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"

if ($hasGit) {
    Write-Host "[INFO] 检测到系统已安装 Git，使用 Git 协议同步..." -ForegroundColor Green
    Write-LogInfo "检测到系统已安装 Git，使用 Git 协议同步"
    if (Test-Path "$targetDir\.git") {
        Write-Host "[INFO] 检测到已存在 $targetDir 目录，正在同步至 GitHub 最新版本（自动保留本地修改）..." -ForegroundColor Green
        Write-LogInfo "检测到已存在 $targetDir 目录，正在同步至 GitHub 最新版本"
        Set-Location $targetDir
        git pull origin main | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-LogWarn "代码同步未完成，暂存本地修改后自动重试..."
            git stash 2>$null | Out-Null
            git pull origin main | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-LogWarn "代码同步未完成（可稍后手动更新），继续安装..."
            }
            git stash pop 2>$null | Out-Null
        }
        Write-LogStep "源码同步完成" "ok"
    } else {
        Write-LogStep "正在克隆仓库: $repoUrl"
        git clone $repoUrl $targetDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[提示] 直连较慢，切换至国内镜像通道拉取..." -ForegroundColor Yellow
            Write-LogWarn "直连较慢，切换至国内镜像通道拉取"
            git clone $proxyRepoUrl $targetDir
            if ($LASTEXITCODE -ne 0) {
                Show-FriendlyError -Reason "源码下载失败" -Detail "请检查网络连接后重新运行安装脚本"
            }
        }
        Write-LogStep "源码克隆完成" "ok"
        Set-Location $targetDir
    }
} else {
    Write-Host "[提示] 系统未安装 Git，自动启用免 Git 原生 ZIP 极速下载与解压通道..." -ForegroundColor Yellow
    Write-LogWarn "系统未安装 Git，自动启用免 Git 原生 ZIP 极速下载与解压通道"
    $zipFile = "miroworld-main.zip"

    # 优先使用高速镜像通道下载（自动重试 + 指数退避）
    Write-LogStep "正在从高速镜像节点下载源码归档包..."
    $downloadSuccess = $false
    if (Invoke-WebRequestWithRetry -Uri $proxyZipUrl -OutFile $zipFile -MaxAttempts 3 -TimeoutSec 60) {
        $downloadSuccess = $true
    } else {
        Write-Host "[提示] 镜像节点下载失败，尝试官方直连下载..." -ForegroundColor Yellow
        Write-LogWarn "镜像节点下载失败，尝试官方直连下载"
        if (Invoke-WebRequestWithRetry -Uri $zipUrl -OutFile $zipFile -MaxAttempts 3 -TimeoutSec 60) {
            $downloadSuccess = $true
        }
    }

    if (-not $downloadSuccess) {
        Show-FriendlyError -Reason "源码包下载失败" -Detail "请检查网络连接后重新运行安装脚本"
    }

    # 自动解压
    Write-Host "[STEP] 正在自动解压源码包..." -ForegroundColor Blue
    Write-LogStep "正在自动解压源码包..."
    $tempExtract = "miroworld-extract-temp"
    if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue }
    try {
        Expand-Archive -Path $zipFile -DestinationPath $tempExtract -Force -ErrorAction Stop
    } catch {
        Show-FriendlyError -Reason "源码包解压失败" -Detail "下载的文件可能已损坏，请重新运行安装脚本"
    }

    if (Test-Path "$tempExtract\miroworld-main") {
        if (-not (Test-Path $targetDir)) { New-Item -ItemType Directory -Path $targetDir | Out-Null }
        try {
            Copy-Item -Path "$tempExtract\miroworld-main\*" -Destination $targetDir -Recurse -Force -ErrorAction Stop
        } catch {
            Show-FriendlyError -Reason "源码目录复制失败" -Detail "请检查磁盘空间与目录权限后重试"
        }
    } else {
        Show-FriendlyError -Reason "源码包解压失败" -Detail "未找到解压后的源码目录，请重新运行安装脚本"
    }

    Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
    Remove-Item -Force $zipFile -ErrorAction SilentlyContinue
    Write-LogStep "源码包自动解压释放成功" "ok"
    Set-Location $targetDir
}

# 进入项目目录后，将日志路径指向项目内 logs 目录（避免写到项目外部）
$ScriptRoot = (Get-Location).Path
$LogFile = Join-Path $ScriptRoot "logs\install.log"
$LogDir = Split-Path $LogFile -Parent
try {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force -ErrorAction Stop | Out-Null
    }
    Write-LogToFile "安装日志已切换至项目内: $LogFile"
    Write-Host "[INFO] 安装日志将写入: $LogFile" -ForegroundColor Green
} catch {
    Write-LogWarn "无法创建日志目录: $LogDir（将继续安装，但无法保存日志）"
}

# 3. 安装后端 Python 依赖、前端依赖并构建前端生产包
Write-Host "[3/5] 正在安装后端 Python 依赖与前端构建产物（国内镜像加速）..." -ForegroundColor Blue
Write-LogStep "正在安装后端 Python 依赖与前端构建产物"

# 3.1 后端 Python 依赖
$reqFile = "app\backend\requirements.txt"
if (Test-Path $reqFile) {
    Write-LogStep "正在安装后端 Python 依赖 (requirements.txt)..."
    $pythonCmd = "python"
    if (Test-Path "app\backend\.venv\Scripts\python.exe") {
        $pythonCmd = "app\backend\.venv\Scripts\python.exe"
        Write-LogInfo "检测到项目虚拟环境，使用: $pythonCmd"
    }
    & $pythonCmd -m pip install -r $reqFile -i https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ -q --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        Show-FriendlyError -Reason "后端 Python 依赖安装失败" -Detail "请检查网络连接后重新运行安装脚本，或将安装日志发送给维护者"
    }
    Write-LogStep "后端 Python 依赖安装完成" "ok"
} else {
    Write-LogWarn "未找到 $reqFile，跳过后端 Python 依赖安装"
}

# 3.2 前端依赖与生产构建
if (Test-Path "app\frontend\package.json") {
    Push-Location "app\frontend"
    try {
        Write-LogStep "正在安装前端依赖 (npm install)..."
        npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            Show-FriendlyError -Reason "前端依赖安装失败 (npm install)" -Detail "请检查网络连接后重新运行安装脚本，或将安装日志发送给维护者"
        }
        Write-LogStep "前端依赖安装完成" "ok"
        Write-LogStep "正在构建前端生产包 (npm run build)..."
        npm run build
        if ($LASTEXITCODE -ne 0) {
            Show-FriendlyError -Reason "前端构建失败 (npm run build)" -Detail "请检查网络连接后重新运行安装脚本，或将安装日志发送给维护者"
        }
        Write-LogStep "前端构建完成" "ok"
    } finally {
        Pop-Location
    }
} else {
    Write-LogWarn "未找到 app\frontend\package.json，跳过前端依赖安装与构建"
}

# 4. 运行环境配置与启动服务
Write-Host "[4/5] 正在拉起环境自愈与全套服务 (Neo4j / Python / Node.js)..." -ForegroundColor Blue
Write-LogStep "正在拉起环境自愈与全套服务 (Neo4j / Python / Node.js)"
if (Test-Path "start.bat") {
    & cmd.exe /c "start.bat"
    if ($LASTEXITCODE -ne 0) {
        Write-LogWarn "start.bat 返回非零退出码: $LASTEXITCODE（服务可能已在后台启动，可稍后运行 .\start.bat 确认）"
    }
    Write-LogStep "服务启动脚本执行完成" "ok"
} else {
    Write-LogWarn "未找到 start.bat，跳过环境配置"
}

# 5. 完成
Write-LogStep "安装完成" "ok"
Write-LogToFile "[END] ===== 安装完成 ====="
Write-Host "`n=====================================================================" -ForegroundColor Green
Write-Host "  🎉 恭喜！Miroworld 已在当前机器全部配置就绪！" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "👉 运行启动服务：" -ForegroundColor Yellow
Write-Host "   cd $targetDir ; .\start.bat" -ForegroundColor Cyan
Write-Host "`n🌐 启动后浏览器访问：http://localhost:3000" -ForegroundColor Yellow
Write-Host "📄 安装日志已保存至: $LogFile" -ForegroundColor Yellow
Write-Host "=====================================================================" -ForegroundColor Green
