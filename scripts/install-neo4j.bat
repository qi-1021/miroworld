@echo off
chcp 65001 >nul
REM ==============================================================================
REM Neo4j 自动下载和安装脚本 (Windows)
REM 支持国内华为云、中科院软件所与官方镜像多源容灾
REM ==============================================================================

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set NEO4J_DIR=%PROJECT_ROOT%\neo4j

echo [INFO] 检查 Neo4j 知识图谱数据库环境...

if exist "%NEO4J_DIR%\neo4j\bin\neo4j.bat" (
    echo [INFO] ✓ Neo4j 已安装在 %NEO4J_DIR%\neo4j
    exit /b 0
)

if not exist "%NEO4J_DIR%" mkdir "%NEO4J_DIR%"

echo [INFO] 正在下载 Neo4j 5.26.0 便携版 (支持国内多源自动加速)...
cd /d "%NEO4J_DIR%"

REM 使用 PowerShell 多源下载（国内华为云/中科院镜像优先，官方源兜底）
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
  "$ProgressPreference = 'SilentlyContinue'; " ^
  "$urls = @('https://mirrors.huaweicloud.com/neo4j/neo4j-community-5.26.0-windows.zip', " ^
  "          'https://mirror.iscas.ac.cn/neo4j/neo4j-community-5.26.0-windows.zip', " ^
  "          'https://dist.neo4j.org/neo4j-community-5.26.0-windows.zip', " ^
  "          'https://dist.neo4j.org/neo4j-community-5.26.0-windows-amd64.zip'); " ^
  "$ok = $false; " ^
  "foreach ($u in $urls) { " ^
  "  Write-Host \"尝试从节点下载 Neo4j: $u\"; " ^
  "  try { " ^
  "    Invoke-WebRequest -Uri $u -OutFile 'neo4j-5.26.0.zip' -UseBasicParsing -TimeoutSec 180; " ^
  "    if ((Test-Path 'neo4j-5.26.0.zip') -and ((Get-Item 'neo4j-5.26.0.zip').Length -gt 10000000)) { " ^
  "      $ok = $true; " ^
  "      Write-Host '✓ Neo4j 下载成功！'; " ^
  "      break; " ^
  "    } " ^
  "  } catch { " ^
  "    Write-Host '节点连接受限，切换下一节点...'; " ^
  "    if (Test-Path 'neo4j-5.26.0.zip') { Remove-Item 'neo4j-5.26.0.zip' -Force } " ^
  "  } " ^
  "}; " ^
  "if (-not $ok) { exit 1 }"

if errorlevel 1 (
    echo [ERROR] 所有 Neo4j 下载节点均失败，请检查网络连接
    exit /b 1
)

echo [INFO] 正在解压 Neo4j...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path 'neo4j-5.26.0.zip' -DestinationPath '%NEO4J_DIR%' -Force; " ^
  "$extracted = Get-ChildItem '%NEO4J_DIR%' | Where-Object { $_.PSIsContainer -and ($_.Name -like 'neo4j-community*') } | Select-Object -First 1; " ^
  "if ($extracted) { " ^
  "  if (Test-Path '%NEO4J_DIR%\neo4j') { Remove-Item -Recurse -Force '%NEO4J_DIR%\neo4j' }; " ^
  "  Move-Item $extracted.FullName '%NEO4J_DIR%\neo4j'; " ^
  "}; " ^
  "if (Test-Path 'neo4j-5.26.0.zip') { Remove-Item 'neo4j-5.26.0.zip' -Force }"

if not exist "%NEO4J_DIR%\neo4j\bin\neo4j.bat" (
    echo [ERROR] Neo4j 解压与配置失败
    exit /b 1
)

echo [INFO] ✓ Neo4j 便携版安装配置完成！
echo [INFO] 位置: %NEO4J_DIR%\neo4j
endlocal
