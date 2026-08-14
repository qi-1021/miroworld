# ⚙️ 配置参考

## 环境变量 (.env)

位置：`app/.env`

### LLM 配置

```env
# LLM API 密钥（必需）
# 获取地址：https://bailian.console.aliyun.com
LLM_API_KEY=sk-REDACTED

# LLM 服务地址
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 模型名称
LLM_MODEL_NAME=qwen-plus

# 可选：Python LLM 客户端配置
OPENAI_API_KEY=sk-REDACTED
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### Neo4j 配置

```env
# Neo4j Bolt 连接地址
NEO4J_URI=bolt://localhost:7687

# Neo4j 用户名
NEO4J_USER=neo4j

# Neo4j 密码
NEO4J_PASSWORD=password
```

### Graphiti 配置

```env
# Graphiti 默认 LLM 模型
GRAPHITI_LLM_MODEL=qwen3-max

# Embedding 模型配置
EMBEDDING_API_KEY=sk-REDACTED
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
```

### 后端选择

```env
# 选择后端：'cloud' 或 'graphiti'
ZEP_BACKEND=graphiti  # 本地 Neo4j

# 如果选择 cloud，需要配置
ZEP_API_KEY=z_REDACTED
```

---

## LLM API 提供商

### 1. 阿里百炼（推荐）

**优点**：
- 免费额度充足
- 支持国内网络
- 兼容 OpenAI SDK

**申请步骤**：
1. 访问 https://bailian.console.aliyun.com
2. 创建 API Key
3. 复制到 `.env`

**配置**：
```env
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus  # 或 qwen-max、qwen3-max 等
```

---

### 2. OpenAI

**优点**：
- 功能完整
- 社区资源丰富

**需求**：
- 付费账户（GPT-4 API）
- 信用卡

**配置**：
```env
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4  # 或 gpt-3.5-turbo
```

---

### 3. 其他兼容提供商

支持任何兼容 OpenAI SDK 的 LLM API，例如：
- LocalAI
- Ollama
- vLLM
- Text Generation WebUI

**配置示例**：
```env
LLM_API_KEY=sk-xxxxxxxx  # 或任何 API Key
LLM_BASE_URL=http://localhost:8000/v1  # 本地服务
LLM_MODEL_NAME=llama-2-7b  # 模型名称
```

---

## 端口配置

### 默认端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 | 3000 | Vue.js 开发服务器 |
| 后端 | 5001 | Flask API 服务器 |
| Neo4j Bolt | 7687 | 数据库连接 |
| Neo4j Browser | 7474 | Web 管理界面 |

### 修改端口

**前端** (修改 `app/frontend/package.json`):
```json
"dev": "vite --port 3001"
```

**后端** (修改 `app/backend/app.py`):
```python
if __name__ == '__main__':
    app.run(port=5002)
```

**Neo4j** (修改 `neo4j/neo4j/conf/neo4j.conf`):
```
server.bolt.listen_address=:7688
server.http.listen_address=:7475
```

---

## 虚拟环境管理

### 主环境（Graphiti）

位置：`app/backend/.venv`

```bash
# 激活
source app/backend/.venv/bin/activate  # macOS/Linux
# 或
app\backend\.venv\Scripts\activate  # Windows

# 安装包
uv pip install <package_name>

# 停用
deactivate
```

### 模拟环境（CAMEL-AI）

位置：`app/backend/.venv-simulation`

```bash
# 激活（仅在运行模拟时）
source app/backend/.venv-simulation/bin/activate

# 预装包
- camel-oasis==0.2.5
- openai
- python-dotenv
```

**为什么两个环境？**

- `camel-ai` 要求 Neo4j 5.23.0
- `graphiti-core` 要求 Neo4j 6.x
- 使用两个环境隔离这些冲突

---

## 数据库管理

### 连接 Neo4j

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")
)

with driver.session() as session:
    result = session.run("MATCH (n) RETURN count(n) as count")
    print(result.single()["count"])

driver.close()
```

### 常用 Cypher 查询

```cypher
# 查看所有节点和关系统计
MATCH (n) RETURN labels(n) as label, count(*) as count
UNION
MATCH ()-[r]->() RETURN type(r) as type, count(*) as count

# 删除所有数据
MATCH (n) DETACH DELETE n

# 创建索引（加快查询）
CREATE INDEX FOR (n:Entity) ON (n.name)
CREATE INDEX FOR (n:Entity) ON (n.id)
```

### 备份数据

```bash
# Neo4j 在线备份
cd neo4j/neo4j
./bin/neo4j-admin dump --database=neo4j --to=/path/to/backup.dump

# 恢复备份
./bin/neo4j-admin restore --database=neo4j /path/to/backup.dump
```

---

## 日志配置

### Neo4j 日志

位置：`neo4j/neo4j/logs/`

```
neo4j.log          # 主日志
query.log          # 查询日志
debug.log          # 调试信息
```

### 应用日志

**后端日志**：在启动脚本终端输出

**前端日志**：浏览器开发者工具（F12）

### 调整日志级别

编辑 `neo4j/neo4j/conf/neo4j.conf`:
```
dbms.logs.general.level=DEBUG
dbms.logs.query.enabled=true
```

---

## 性能优化

### Neo4j 内存配置

编辑 `neo4j/neo4j/conf/neo4j.conf`:
```
# 对于 8GB 系统
dbms.memory.heap.initial_size=2g
dbms.memory.heap.max_size=2g
dbms.memory.pagecache.size=2g
```

### 数据库连接池

修改 `app/backend/app.py`:
```python
GraphDatabase.driver(
    uri,
    auth=auth,
    max_connection_pool_size=100,
    connection_timeout=30
)
```

---

## 安全建议

⚠️ **仅用于开发环境！**

### 修改默认密码

```bash
cd neo4j/neo4j/bin
./neo4j-admin dbms set-initial-password myNewPassword123!
```

更新 `.env`:
```env
NEO4J_PASSWORD=myNewPassword123!
```

### 启用 Neo4j 认证

已默认启用。修改 `neo4j.conf`:
```
dbms.security.auth_enabled=true
```

### API 密钥安全

- 不要将 `.env` 提交到 Git
- 使用 `.gitignore` 排除：
  ```
  app/.env
  neo4j/neo4j/data/
  neo4j/neo4j/logs/
  ```

---

## 环境变量模板

复制到 `app/.env` 并填入你的值：

```env
# ===== LLM 配置 =====
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# ===== Neo4j =====
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# ===== Graphiti =====
GRAPHITI_LLM_MODEL=qwen3-max
EMBEDDING_API_KEY=sk-xxxxxxxx
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4

# ===== 后端选择 =====
ZEP_BACKEND=graphiti
```

---

更多信息参见：[完整部署文档](DEPLOYMENT.md)
