@echo off
REM MiroFish Windows 停止脚本：结束监听 3000/5001 的进程（Neo4j 可由 start.bat 管理）
REM 用法：stop.bat [--all]

setlocal

echo [INFO] 停止 MiroFish 前端/后端进程...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo [INFO] 结束 PID %%a (前端 :3000)
    taskkill /F /PID %%a >nul 2>nul
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001" ^| findstr "LISTENING"') do (
    echo [INFO] 结束 PID %%a (后端 :5001)
    taskkill /F /PID %%a >nul 2>nul
)

if /i "%~1"=="--all" (
    echo [INFO] --all: 同时停止 Neo4j (:7687)
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7687" ^| findstr "LISTENING"') do (
        echo [INFO] 结束 PID %%a (Neo4j :7687)
        taskkill /F /PID %%a >nul 2>nul
    )
)

echo [INFO] 停止完成。
endlocal
