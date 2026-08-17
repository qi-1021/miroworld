@echo off
REM Neo4j 自动下载和安装脚本 (Windows)

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set NEO4J_DIR=%PROJECT_ROOT%\neo4j

echo [INFO] 检查 Neo4j 安装...

if exist "%NEO4J_DIR%\neo4j" (
    echo [WARN] Neo4j 已安装在 %NEO4J_DIR%\neo4j
    set /p REINSTALL=是否重新安装? (y/n):
    if not "!REINSTALL!"=="y" (
        echo [INFO] 取消安装
        exit /b 0
    )
    echo [INFO] 删除旧版本...
    rmdir /s /q "%NEO4J_DIR%\neo4j"
)

if not exist "%NEO4J_DIR%" mkdir "%NEO4J_DIR%"

echo [INFO] 下载 Neo4j 5.26.0 (支持国内多源自动加速)...
cd /d "%NEO4J_DIR%"

REM 使用 PowerShell 多源下载（国内镜像优先，官方源兜底）
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$urls = @('https://dist.neo4j.org/neo4j-community-5.26.0-windows-amd64.zip', 'https://mirrors.huaweicloud.com/neo4j/neo4j-community-5.26.0-windows-amd64.zip', 'https://mirror.iscas.ac.cn/neo4j/neo4j-community-5.26.0-windows-amd64.zip'); ^
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
  $ProgressPreference = 'SilentlyContinue'; ^
  $ok = $false; ^
  foreach ($u in $urls) { ^
    Write-Host \"尝试从下载节点获取: $u\"; ^
    try { ^
      Invoke-WebRequest -Uri $u -OutFile 'neo4j-5.26.0.zip' -TimeoutSec 180; ^
      if ((Test-Path 'neo4j-5.26.0.zip') -and ((Get-Item 'neo4j-5.26.0.zip').Length -gt 10000000)) { ^
        $ok = $true; ^
        Write-Host '✓ 下载成功！'; ^
        break; ^
      } ^
    } catch { ^
      Write-Host '该节点连接超时或受限，切换下一节点...'; ^
      if (Test-Path 'neo4j-5.26.0.zip') { Remove-Item 'neo4j-5.26.0.zip' -Force } ^
    } ^
  }; ^
  if (-not $ok) { exit 1 }"

if errorlevel 1 (
    echo [ERROR] 所有 Neo4j 下载节点均失败，请检查网络连接
    pause
    exit /b 1
)

echo [INFO] 解压...
powershell -Command "Expand-Archive -Path neo4j-5.26.0.zip -DestinationPath ."

if errorlevel 1 (
    echo [ERROR] 解压失败
    pause
    exit /b 1
)

echo [INFO] 重命名文件夹...
ren "neo4j-community-5.26.0-windows-amd64" "neo4j"

echo [INFO] 清理安装文件...
del neo4j-5.26.0.zip

echo [INFO] ✓ Neo4j 安装完成！
echo [INFO] 位置: %NEO4J_DIR%\neo4j
echo [INFO] 下次运行 start.bat 时会自动启动 Neo4j

pause
