@echo off
setlocal EnableDelayedExpansion

REM 微信聊天视频生成器 —— 重启脚本（Windows）
REM 1. 重新编译前端产物
REM 2. 重新构建并启动 Docker 服务

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\"

cd /d "%PROJECT_ROOT%"

echo ==^> 编译前端产物...
cd frontend
call npm install
if errorlevel 1 (
    echo 前端依赖安装失败
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo 前端编译失败
    exit /b 1
)
cd /d "%PROJECT_ROOT%"

echo ==^> 停止现有容器...
call docker compose down

echo ==^> 重新构建并启动服务...
call docker compose up -d --build

echo ==^> 服务已启动
echo     前端: http://localhost:8080
echo     后端: http://localhost:8000
echo     健康检查: curl http://localhost:8000/health