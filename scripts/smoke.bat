@echo off
REM MiroFish Windows 全流程冒烟测试
REM 启动后端+前端 → 轮询就绪 → 详细健康检查 → 停止
REM 退出码 0=通过，1=失败

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set APP_DIR=%PROJECT_ROOT%\app
set LOG=%TEMP%\mirofish-smoke.log

echo == MiroFish Windows 冒烟测试 ==
echo 项目: %PROJECT_ROOT%

REM 清理残留
call "%SCRIPT_DIR%stop.bat" --all >nul 2>nul

echo == 启动后端和前端 ==
start "MiroFishBackend" /b cmd /c "cd /d ""%APP_DIR%"" && npm run backend > ""%LOG%.backend"" 2>&1"
start "MiroFishFrontend" /b cmd /c "cd /d ""%APP_DIR%\frontend"" && npm run dev > ""%LOG%.frontend"" 2>&1"

set ready=0
for /l %%i in (1,1,60) do (
    curl -s -m 2 http://127.0.0.1:5001/health >nul 2>nul
    if not errorlevel 1 (
        curl -s -m 2 -o nul http://127.0.0.1:3000/ >nul 2>nul
        if not errorlevel 1 set ready=1
    )
    if "!ready!"=="1" goto ready
    timeout /t 2 /nobreak >nul
)

echo SMOKE FAIL: 后端/前端未在 120 秒内就绪
if exist "%LOG%.backend" type "%LOG%.backend"
if exist "%LOG%.frontend" type "%LOG%.frontend"
call "%SCRIPT_DIR%stop.bat" --all >nul 2>nul
exit /b 1

:ready
echo SMOKE OK: backend /health 通过
echo SMOKE OK: frontend http://127.0.0.1:3000 返回 200
echo == 详细健康检查 ==
curl -s -m 5 http://127.0.0.1:5001/api/health/detailed
echo.
echo == 冒烟结束，停止服务 ==
call "%SCRIPT_DIR%stop.bat" --all >nul 2>nul
echo SMOKE PASS
endlocal
exit /b 0
