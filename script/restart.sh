#!/usr/bin/env bash
set -euo pipefail

# 对话剧场 / Dialogue Theater —— 重启脚本
# 1. 重新编译前端产物
# 2. 重新构建并启动 Docker 服务

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

echo "==> 编译前端产物..."
cd frontend
npm install
npm run build
cd "${PROJECT_ROOT}"

echo "==> 停止现有容器..."
docker compose down

echo "==> 重新构建并启动服务..."
docker compose up -d --build

echo "==> 服务已启动"
echo "    前端: http://localhost:8080"
echo "    后端: http://localhost:8000"
echo "    健康检查: curl http://localhost:8000/health"
