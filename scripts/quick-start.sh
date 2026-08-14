#!/bin/bash

# MiroFish 快速启动脚本 - 第二磁盘版
# 用法: bash ~/Desktop/startup-mirofish-disk2.sh

echo "🚀 MiroFish 应用启动"
echo "=================="
echo ""

# 检查磁盘是否挂载
if [ ! -d "/Volumes/mac第二磁盘/mirofish-portable" ]; then
  echo "❌ 错误: 第二磁盘未挂载或路径不存在"
  echo "请确保 /Volumes/mac第二磁盘 已连接"
  exit 1
fi

echo "✓ 第二磁盘已检测"
echo ""

# 启动 Neo4j (如未运行)
if ! lsof -i :7687 >/dev/null 2>&1; then
  echo "启动 Neo4j..."
  brew services start neo4j 2>/dev/null || true
  sleep 3
fi

if lsof -i :7687 >/dev/null 2>&1; then
  echo "✓ Neo4j 运行在端口 7687"
else
  echo "❌ Neo4j 启动失败"
  exit 1
fi

echo ""

# 启动后端
echo "启动后端 (Flask)..."
cd "/Volumes/mac第二磁盘/mirofish-portable/app/backend"
nohup uv run python run.py > /tmp/mirofish-backend.log 2>&1 &
sleep 3

if lsof -i :5001 >/dev/null 2>&1; then
  echo "✓ 后端运行在端口 5001"
else
  echo "❌ 后端启动失败"
  echo "   查看日志: tail -f /tmp/mirofish-backend.log"
  exit 1
fi

echo ""

# 启动前端
echo "启动前端 (Vue3)..."
cd "/Volumes/mac第二磁盘/mirofish-portable/app/frontend"
nohup npm run dev > /tmp/mirofish-frontend.log 2>&1 &
sleep 5

if lsof -i :3000 >/dev/null 2>&1; then
  echo "✓ 前端运行在端口 3000"
else
  echo "❌ 前端启动失败"
  echo "   查看日志: tail -f /tmp/mirofish-frontend.log"
  exit 1
fi

echo ""
echo "=================="
echo "✨ 所有服务已启动"
echo "=================="
echo ""
echo "访问 MiroFish:"
echo "  🌐 http://localhost:3000"
echo ""
echo "详细信息:"
echo "  Neo4j:  http://localhost:7474"
echo "  API:    http://localhost:5001"
echo ""
echo "查看日志:"
echo "  后端: tail -f /tmp/mirofish-backend.log"
echo "  前端: tail -f /tmp/mirofish-frontend.log"
echo ""
echo "停止应用:"
echo "  pkill -f 'uv run python run.py'  (后端)"
echo "  pkill -f 'npm run dev'            (前端)"
echo "  brew services stop neo4j         (数据库)"
echo ""
