# 🚀 快速启动指南

## 系统要求

- ✅ Node.js 18+
- ✅ Python 3.11+  
- ✅ 无需 Docker（已集成 Neo4j standalone）

## 3 步快速启动

### macOS / Linux

```bash
cd mirofish-portable
chmod +x scripts/*.sh
./scripts/start.sh
```

### Windows

```cmd
cd mirofish-portable
scripts\start.bat
```

---

## 第一次启动会自动：

1. ✓ 下载并安装 Neo4j
2. ✓ 安装所有 Node.js 依赖
3. ✓ 创建 Python 虚拟环境
4. ✓ 启动所有服务

## 你会看到：

```
前端: http://localhost:3000  ✓
后端: http://localhost:5001  ✓
Neo4j: http://localhost:7474 ✓
```

## 完成！🎉

打开浏览器访问 http://localhost:3000

---

## 常见问题

**Q: 启动过程中缺少什么？**  
A: 脚本会自动提示。如果缺少 Node.js 或 Python，请先安装它们。

**Q: 能在移动硬盘上运行吗？**  
A: 是的！只需将整个 `mirofish-portable` 文件夹复制到移动硬盘。各台设备上只需有 Node.js 和 Python 3.11+。

**Q: 需要 Docker 吗？**  
A: 不需要！Neo4j 会自动安装在 `neo4j/neo4j/` 目录。

**Q: 数据会保存在哪里？**  
A: Neo4j 数据存储在 `neo4j/neo4j/data/` 目录，会随着整个项目夹移动。

---

详细文档：[DEPLOYMENT.md](DEPLOYMENT.md)
