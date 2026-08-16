# Miroworld 命令行工具（CLI）说明

面向 **AI Agent / 自动化** 的纯命令操作工具。所有子命令读操作最快、写操作走真实后端服务管线；
统一 `--json` 输出 `{"success":true|false,...}`，退出码 0=成功、非 0=失败，错误可读。

脚本：`app/backend/scripts/mirofish_cli.py`（纯标准库 + 项目服务；`pathlib`+UTF-8，Windows 可跑）。

> 提示：下文的 `python` 指项目后端解释器；Windows 用 `py` 或你的 venv 路径。后端需已启动
> （`scripts/start.sh` / `scripts/start.bat`），因为 graph/conflict/sim 走真实服务；纯只读
> 命令（models/health/project list）可直接在本机跑。

## 运行方式

bash：
```bash
cd app/backend
PYTHONPATH=. python scripts/mirofish_cli.py models registry --json
```
cmd / PowerShell（Windows）：
```bat
cd app\backend
set PYTHONPATH=.
python scripts\mirofish_cli.py models registry --json
```
PowerShell 用 `$env:PYTHONPATH="."` 代替 `set`。

## 输出契约

- 成功：`{"success": true, "data": <结果>}`
- 失败：`{"success": false, "error": "<可读错误>"}`
- 退出码：0=成功；非 0=失败

---

## 命令一览

### project — 项目
| bash | cmd |
|---|---|
| `CLI project list --json` | `CLI project list --json` |
| `CLI project create --name "我的世界"` | 同左 |
| `CLI project delete --project-id proj_xxx` | 同左 |
| `CLI project export --project-id proj_xxx` | 同左 |
| `CLI project import --file snap.json` | 同左 |

（下文中 `CLI` 统一指代上面的解释器调用前缀。）

### models — 模型注册表（只读）
```bash
CLI models registry --json       # 已验证模型数 + 列表 + 连接数
CLI models list --json           # 完整注册表（含连接）
```

### health — 服务健康
```bash
CLI health --json                # frontend/backend/neo4j 端口探测
CLI health --detailed --json     # 附加模型注册表 verified≥1 检查
```

### world — 世界设定
```bash
CLI world save --project-id proj_xxx --background "背景..." --story "正文..."  # 写
CLI world save --project-id proj_xxx --background-file bg.txt --story-file story.txt
CLI world get   --project-id proj_xxx --json
CLI world settings --project-id proj_xxx --json   # 设定统计 + 图谱状态
```

### timeline — 时间线
```bash
CLI timeline extract --project-id proj_xxx --source bg --wait
CLI timeline get        --project-id proj_xxx --json
CLI timeline threads    --project-id proj_xxx --json
CLI timeline characters --project-id proj_xxx --json
CLI timeline structure  --project-id proj_xxx --json          # 读已保存/LLM 判断
CLI timeline structure-text --text "魏蜀吴三国并行..." --json  # 对一段文本判结构
CLI timeline extract-text --text "次日凯尔希发布命令..." --json # 对文本局部整块抽取
CLI timeline final-report --project-id proj_xxx --action generate --json   # 生成最终时间线报告（小说+梗概）
CLI timeline final-report --project-id proj_xxx --action get --json        # 读取
CLI timeline final-report --project-id proj_xxx --action download --json   # 返回 Markdown
```

### conflict — 冲突
```bash
CLI conflict detect    --project-id proj_xxx                # LLM 检测冲突并保存
CLI conflict list      --project-id proj_xxx --json          # 已保存冲突清单
CLI conflict history   --project-id proj_xxx --json          # 各冲突的多轮辩驳史
CLI conflict corrections --project-id proj_xxx --regenerate --json  # 生成/重算改正补丁
CLI conflict corrections --project-id proj_xxx --read --json        # 只读已生成改正
```

### graph — 世界图谱
```bash
CLI graph status   --project-id proj_xxx --json   # graph_id + 状态 + 节点/边数
CLI graph get      --project-id proj_xxx --json   # 完整图谱节点/边
CLI graph build-world --project-id proj_xxx --wait --json  # 世界图谱构建（背景+正文，断点续建）
CLI graph build    --project-id proj_xxx --wait    # 旧版媒体分析图谱（需项目本体）
```

### sim — 世界模拟
```bash
CLI sim list     --project-id proj_xxx --json
CLI sim history  --project-id proj_xxx --json
CLI sim history  --project-id proj_xxx --favorited-only --json
CLI sim create   --project-id proj_xxx --graph-id mirofish_xxx --json   # 创建模拟
CLI sim prepare  --simulation-id sim_xxx --wait --json                 # 生成智能体人设+配置
CLI sim favorite --simulation-id sim_xxx --value 1 --json   # 标记收藏
CLI sim favorite --simulation-id sim_xxx --value 0 --json   # 取消收藏
CLI sim start    --project-id proj_xxx --steps 6 --time-mode narrative --time-jumps "数日后,三个月后"
```

### assistant — 深度互动
```bash
CLI assistant ask --project-id proj_xxx --question "这个设定合理吗？"
```

---

## AI Agent 从零到最终报告的全命令流水线

适合把"新建世界 → 出小说/梗概"整条链跑通。用真实项目 `proj_xxx` 示例（bash；Windows 把
`\` 换成一行即可）。

```bash
CLI=python app/backend/scripts/mirofish_cli.py   # 或完整 python 路径

# 1) 建项目
$CLI project create --name "测试世界"
# → {"success":true,"data":{"project":{"project_id":"proj_xxxxxxxxxxxx",...}}}
PID=proj_xxxxxxxxxxxx

# 2) 提交背景与正文
$CLI world save --project-id $PID --background "罗德岛移动城邦…" --story "阿米娅自幼…"

# 3) 抽取时间线（背景与正文；--wait 阻塞到完成）
$CLI timeline extract --project-id $PID --source bg --wait
$CLI timeline extract --project-id $PID --source story --wait

# 4) 构建世界图谱（可断点续建，--wait）
$CLI graph build-world --project-id $PID --wait

# 5) 冲突检测（LLM）并生成外挂改正补丁
$CLI conflict detect --project-id $PID
$CLI conflict corrections --project-id $PID --regenerate

# 6) 创建世界模拟并准备智能体人设
GID=$($CLI graph status --project-id $PID --json | grep -o 'mirofish_[a-f0-9]*' | head -1)
SIM_ID=$($CLI sim create --project-id $PID --graph-id $GID --json | grep -o 'sim_[a-f0-9]*' | head -1)
$CLI sim prepare --simulation-id $SIM_ID --wait

# 7) 生成最终时间线报告（小说 + 梗概）
$CLI timeline final-report --project-id $PID --action generate
$CLI timeline final-report --project-id $PID --action download > final.md

# 8) 收藏"最喜欢的流向"
$CLI sim history --project-id $PID --json
$CLI sim favorite --simulation-id $SIM_ID --value 1
```

> 说明：
> - 步骤 4/5 会触发真实 LLM/建图，耗时较长，用 `--wait` 阻塞或后台轮询（不传 `--wait`
>   返回 `task_id`，再 `graph status` 轮询）。
> - `sim prepare --wait` 会等智能体人设生成完毕；不传 `--wait` 则返回 `task_id` 后异步跑。

## 常见错误排查

- `"成功":false, "error":"项目不存在"` → `project_id` 拼错。
- `graph build-world` 报「尚未提交世界输入」 → 先 `world save` 提交背景/正文。
- 后端未启动 → 先 `scripts/start.sh`（或 start.bat）。
- Windows 中文乱码 → 终端用 UTF-8；脚本内部已强制 UTF-8。
