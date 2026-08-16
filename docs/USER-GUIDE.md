# MiroFish 使用指南

MiroFish 是一个本地优先的小说世界推演工具：读取背景设定与正文，抽取多线时间线、构建知识图谱、检测设定冲突，并进行世界模拟推演。本文面向普通使用者。

---

## 1. 快速开始

### macOS / Linux
```bash
cd mirofish-portable
bash scripts/setup-env.sh   # 首次/更新环境
bash scripts/start.sh       # 启动完整服务
bash scripts/smoke.sh       # 可选：全流程冒烟
bash scripts/stop.sh --all  # 停止全部
```

### Windows
```bat
cd mirofish-portable
scripts\setup-env.bat
scripts\start.bat
scripts\smoke.bat
scripts\stop.bat --all
```

启动后：
- 前端：http://localhost:3000
- 后端：http://localhost:5001
- Neo4j 管理台：http://localhost:7474

---

## 2. 首页两种模式

首页控制台有两个模式，**世界推演**现在是默认第一优先：

1. **世界推演**：上传/粘贴“背景设定”和“小说正文”，生成世界设定库，之后可做时间线抽取、冲突检测、知识图谱、世界模拟。
2. **世界推演**：从背景资料与章节正文出发，生成可分叉、可修正的世界模拟时间线。

> 首页默认只提供世界推演模式，不再暴露旧媒体分析入口。

---

## 3. 世界设定库（World Library）

进入方式：
- 首页导航右上角“世界设定库”按钮，或
- 在世界推演模式下填写资料后点击“创建世界”。

页面内可以：
- 上传背景/正文文件（txt / md / pdf），或直接粘贴文本。
- 查看已保存文件、分块数量、字符数。
- 点击“保存到设定库”建立索引。

### 冲突检测
- 背景和正文都非空后，点击“检测背景与正文冲突”。
- 每条冲突可以：
  - **以背景为准**（accepted）
  - **忽略**（dismissed）
  - **自定义辩解**（justified）：填写你的裁定说明，系统会保存下来。

### 知识图谱
- 点击“构建世界图谱”会先由 LLM 生成本体，再写入 Graphiti/Neo4j。
- 构建完成后可点击“补边”补齐关系边。
- 如果构建任务因重启丢失，页面会提示“任务不存在，请重新构建”。

### 项目快照
- 页面右上角“导出快照”可下载 `.mirofish.json`。
- “导入快照”可从文件恢复一个全新项目（含时间线、设定库、冲突、人物、模型绑定）。

---

## 4. 时间线

时间线是 MiroFish 的核心：

- **抽取**：点击“抽取时间线”，按“人物故事 / 背景设定”分别抽取。
- **线程/维度**：如果背景是多国、多势力、多线并行，事件会带有 `thread_name` 和 `dimension`；时间线上方可以用“线程/维度”过滤。
- **分叉推演**：在任意事件上点击“在此分叉推演”，生成独立分支；主线视图不会混入分支事件。
- **未来推演**：输入目标，生成未来事件（虚线区）。
- **人工修正**：点击事件卡片“修正”，可改摘要、时间、地点、排序。
- **批量操作**：进入“批量选择”，可多选删除，或删除当前时间点之后的所有事件。
- **异议**：对事件的时间/地点/分类等提交异议，便于后续校对。
- **结构视图**：点击“结构视图”可查看树状（父子事件）、网状（关联事件）、并行线程、世界外/元叙事四种结构。

> 提示：如果结尾是“寓言/导演/高维视角”，建议在抽取时让模型把它标记为 `dimension=allegory/meta`，或手动在修正中把维度改掉，避免和主时间线混排。

---

## 5. 世界模拟

世界推演模式下的“世界模拟”是独立世界推演：

- 填写“任务目标”（可选）。
- 选择步数。
- 选择时间推进方式：
  - **固定分钟**：每步推进固定分钟，适合短时事件。
  - **叙事跳跃**：每步使用你提供的时间标签（如“数日后、三个月后、一年后”），适合真正的世界推演。
- 可勾选“把当前时间线作为推演上下文”，让世界模拟承接已有时间线。
- 可选择“起点事件”，让世界模拟从某个时间线事件开始推演。
- 启动后可以暂停/恢复/停止，也可以对角色“采访”。

---

## 6. 命令行 CLI（供 AI Agent / 自动化操作）

后端自带一个面向 AI Agent 的命令行工具，所有操作都支持 `--json` 输出。

```bash
cd app/backend

# 健康检查
python scripts/mirofish_cli.py --json health

# 项目
python scripts/mirofish_cli.py --json project list
python scripts/mirofish_cli.py --json project create --name "新项目"
python scripts/mirofish_cli.py --json project export --project-id proj_xxx --output backup.mirofish.json
python scripts/mirofish_cli.py --json project import --file backup.mirofish.json

# 世界设定库
python scripts/mirofish_cli.py --json world save --project-id proj_xxx --background "..." --story "..."
python scripts/mirofish_cli.py --json world get --project-id proj_xxx

# 时间线
python scripts/mirofish_cli.py --json timeline extract --project-id proj_xxx --source bg --wait
python scripts/mirofish_cli.py --json timeline get --project-id proj_xxx
python scripts/mirofish_cli.py --json timeline threads --project-id proj_xxx

# 冲突检测
python scripts/mirofish_cli.py --json conflict detect --project-id proj_xxx

# 世界模拟
python scripts/mirofish_cli.py --json sim start --project-id proj_xxx --steps 6 --time-mode narrative --time-jumps "数日后,三个月后,一年后"

# 内置助手
python scripts/mirofish_cli.py --json assistant ask --project-id proj_xxx --question "结尾和前面不像同一世界，怎么办？"
```

> 注意：`--json` 要放在子命令前面，例如 `mirofish --json project list`。

## 7. 内置项目助手

在世界设定库右上角点击“助手”：

- 输入问题，助手会读取当前项目上下文并回答“该去哪个栏目改、怎么改”。
- 如果助手判断可以直接执行操作（修改时间线事件、批量删除、保存人物、保存设定等），它会直接执行并把结果返回给你。

---

## 7. 模型设置

- 右下角“模型设置”可以接入 OpenAI 兼容的聊天/向量模型。
- 添加连接时会自动探测 `/models`、`/chat/completions` 和 `/embeddings`。
- 如果某个模型支持 embedding，系统会自动把它加入向量能力。
- 向量偏好可选 `cloud / local / auto`。

---

## 8. 数据与备份

所有数据都在 `app/backend/data/` 下：
- `world/`：世界设定库与冲突报告
- `world-timeline/`：时间线、人物档案、线程清单、任务状态
- `world-sim/`：世界模拟状态与事件
- `world-graph/`：图谱补边缓存
- `task-manager/`：通用任务持久化

最稳妥的备份方式：在世界设定库页面“导出快照”，得到一个 `.mirofish.json` 文件。

---

## 9. 常见问题

### 9.1 空项目删不掉？
新版删除会级联清理 `uploads/projects`、`world/`、`world-timeline/`、`world-sim/`、`world-graph/` 下对应目录；如果仍删不掉，请确认是否正在被其它进程占用。

### 9.2 长设定文本抽取质量差？
系统现在会对长背景做“分块线索识别”，不会因为一次超长调用失败就整体降级为普通抽取。如果仍然不好，建议：
- 在背景文本里用标题/分段明确区分国家/势力/时间线；
- 先运行一次“抽取时间线（背景）”，再人工修正线程名；
- 把特别长的设定拆成多个文件上传。

### 9.3 Neo4j 没启动？
- macOS/Linux：`bash scripts/start.sh` 会自动启动。
- Windows：`start.bat` 会自动启动。
- 也可以手动访问 http://localhost:7474 确认。

---

## 10. 更多文档

- `docs/QUICK-START.md`：快速部署
- `docs/DEPLOYMENT.md`：部署与运维
- `docs/CONFIG-REFERENCE.md`：配置项参考
- `docs/TROUBLESHOOTING.md`：排障
- `docs/DADI-VALIDATION.md`：《大地巡旅》长设定集验证与处理建议
