# Miroworld 可移植部署指南

完全独立的 Miroworld 部署方案，可直接复制到移动硬盘，在任何设备上快速启动。

## 📦 项目结构

```
miroworld/
├── app/                    # Miroworld 应用代码
│   ├── backend/           # Python 后端 (Flask)
│   ├── frontend/          # Vue 3 前端
│   ├── package.json
│   ├── .env              # 环境变量配置
│   └── ...
├── neo4j/                  # Neo4j 数据库（首次启动时自动安装）
├── scripts/                # 启动和安装脚本
│   ├── start.sh           # macOS/Linux 启动脚本
│   ├── start.bat          # Windows 启动脚本
│   ├── install-neo4j.sh   # macOS/Linux Neo4j 安装
│   ├── install-neo4j.bat  # Windows Neo4j 安装
│   └── ...
├── .config/                # 自定义配置
└── docs/                   # 文档
    └── DEPLOYMENT.md      # 本文件
```

## 🚀 快速开始

### macOS / Linux

```bash
# 1. 进入项目目录
cd miroworld

# 2. 赋予执行权限
chmod +x scripts/*.sh

# 3. 首次启动：自动安装 Neo4j 和依赖
./scripts/start.sh
```

### Windows

```cmd
REM 1. 进入项目目录（在文件管理器中打开或命令行中 cd 到该目录）
REM 2. 双击运行
scripts\start.bat
```

## 🔧 前置要求

| 工具 | 版本 | 说明 | 检查命令 |
|------|------|------|---------|
| **Node.js** | 18+ | 前端运行环境 | `node --version` |
| **Python** | 3.11+ | 后端运行环境 | `python3 --version` |
| **uv** | 最新版 | Python 包管理器（可选，脚本会自动安装） | `uv --version` |

不需要 Docker！所有依赖都会自动下载和配置。

## ⚙️ 启动过程详解

运行启动脚本时会自动执行以下步骤：

### 1. 验证前置依赖
- 检查 Node.js、Python、uv 是否已安装
- 如果缺少，脚本会给出安装提示

### 2. 启动 Neo4j 数据库
- 如果首次启动，自动下载并安装 Neo4j 5.26.0
- Neo4j 地址：`bolt://localhost:7687`
- 用户名：`neo4j`  
- 密码：`password`

### 3. 安装应用依赖
- 安装 Node.js 依赖（前端）
- 安装 Python 依赖（后端）
- 创建两个虚拟环境：
  - `.venv`：主环境（Neo4j 6.x）
  - `.venv-simulation`：模拟环境（Neo4j 5.23.0）
  > 两个环境分离是为了解决 `camel-ai` 和 `graphiti-core` 的 Neo4j 版本冲突

### 4. 启动服务
- 启动前端（Vue 3）：`http://localhost:3000`
- 启动后端（Flask）：`http://localhost:5001`
- 启动 Neo4j Web 界面：`http://localhost:7474`

## 📝 环境变量配置

编辑 `app/.env` 修改配置：

```env
# 阿里百炼 LLM API
LLM_API_KEY=sk-xxxxxxxx（填入你的密钥）
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Neo4j 数据库
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# 后端选择
ZEP_BACKEND=graphiti  # 使用本地 Neo4j
```

## 🌐 服务地址

启动完成后，访问以下地址：

- **前端应用**：http://localhost:3000
- **后端 API**：http://localhost:5001
- **Neo4j 管理器**：http://localhost:7474（用户名：neo4j，密码：password）

## 🛑 停止服务

### macOS / Linux
```bash
# 按 Ctrl+C 停止脚本
# 或手动杀死进程
pkill -f "npm run dev"
pkill -f "neo4j"
```

### Windows
```cmd
REM 按 Ctrl+C 停止脚本
REM 或通过任务管理器关闭进程
```

## 🔄 数据清理

如需清空 Neo4j 数据库：

```bash
# macOS/Linux
cd app/backend
.venv/bin/python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password'))
with d.session() as s: s.run('MATCH (n) DETACH DELETE n')
d.close()
print('数据已清空')
"
```

或登录 Neo4j 管理界面执行：
```cypher
MATCH (n) DETACH DELETE n
```

## 🛠️ 手动安装 Neo4j

如果启动脚本自动安装失败，可以手动运行安装脚本：

### macOS / Linux
```bash
chmod +x scripts/install-neo4j.sh
./scripts/install-neo4j.sh
```

### Windows
```cmd
scripts\install-neo4j.bat
```

## 🚨 常见问题排查

### 1. 端口被占用

**问题**：`Address already in use`

**解决**：
```bash
# macOS/Linux
lsof -i :3000 -i :5001 -i :7687 -i :7474
# 杀死占用端口的进程
kill -9 <PID>

# Windows
netstat -ano | findstr :3000
# 在任务管理器中结束进程
```

### 2. Python 版本不兼容

**问题**：`camel-oasis requires Python 3.10-3.11`

**解决**：
- 检查 Python 版本：`python3 --version`
- 如果是 Python 3.12+，需要降级或创建 3.11 虚拟环境

### 3. Node 依赖安装失败

**问题**：`npm ERR! ...`

**解决**：
```bash
# 清理缓存
npm cache clean --force

# 重新安装
cd app
npm run setup:all
```

### 4. Neo4j 启动失败

**问题**：Neo4j 无法连接

**解决**：
```bash
# 检查 Neo4j 日志
tail -f neo4j/neo4j/logs/neo4j.log

# 重置数据库
rm -rf neo4j/neo4j/data
# 重新启动
```

## 💾 部署到移动硬盘

### 步骤 1：复制项目

```bash
# 假设移动硬盘挂载在 /Volumes/MyDrive
cp -r ~/Desktop/miroworld /Volumes/MyDrive/
```

### 步骤 2：在不同设备上启动

```bash
# 挂载移动硬盘后
cd /Volumes/MyDrive/miroworld

# macOS/Linux
./scripts/start.sh

# Windows
scripts\start.bat
```

### 注意事项

- **Node.js/Python** 仍需在每台设备上安装（虚拟环境会自动创建）
- **Neo4j** 会在移动硬盘上自动安装和运行，数据存储在 `neo4j/neo4j/data/`
- **第一次启动会较慢**（需下载依赖），之后启动会更快

## 📊 虚拟环境说明

该部署使用两个虚拟环境来解决依赖冲突：

| 环境 | 位置 | Neo4j | 用途 |
|------|------|-------|------|
| 主环境 | `app/backend/.venv` | 6.x | Graphiti 图谱构建 |
| 模拟环境 | `app/backend/.venv-simulation` | 5.23.0 | CAMEL-AI 多智能体模拟 |

启动脚本会自动管理两个环境的活跃状态。

## 🔐 安全提示

- **默认密码**：此部署使用默认密码 `password`
- 在生产环境中修改 Neo4j 密码：
  ```bash
  neo4j/bin/neo4j-admin dbms set-initial-password <new_password>
  ```
- 更新 `.env` 中的 `NEO4J_PASSWORD`

## 📞 获取帮助

- 查看项目原始文档：`app/LOCAL-STARTUP.md`
- 上游项目：https://github.com/tt-a1i/MiroFish-local
- Neo4j 文档：https://neo4j.com/docs/

---

**版本**：1.0  
**更新日期**：2026-03-07  
**支持平台**：macOS、Linux、Windows
