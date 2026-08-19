# 📖 Miroworld 完整使用教程

> **给谁看？** 给第一次打开 Miroworld 的你，也给想把这台“世界推演引擎”用到极致的你。  
> 前 5 章照着点就能跑通；第 7 章“手机远程”和第 8-9 章“排障/反馈”确实不像普通用户会干的事——但既然你问了，就写到**照着做就能通**。

**阅读建议**：第一次用只看 **第 2-4 章** 即可；遇到问题再跳到 **第 8-9 章**。

---

## 目录

- [1. 写在前面：这东西到底是干嘛的](#1-写在前面这东西到底是干嘛的)
- [2. 安装与启动（从零到看到界面）](#2-安装与启动从零到看到界面)
- [3. 模型配置（3 分钟接好大脑）](#3-模型配置3-分钟接好大脑)
- [4. 第一次推演：10 分钟端到端流程](#4-第一次推演10-分钟端到端流程)
- [5. 核心功能详解](#5-核心功能详解)
  - [5.1 世界设定库](#51-世界设定库-world-bible)
  - [5.2 冲突检测](#52-冲突检测)
  - [5.3 知识图谱](#53-知识图谱)
  - [5.4 时间线](#54-时间线)
  - [5.5 世界模拟](#55-世界模拟)
  - [5.6 线索/人物/结构视图](#56-线索人物结构视图)
- [6. 助手与 CLI（给爱用命令行/Agent 的你）](#6-助手与-cli)
- [7. 手机/平板远程高效连接](#7-手机平板远程高效连接重点)
- [8. 如何发现错误（日志在哪、看什么）](#8-如何发现错误日志在哪看什么)
- [9. 如何提交反馈（让你提的 Issue 一次就被看懂）](#9-如何提交反馈让你提的-issue-一次就被看懂)
- [10. 数据备份与迁移](#10-数据备份与迁移)
- [11. 常见问题速查](#11-常见问题速查)

---

## 1. 写在前面：这东西到底是干嘛的

一句话：**把你的世界设定 + 小说正文，变成可推演、可分叉、可回溯的“活世界”**。

- 你写的是背景设定和情节，机器做的是记忆、时序、关系和推演。Miroworld 把这四件事拆成流水线：**设定库 → 时间线 → 图谱 → 模拟 → 分叉**。
- 适合小说/剧本/TRPG 创作者用来查设定冲突、理时间线、试“如果当时选了另一条路会怎样”。

> 详细设计动机与技术选型见 [README 为什么要这样做](../README.md#为什么要做这个东西技术原理简述)。

---

## 2. 安装与启动（从零到看到界面）

### 2.1 一行命令安装（推荐）

无需提前克隆，打开终端直接粘贴：

**macOS / Linux**
```bash
# 官方
curl -fsSL https://raw.githubusercontent.com/qi-1021/miroworld/main/install.sh | bash
# 国内镜像（网络慢时用）
curl -fsSL https://ghproxy.net/https://raw.githubusercontent.com/qi-1021/miroworld/main/install.sh | bash
```

**Windows（PowerShell，右键“以管理员身份运行”更稳）**
```powershell
irm https://raw.githubusercontent.com/qi-1021/miroworld/main/install.ps1 | iex
# 国内镜像
irm https://ghproxy.net/https://raw.githubusercontent.com/qi-1021/miroworld/main/install.ps1 | iex
```

装完后你会得到一个 `miroworld/` 文件夹，里面已包含 Python/Node/Java/Neo4j 的便携环境（首次会自动下载，国内已走镜像加速）。

### 2.2 启动 / 停止 / 更新

**启动**
```bash
cd miroworld
# macOS / Linux
./start.sh
# Windows
start.bat
```
看到 `前端: http://localhost:3000` `后端: http://localhost:5001` `Neo4j: http://localhost:7474` 即成功，Windows 还会自动唤起浏览器。

**停止**
```bash
# macOS / Linux：终端按 Ctrl+C，或另开终端
./stop.sh        # 仅停前后端
./stop.sh --all  # 连 Neo4j 一起停
# Windows
stop.bat
stop.bat --all
```

**更新（免密，一键对齐最新版）**
```bash
./update.sh   # macOS / Linux
update.bat    # Windows 双击即可
```

### 2.3 验证是否真的起来了

- 浏览器打开 `http://localhost:3000` 能看到首页
- 后端健康：`http://localhost:5001/api/health` 返回 `{"status":"ok",...}`
- Neo4j：`http://localhost:7474` 用 `neo4j / password` 能登录
- 可选冒烟：`bash scripts/smoke.sh`（或 `scripts\smoke.bat`）全流程自检

---

## 3. 模型配置（3 分钟接好大脑）

> Miroworld 的所有“智能”都来自你接入的模型。**不内置任何密钥**，你需要在右下角“模型设置”里填自己的。

### 3.1 四类角色

| 角色 | 干什么 | 掉线会怎样 |
|------|--------|------------|
| **主对话/决策 Primary** | 设定库、时间线、冲突、模拟的默认大脑 | 全部功能受影响 |
| **沙盘推演 Simulation** | 世界模拟专用（可与主模型不同） | 模拟变慢或回退到主模型 |
| **图谱抽取 Graphiti LLM** | 知识图谱实体/关系抽取 | 图谱构建失败 |
| **向量检索 Embedding** | 设定库分块检索 | 检索质量下降 |

### 3.2 推荐配置（可直接照抄）

**主模型（任选其一即可）**
- ① `Opencode go/mimo-v2.5`（性价比最高，推荐）
- ② `DeepSeek-v4-flash-0731`（无论哪家网关）
- ③ `gpt-5-luna`（有钱任性）
- ④ 自建/其他：智商建议 ≥ `qwen3:27b`，否则时间线与推演会频繁出错

**向量模型（免费且好）**
- `硅基流动 BAAI/bge-m3`（完全免费，不接受反驳）

> 接入方式千变万化，最快办法：把你的供应商“Base URL + API Key + Model ID”截图丢给身边任意 AI（豆包/通义/DeepSeek 都行），问它“这是 OpenAI 兼容接口吗？怎么填到 Miroworld？”

### 3.3 操作步骤

1. 点右下角 **“模型设置”**
2. **添加连接**：填 `Base URL`（如 `https://api.openai.com/v1`）、`API Key`，点“探测”——会自动测 `/models`、`/chat/completions`、`/embeddings`
3. **创建模型条目**：从探测结果选一个 `model_id`，勾 `chat` / `embedding` 能力，保存
4. **绑定角色**：在“角色绑定”里把 4 类角色分别指向模型，保存
5. **测试**：点“测试”按钮，真跑一次 `hello`，成功再去推演

**本地 Ollama**：`Base URL` 填 `http://localhost:11434/v1`，`API Key` 随便填 `ollama`，模型填本地已 `ollama pull` 的名字。

---

## 4. 第一次推演：10 分钟端到端流程

> 用一份 2-3 千字的背景 + 一章正文就能跑通。

1. **创建项目**：首页选“世界推演”→ 输入项目名→ 创建
2. **导入设定库**：进“世界设定库”→ 拖拽 `背景设定.txt` 到“背景”区，`第一章.txt` 到“正文”区（也支持 pdf/docx）→ 点“保存到设定库”，看右上角分块数/字符数
3. **抽时间线**：切到“时间线”→ 点“抽取时间线”→ 选 `story`（正文）→ 等待完成（下方有实时日志）
4. **看图谱**：点“构建世界图谱”→ 等本体生成→ 再点“补边”
5. **跑模拟**：切“世界模拟”→ 填任务目标如“推演主角接下来三个月的抉择”→ 步数选 `6`，时间推进选“叙事跳跃”填 `数日后,三个月后,一年后` → 点“启动模拟”→ 看每轮角色的移动/协同/警戒日志
6. **玩分叉**：在时间线的任意事件上点“在此分叉推演”，输入“如果当时主角没有救那个人”，看新分支

通了这一次，后面就是重复“改设定→重抽→重推”的循环。

---

## 5. 核心功能详解

### 5.1 世界设定库（World Bible）

- **在哪**：首页右上角“世界设定库”或创建世界后自动进入
- **能做什么**：上传/粘贴背景与正文，分块索引，查看已保存文件、分块数、字符数
- **技巧**：长设定建议按国家/势力分文件上传，标题用 `## 罗德岛` 这种 Markdown 标题，抽取更准

### 5.2 冲突检测

- 触发：背景与正文都非空后，点“检测背景与正文冲突”
- 每条冲突可：**以背景为准（accepted）** / **忽略（dismissed）** / **自定义辩解（justified）**——填你的裁定，系统会存档，后续可导出

### 5.3 知识图谱

- 点“构建世界图谱”会先让 LLM 生成本体（人物/组织/地理/概念/物品），再写入 Graphiti/Neo4j
- 构建中可在日志里看本体 JSON；完成后可点“补边”补齐关系
- 若提示“任务不存在，请重新构建”，说明后端重启丢了临时任务，重建即可（数据不丢）

### 5.4 时间线

- **抽取**：按 `人物故事 / 背景设定` 分别抽，互不覆盖
- **线程/维度**：多线并行会带 `thread_name`（如“罗德岛线”）和 `dimension`（如 `reality/allegory/meta`），顶部可过滤
- **寓言/元叙事**：若结尾是导演视角/高维俯瞰，建议抽取时让模型标 `dimension=meta`，或事后批量把该段事件的维度改掉，避免与主时间线混排
- **分叉**：任意事件→“在此分叉推演”生成独立分支，主线视图不混入
- **未来推演**：输入目标，生成虚线区未来事件
- **修正**：点事件卡片“修正”可改摘要、时间、地点、排序
- **批量**：进入“批量选择”可多选删除，或“一键删除该时间点之后”
- **结构视图**：树状（父子）、网状（关联）、并行线程、世界外/元叙事 4 种

### 5.5 世界模拟

- **任务目标**（可选）：如“推演三个月内势力博弈”
- **步数**：一般 4-8 步，太多会慢
- **时间推进**：
  - 固定分钟：每步固定 `N` 分钟，适合短时事件
  - 叙事跳跃：填 `数日后,三个月后,一年后`，适合长线推演
- **上下文**：可勾“把当前时间线作为上下文”，或选“起点事件”让模拟从某事件开始
- **控制**：启动后可暂停/恢复/停止；可对角色“采访”（让 LLM 以角色口吻回答）

### 5.6 线索/人物/结构视图

- **线索（Threads）**：自动归纳的多线线索清单
- **人物（Characters）**：从时间线聚合的人物卡
- **结构视图**：见 5.4 最后一点

---

## 6. 助手与 CLI

### 6.1 内置助手

- 在世界设定库右上角点“助手”，输入如“结尾和前面不像同一世界，怎么办？”
- 助手会读取当前项目上下文，告诉你该去哪个栏目改；若判断可直接执行（如批量删除、保存人物），会直接执行并回显结果

### 6.2 CLI（给 AI Agent / 批处理）

```bash
cd app/backend
PY="app/backend/.venv/bin/python"  # Windows: app\backend\.venv\Scripts\python.exe
CLI="app/backend/scripts/mirofish_cli.py"

# 健康
$PY $CLI --json health
# 项目
$PY $CLI --json project list
$PY $CLI --json project create --name "新项目"
# 设定库
$PY $CLI --json world save --project-id proj_xxx --background "..." --story "..."
# 时间线
$PY $CLI --json timeline extract --project-id proj_xxx --source story --wait
$PY $CLI --json timeline get --project-id proj_xxx
# 图谱
$PY $CLI --json graph build-world --project-id proj_xxx --wait
# 模拟
$PY $CLI --json sim start --project-id proj_xxx --steps 6 --time-mode narrative --time-jumps "数日后,三个月后,一年后"
# 助手
$PY $CLI --json assistant ask --project-id proj_xxx --question "怎么修时间线？"
```
> `--json` 放在子命令前：`mirofish --json project list`

---

## 7. 手机/平板远程高效连接（重点）

> **坦白说，这不是普通用户的必做题**。但如果你想躺在沙发上用手机改设定、或让朋友远程看推演，按下面做，5 分钟通。

### 7.1 最高效：同一 Wi-Fi 局域网直连（零配置，首选）

**原理**：手机和电脑连同一个 Wi-Fi，就是同一个局域网，直接用电脑的局域网 IP 访问。

**步骤（电脑端）**

1. 查电脑的局域网 IP：
   - Windows：`Win+R` → 输入 `cmd` → 执行 `ipconfig` → 找 `无线局域网适配器 WLAN` 下的 `IPv4 地址`，如 `192.168.1.42`
   - macOS：`系统设置 → 网络 → Wi-Fi → 详细信息`，或终端 `ifconfig | grep "inet 192"`
2. 确保防火墙放行：
   - Windows：首次启动 `start.bat` 时会弹防火墙提示，点“允许访问”；若错过，去 `设置 → 防火墙 → 允许应用` 放行 `Python` 与 `Node`
   - macOS：`系统设置 → 网络 → 防火墙` 保持关闭或放行 `node` / `python`
3. 启动服务：`start.bat` / `./start.sh`（保持运行）

**步骤（手机端）**

- 用同一 Wi-Fi，浏览器访问 `http://192.168.1.42:3000`（把 IP 换成你查到的）
- 后端与 Neo4j 同理：`http://192.168.1.42:5001`、`http://192.168.1.42:7474`
- 建议把该地址“添加到主屏幕”，以后像 App 一样点开

**高效技巧**

- 给电脑设固定 IP（路由器后台 → DHCP 静态分配），避免每次 IP 都变
- 手机开“桌面网站”模式，时间线拖拽更顺
- 若手机打不开，先在电脑上 `ping 192.168.1.42` 自测，再检查是否连的 5G 流量而非 Wi-Fi

### 7.2 不在同一 Wi-Fi：内网穿透（frp / ngrok / 花生壳）

**何时用**：你在外面，电脑在家，想远程用。

**最简方案（ngrok，1 条命令）**

1. 电脑安装 ngrok：`https://ngrok.com` 注册→ 下载→ `ngrok config add-authtoken <你的token>`
2. 启动穿透（保持 `start.*` 已运行）：
   ```bash
   ngrok http 3000  # 会给你一个 https://xxxx.ngrok.io  外网地址
   ngrok http 5001  # 后端（如需手机直接调 API）
   ```
3. 手机直接访问那个 `https://xxxx.ngrok.io` 即可（注意：前端默认调 `localhost:5001`，远程时需在前端 `设置→后端地址` 改为你的 ngrok 后端地址，或用 `docs/DEPLOYMENT.md` 的反向代理方案）

**进阶（frp 自建，稳定免费）**

- 在一台有公网 IP 的服务器上部署 `frps`，家中电脑跑 `frpc` 把 `3000/5001` 映射出去，手机访问公网 IP:映射端口。配置见 `frp` 官方文档。

**安全提醒**

- 穿透等于把本机暴露到公网，**务必设强密码**（Neo4j 默认 `neo4j/password` 仅本地用，穿透后请改密码并关闭 `7474` 外网映射）
- 用完即关 `ngrok`/`frpc`，不要长期暴露

### 7.3 终极省心：Tailscale / ZeroTier 组虚拟局域网

- 在电脑和手机都装 Tailscale，登录同一账号，自动组虚拟局域网，手机用 `http://100.x.x.x:3000` 访问，像在家里一样，且自带加密，无需端口映射。适合长期远程。

---

## 8. 如何发现错误（日志在哪、看什么）

### 8.1 先看哪里

| 看什么 | 在哪 | 怎么看 |
|--------|------|--------|
| 后端是否活着 | `http://localhost:5001/api/health` | 浏览器打开，`status: ok` 即活 |
| 前端日志 | 启动终端的前台输出 | 直接看报错栈 |
| 后端日志 | `app/backend/logs/` 或启动终端 | `tail -f app/backend/logs/*.log` |
| Neo4j 日志 | `neo4j/logs/neo4j.log` | `tail -f neo4j/logs/neo4j.log` |
| 冒烟自检 | `scripts/smoke.sh` / `scripts\smoke.bat` | 一键跑完全流程 |

### 8.2 常见报错对照

- **端口占用 `Address already in use :3000/5001/7687`**：`lsof -i :3000`（Mac）或 `netstat -ano | findstr :3000`（Win）查 PID 后 `kill` / `taskkill`
- **`No solution found (neo4j/oasis)`**：已修复为 `requirements.txt` 直装，重跑 `install.*` 即可
- **中文路径导致 Neo4j 崩溃**：`start.bat` 已用 `subst` 虚拟盘符自愈，重启 `start.bat` 即可
- **模型 429 / 超时**：并发已限流为 2，降低 `max_concurrency` 或换更稳的网关
- **时间线任务丢失**：后端重启会丢临时任务，点“重新抽取”即可，数据不丢

---

## 9. 如何提交反馈（让你提的 Issue 一次就被看懂）

> 作者原话：*“俺寻思能用，但实际上能不能用，我甚至无法第一时间在 Windows 上测试。烦请诸君不要苛责，有问题就在 Issues 上提。”* —— 所以，提得越清楚，修得越快。

**去哪提**：`https://github.com/qi-1021/miroworld/issues` 点 `New issue`

**标题格式**：`[模块] 一句话描述`，如 `[时间线] 分叉后主线混入分支事件`

**正文模板（直接复制填）**：

```markdown
**环境**
- 系统：macOS 14 / Windows 11 24H2
- 安装方式：install.sh / install.ps1 / 手动克隆
- 版本：`cat VERSION` 输出
- Node/Python：`node -v` / `python --version`

**复现步骤**
1. ...
2. ...
3. ...

**期望 vs 实际**
- 期望：...
- 实际：...（贴截图）

**日志（关键）**
- 后端：`http://localhost:5001/api/health` 返回
- 终端报错（贴最后 30 行）
- `app/backend/logs/` 相关片段

**可复现的最小数据**（可选）
- 脱敏后的背景/正文片段或快照 `*.miroworld.json`
```

**加分项**：能用 `scripts/smoke.sh` 复现的，直接贴 `smoke` 日志；愿意一起修的，留联系方式。

---

## 10. 数据备份与迁移

- **最稳妥**：世界设定库页→“导出快照”得 `*.miroworld.json`（含时间线、设定库、冲突、人物、模型绑定）
- **物理目录**（随项目走，拷硬盘即走）：
  - `app/backend/data/world/<project_id>/` 设定库
  - `app/backend/data/world-timeline/<project_id>/` 时间线
  - `app/backend/data/world-sim/<project_id>/` 模拟事件
  - `neo4j/data/` 图数据
- **恢复**：新机器 `install.*` 后，在世界设定库页“导入快照”

---

## 11. 常见问题速查

**Q: 能放 U 盘随身带吗？**
A: 能。`neo4j/` 与 `app/backend/data/` 都在项目内，拷走即插即用。

**Q: Windows 11 `stop.bat` 报找不到 `wmic`？**
A: 新版已改 `Get-CimInstance`，无需 `wmic`。

**Q: 长设定抽取质量差？**
A: 按国家/势力分文件、用 Markdown 标题分段；先抽背景再抽正文，手动修线程名。

**Q: 端口想改？**
A: 改 `app/package.json` 与 `app/backend/app/config.py` 对应端口，保持前后端一致。

---

**祝推演顺利！** 有问题按第 9 章提 Issue，带日志的 Issue 优先级最高。
