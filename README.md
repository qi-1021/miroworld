# 🐟 Miroworld 可移植版 (Portable Edition)

完全独立、即插即用的 Miroworld 部署方案。

**它是什么？** 一个完整的、可在任何设备上快速启动的 Miroworld 群体智能引擎，包含：
- ✨ Miroworld 应用（前端 + 后端）
- 🗄️ Neo4j 本地数据库（自动安装）
- 🔄 跨平台启动脚本（macOS/Linux/Windows）
- 💾 完全可移植（支持移动硬盘部署）
- 🌍 **世界推演优先**：首页默认进入世界推演，产品统一围绕世界模拟主流程

---

## 🚀 3 步快速启动

### macOS/Linux
```bash
cd miroworld
chmod +x scripts/*.sh
./scripts/start.sh
```

### Windows
```cmd
cd miroworld
scripts\setup-env.bat   REM 首次/更新：主环境 Graphiti + OASIS 隔离环境
scripts\start.bat
scripts\smoke.bat       REM 可选：全流程冒烟
scripts\stop.bat --all  REM 停止前端/后端/Neo4j
```

---

## 📋 前置要求

| 工具 | 版本 | 检查 |
|------|------|------|
| Node.js | 18+ | `node --version` |
| Python | 3.11+ | `python3 --version` |

**不需要 Docker！** Neo4j 会自动下载并本地运行。

---

## 📖 文档

- `docs/USER-GUIDE.md`：使用者指南（推荐先读）
- `docs/PROJECT-STRUCTURE.md`：项目结构说明
- `docs/QUICK-START.md`：快速部署
- `docs/DEPLOYMENT.md`：部署与运维
- `docs/CONFIG-REFERENCE.md`：配置项参考
- `docs/TROUBLESHOOTING.md`：排障

## 📦 项目结构

```
miroworld/
├── app/                  # Miroworld 应用代码
│   ├── backend/         # 后端 (Flask + Graphiti)
│   ├── frontend/        # 前端 (Vue 3)
│   └── .env            # 环境变量
├── neo4j/              # Neo4j 数据库（自动安装）
├── scripts/            # 启动和安装脚本
│   ├── start.sh       # macOS/Linux 启动
│   ├── start.bat      # Windows 启动
│   ├── setup-env.sh/.bat  # 环境搭建
│   ├── smoke.sh/.bat      # 冒烟
│   └── install-neo4j.*
├── docs/              # 文档中心
│   ├── USER-GUIDE.md
│   ├── PROJECT-STRUCTURE.md
│   ├── QUICK-START.md
│   └── DEPLOYMENT.md
└── .config/           # 自定义配置
```

---

## 🌐 启动后访问

启动完成后，自动访问以下地址：

- **应用前端**：http://localhost:3000
- **后端 API**：http://localhost:5001
- **Neo4j Web**：http://localhost:7474

---

## 🔧 启动过程

脚本会自动执行：

1. **检查依赖** - 验证 Node.js、Python、uv
2. **启动 Neo4j** - 自动下载安装（仅首次）
3. **安装依赖** - npm 和 Python 包管理
4. **启动应用** - 前端和后端服务

## 💾 可移植部署

复制整个 `miroworld` 文件夹到移动硬盘：

```bash
cp -r miroworld /Volumes/MyDrive/
```

在任何设备上启动：
```bash
cd /Volumes/MyDrive/miroworld
./scripts/start.sh
```

**注**：Node.js 和 Python 仍需在各设备上安装。Neo4j 数据会随项目文件夹移动。

---

## 🛑 停止服务

按 **Ctrl+C** 停止脚本。

---

## 💡 关键特性

✅ **零 Docker 依赖** - 本地 Neo4j standalone  
✅ **全自动安装** - 首次启动自动配置所有依赖  
✅ **跨平台支持** - macOS/Linux/Windows 统一脚本  
✅ **数据持久化** - Neo4j 数据保存在 `neo4j/neo4j/data/`  
✅ **完全可移植** - 复制到移动硬盘即可使用  
✅ **双虚拟环境** - 解决 camel-ai 和 graphiti 的依赖冲突  

---

## 🔐 默认凭证

| 服务 | 用户名 | 密码 |
|------|--------|------|
| Neo4j | neo4j | password |

**⚠️ 生产环境**：请修改默认密码。

---

## 📚 文档

- **[快速启动](docs/QUICK-START.md)** - 3 步启动指南
- **[完整部署文档](docs/DEPLOYMENT.md)** - 详细配置和故障排查
- **[Miroworld 原始文档](app/LOCAL-STARTUP.md)** - 官方启动指南

---

## 🐛 常见问题

**Q: 能在 Windows 上运行吗？**  
A: 是的！提供了专用的 `.bat` 启动脚本。

**Q: 移动硬盘上的数据会丢失吗？**  
A: 不会。Neo4j 数据存储在项目文件中，会随硬盘移动。

**Q: 需要网络连接吗？**  
A: 首次启动需要下载 Neo4j 和依赖（~1GB）。之后离线也可运行。

---

## 🤝 贡献

基于上游项目 MiroFish-local：https://github.com/tt-a1i/MiroFish-local

---

## 📄 许可证

AGPL-3.0 License

---

**准备好了？** → 运行 `./scripts/start.sh` 开始！ 🚀
