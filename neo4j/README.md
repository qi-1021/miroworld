# Neo4j 便携部署说明

本目录包含便携版 Neo4j（从 Homebrew 打包）：程序、数据与启动模板都跟随项目文件夹。

## 📦 目录结构

- **neo4j-program/**：Neo4j 程序文件（原 Homebrew Cellar 拷贝，约 262MB）
  - `libexec/`：真实运行目录（bin、lib、conf 等）
- **neo4j-data/**：项目内数据目录（跟随文件夹走）
  - `data/`：Neo4j 数据库（databases、transactions 等）
  - `logs/`：运行日志
- **neo4j-data-persistent/**：旧的数据备份（517MB，保留备用）
- **conf-template/neo4j.conf**：便携配置模板（占位符 `__NEO4J_DATA_DIR__` / `__NEO4J_LOG_DIR__`）
- **homebrew.mxcl.neo4j.plist.backup**：原 Homebrew 启动配置备份

## 🚀 启动方式（推荐）

直接运行项目根目录的启动脚本，它会自动完成全部工作：

```bash
./scripts/start.sh        # macOS / Linux
scripts\start.bat         # Windows
```

启动脚本会：
1. 识别 Neo4j 安装目录（兼容 `neo4j/neo4j` 与 `neo4j/neo4j-program` 两种布局）
2. 根据模板生成运行时配置（数据/日志目录指向项目内的 `neo4j-data/`）
3. 用 `NEO4J_CONF` 指向生成的配置并启动 Neo4j

手动启动（调试用）：

```bash
# 先生成配置
mkdir -p neo4j/run neo4j/neo4j-data/data neo4j/neo4j-data/logs
sed -e "s|__NEO4J_DATA_DIR__|$PWD/neo4j/neo4j-data/data|g" \
    -e "s|__NEO4J_LOG_DIR__|$PWD/neo4j/neo4j-data/logs|g" \
    neo4j/conf-template/neo4j.conf > neo4j/run/neo4j.conf

# 再启动
NEO4J_CONF="$PWD/neo4j/run" ./neo4j/neo4j-program/libexec/bin/neo4j console
```

## ⚠️ 重要限制：路径不能含中文

**Neo4j（JVM）无法在含中文等非 ASCII 字符的路径下运行**（访问 plugins/conf/logs 目录会报错）。因此：

- 项目必须放在**纯英文路径**下，例如 `/Volumes/Data/mirofish-portable`
- 当前位于 `/Volumes/mac第三磁盘/...`（含中文）时，启动脚本会给出明确提示并中止 Neo4j 启动

两个解决方案：

1. **将项目移动到纯英文路径**（推荐）——整个文件夹可整体移动，数据全部跟随。
2. **改用系统安装的 Neo4j**：`brew install neo4j` 后启动（原 Homebrew 数据仍在 `/opt/homebrew/var/neo4j/data`，可继续使用），再运行启动脚本（脚本检测到 7687 端口已监听会跳过内置 Neo4j）。

## 🔧 配置说明

- **HTTP 端口**：7474（浏览器访问）
- **Bolt 端口**：7687（数据库连接）
- **默认用户名/密码**：neo4j / password（见 `app/.env` 的 `NEO4J_*` 配置）
- **数据目录**：`neo4j/neo4j-data/data`（跟随项目，可整体拷贝迁移）

## 📝 说明

- Neo4j 版本：2026.02.2
- 原安装方式：Homebrew（`/opt/homebrew/Cellar/neo4j/2026.02.2`）
- 数据备份时间：2026年3月7日
- Java 依赖：需要系统安装 Java 17+（启动脚本会自动检测）
