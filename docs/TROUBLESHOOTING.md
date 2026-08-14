# 🔧 故障排查指南

## 启动脚本问题

### "command not found: ./scripts/start.sh"

**原因**：脚本没有执行权限

**解决**：
```bash
chmod +x scripts/*.sh
./scripts/start.sh
```

---

### "Node.js 未安装"

**原因**：系统没有安装 Node.js

**解决**：
```bash
# macOS (使用 Homebrew)
brew install node

# 或访问 https://nodejs.org 下载安装
```

验证：
```bash
node --version  # 应该显示 v18.0.0 或更高
```

---

### "Python3 未安装"

**原因**：系统没有安装 Python

**解决**：
```bash
# macOS
brew install python3

# Linux (Ubuntu/Debian)
sudo apt-get install python3

# 或访问 https://python.org
```

验证：
```bash
python3 --version  # 应该显示 3.11+ 或更高
```

---

## Neo4j 问题

### "Cannot download Neo4j"

**原因**：网络连接问题

**解决**：
```bash
# 检查网络连接
ping google.com

# 如果网络正常，手动下载
cd neo4j
curl -L -o neo4j-5.26.0-unix.tar.gz \
  https://dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz

# 解压
tar -xzf neo4j-5.26.0-unix.tar.gz
mv neo4j-community-5.26.0 neo4j
```

---

### "Neo4j 启动失败"

**症状**：端口 7687 无法连接

**排查**：
```bash
# 查看 Neo4j 日志
tail -f neo4j/neo4j/logs/neo4j.log

# 检查端口占用
lsof -i :7687

# 重置数据库
rm -rf neo4j/neo4j/data
# 重新启动脚本
```

---

### "Unable to connect to localhost:7687"

**原因**：Neo4j 尚未完全启动

**解决**：等待 10-15 秒再试。如果持续失败：
```bash
# 手动启动 Neo4j
cd neo4j/neo4j/bin
./neo4j console

# 在另一个终端中测试连接
python3 -c "from neo4j import GraphDatabase; d=GraphDatabase.driver('bolt://localhost:7687'); print('连接成功')"
```

---

## 端口占用问题

### "Address already in use: port 3000/5001/7687"

某个端口已被其他进程占用。

**macOS/Linux**：
```bash
# 查找占用特定端口的进程
lsof -i :3000
lsof -i :5001
lsof -i :7687

# 例如：查找占用 3000 的进程
lsof -i :3000 | grep LISTEN
# 输出类似：node  12345  user  10u

# 杀死进程
kill -9 12345
```

**Windows**：
```cmd
# 查找占用特定端口的进程
netstat -ano | findstr :3000

# 输出类似：TCP  0.0.0.0:3000  0.0.0.0:0  LISTENING  12345

# 杀死进程（命令提示符以管理员运行）
taskkill /PID 12345 /F
```

或改变应用端口（编辑 `app/package.json`）。

---

## 依赖安装问题

### "npm ERR! ..."

**原因**：npm 依赖冲突

**解决**：
```bash
cd app
# 清理缓存
npm cache clean --force

# 删除 node_modules
rm -rf node_modules frontend/node_modules

# 重新安装
npm run setup:all
```

---

### "Python: No module named..."

**原因**：Python 虚拟环境不完整

**解决**：
```bash
cd app/backend

# 删除虚拟环境
rm -rf .venv .venv-simulation

# 重新创建
npm run setup:backend
```

---

### "camel-oasis requires Python 3.10-3.11"

**原因**：Python 版本不兼容

**解决**：
```bash
# 检查版本
python3 --version

# 如果是 3.12+，需要降级或使用 3.11 创建虚拟环境
# macOS 上如果有多个版本
python3.11 -m venv app/backend/.venv-simulation
```

---

## 数据库问题

### Neo4j 数据已损坏

**症状**：启动后无结果，或查询错误

**解决**：
```bash
# 备份旧数据（可选）
mv neo4j/neo4j/data neo4j/neo4j/data.backup

# 重新启动脚本，Neo4j 会创建新的数据库
./scripts/start.sh
```

---

### 清空所有数据

**方法 1：通过 Neo4j Web 界面**
1. 访问 http://localhost:7474
2. 用户名：`neo4j`，密码：`password`
3. 执行 Cypher 查询：
   ```cypher
   MATCH (n) DETACH DELETE n
   ```

**方法 2：通过脚本**
```bash
cd app/backend
source .venv/bin/activate  # 或 Windows: .venv\Scripts\activate
python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password'))
with d.session() as s: s.run('MATCH (n) DETACH DELETE n')
print('数据已清空')
"
deactivate
```

---

## 应用相关问题

### "Front-end not responding"

**原因**：前端服务未启动或崩溃

**排查**：
```bash
# 检查前端进程
ps aux | grep "npm run frontend"

# 或查看前端日志
# 通常在终端输出中，查找 "vue-cli-service serve" 的错误信息

# 手动启动前端
cd app/frontend
npm run dev
```

---

### "Backend API 500 error"

**原因**：后端加载配置或连接数据库失败

**排查**：
```bash
# 检查环境变量
cat app/.env

# 验证 Neo4j 连接
curl http://localhost:7687

# 查看后端日志（应在启动脚本的输出中）
```

---

### "模拟环境不工作"

**原因**：模拟环境虚拟环境有问题

**解决**：
```bash
cd app/backend

# 删除模拟环境
rm -rf .venv-simulation

# 重新创建
uv venv .venv-simulation --python 3.11
source .venv-simulation/bin/activate
uv pip install camel-oasis==0.2.5 openai python-dotenv
deactivate
```

---

## 移动硬盘部署问题

### "在移动硬盘上启动失败"

**原因**：路径问题或权限问题

**解决**：
```bash
# 确保进入正确目录
cd /Volumes/MyDrive/mirofish-portable

# 检查脚本权限
ls -la scripts/

# 重新赋予权限
chmod +x scripts/*.sh

# 重新启动
./scripts/start.sh
```

---

### "数据没有保存"

**排查**：
```bash
# 确认 Neo4j 数据目录位置
ls -la neo4j/neo4j/data/

# 确认有写入权限
touch neo4j/neo4j/data/test.txt
rm neo4j/neo4j/data/test.txt
```

---

## 性能问题

### "启动很慢"

**第一次启动**：正常，需要下载 Neo4j 和依赖（5-10 分钟）

**后续启动仍然很慢**：
- 磁盘 I/O 速度慢（尤其是移动硬盘）
- 检查硬盘空间
- 关闭其他应用以释放系统资源

---

## 联系支持

如果问题解决不了：

1. 查看完整日志：
   ```bash
   # 重新启动，保存输出
   ./scripts/start.sh 2>&1 | tee startup.log
   ```

2. 检查原项目文档：https://github.com/tt-a1i/MiroFish-local

3. 报告问题时包含：
   - 操作系统和版本
   - Node.js 和 Python 版本
   - 完整的错误日志
   - `startup.log` 文件

---

**祝你使用愉快！** 🎉
