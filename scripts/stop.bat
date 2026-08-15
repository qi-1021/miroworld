@echo off
REM MiroFish Windows 停止脚本
REM 用法：stop.bat [--all] [--force]
REM   stop.bat         停前端(:3000) + 后端(:5001)，仅终止"MiroFish 相关"进程
REM   stop.bat --all   连本项目 Neo4j(:7687) 一起停
REM   stop.bat --force 不等待优雅退出，直接强杀
REM
REM 说明：通过命令行特征（mirofish/run.py/vite/npm run dev 等）识别本项目进程，
REM 避免误杀占用同端口的无关程序。

setlocal enabledelayedexpansion

set STOP_NEO4J=0
set FORCE_ALL=0
for %%a in (%*) do (
    if /i "%%a"=="--all" set STOP_NEO4J=1
    if /i "%%a"=="--force" set FORCE_ALL=1
)

echo [INFO] 停止 MiroFish 前端/后端进程...

call :stop_listening_port 3000 "前端"
call :stop_listening_port 5001 "后端"

if "%STOP_NEO4J%"=="1" (
    echo [INFO] --all: 同时停止 Neo4j (:7687)
    call :stop_listening_port 7687 "Neo4j"
) else (
    echo [INFO] Neo4j 未停止（如需停止请加 --all：stop.bat --all）
)

echo [INFO] 兜底清理残留壳进程（未绑定端口但属于本项目的 node/python/vite 等）...
call :kill_by_marker run_world_simulation
call :kill_by_marker run_parallel_simulation
call :kill_by_marker run_reddit_simulation
call :kill_by_marker run_twitter_simulation

echo [INFO] 停止完成。
echo [INFO] 日志目录: app\backend\logs\（start-backend.log / start-frontend.log，可删除）
endlocal
exit /b 0

REM ==== 子程序：按端口停止监听进程；仅终止命令行含本项目特征的进程 ====
:stop_listening_port
set "port=%~1"
set "name=%~2"
netstat -ano | findstr ":%port%" | findstr "LISTENING" >nul 2>nul
if errorlevel 1 (
    echo [INFO] 端口 %port%: 无进程在监听
    goto :eof
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%port%" ^| findstr "LISTENING"') do (
    set "_pid=%%a"
    set "_islocal=0"
    for /f "delims=" %%c in ('wmic process where "ProcessId=!_pid!" get CommandLine /value 2^>nul ^| find "CommandLine="') do (
        set "_cmd=%%c"
        echo !_cmd! | find /i "mirofish"      >nul 2>nul && set "_islocal=1"
        echo !_cmd! | find /i "run.py"       >nul 2>nul && set "_islocal=1"
        echo !_cmd! | find /i "vite"         >nul 2>nul && set "_islocal=1"
        echo !_cmd! | find /i "concurrently" >nul 2>nul && set "_islocal=1"
        echo !_cmd! | find /i "npm run dev"  >nul 2>nul && set "_islocal=1"
    )
    if "!_islocal!"=="1" (
        echo [INFO] 结束 PID %%a (%name% :%port%)
        if "%FORCE_ALL%"=="1" (
            taskkill /F /PID %%a >nul 2>nul
        ) else (
            taskkill /PID %%a >nul 2>nul
        )
    ) else (
        echo [WARN] 端口 %port% 的 PID %%a 非本项目进程，跳过（如需停止请手动处理）
    )
)
goto :eof

REM ==== 子程序：按命令行标记兜底清理残留子进程（模拟等） ====
:kill_by_marker
set "marker=%~1"
set "tmpfile=%TEMP%\mirofish-stop-%RANDOM%.txt"
wmic process get ProcessId,CommandLine 2>nul > "%tmpfile%"
if errorlevel 1 (
    if exist "%tmpfile%" del /q "%tmpfile%" >nul 2>nul
    goto :eof
)
REM wmic 输出形如 "ProcessId=1234  CommandLine=""...marker..."""
for /f "tokens=1,2 delims==" %%A in ('type "%tmpfile%" ^| findstr /i "!marker!"') do (
    for /f "tokens=1 delims= " %%P in ("%%B") do (
        echo [INFO] 结束残留进程 PID %%P (marker: !marker!)
        taskkill /F /PID %%P >nul 2>nul
    )
)
del /q "%tmpfile%" >nul 2>nul
goto :eof
