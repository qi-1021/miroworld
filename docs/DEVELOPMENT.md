# Miroworld 开发规范（DEVELOPMENT）

> 版本：v1.0 · 2026-08-19 · 基于 `a2b6a67` 之后 40+ 次迭代沉淀
> 适用范围：`Projects/miroworld` 全仓库（`app/backend` / `app/frontend` / `scripts` / `install.*` / `docs`）
> 语言：默认中文回复与中文文档；代码与注释可用中英混合

本规范把“能跑一次”和“能让所有人一直跑通”区分开。任何改动必须同时满足功能正确与双端可交付。

---

## 目录

1. [双端同等支持](#1-双端同等支持-macwin-成对交付)
2. [国内镜像与多源容灾](#2-国内镜像与多源容灾)
3. [依赖自愈与幂等](#3-依赖自愈与幂等)
4. [中文路径兼容](#4-中文路径兼容-subst-虚拟盘符)
5. [不替用户做决策](#5-不替用户做决策)
6. [中文回复与每轮提交推送](#6-中文回复与每轮提交推送)
7. [四项自检清单](#7-四项自检清单)
8. [Git 与测试纪律](#8-git-与测试纪律)
9. [版本与强制更新机制](#9-版本与强制更新机制)
10. [附录](#附录)

---

## 1. 双端同等支持（Mac/Win 成对交付）

**原则**：Mac 与 Windows 同等一等公民。任何面向用户的能力必须双端可用。

**成对清单（改一必改全）：**

| 能力 | Mac | Windows | 说明 |
|------|-----|---------|------|
| 一键安装 | `install.sh` | `install.ps1` | 免 Git 静默下载+解压+启动 |
| 启动 | `start.sh` | `start.bat` | 含环境自检、端口校验、浏览器唤起 |
| 停止 | `stop.sh` | `stop.bat` | 幂等、无残留 |
| 更新 | `update.sh` | `update.bat` | `git fetch + reset --hard` |
| 环境搭建 | `scripts/setup-env.sh` | `scripts/setup-env.bat` | Graphiti 主环境 |
| Neo4j 安装 | `scripts/install-neo4j.sh` | `scripts/install-neo4j.bat` | 含镜像与静默部署 |

**执行要求：**

- 改 `*.sh` 必同步改 `*.bat`/`*.ps1`，反之亦然；PR 中需同时出现两者 diff。
- 路径一律用平台无关写法；涉及 `subst`、`%~dp0`、`$SCRIPT_DIR`、`/` vs `\` 的改动必须双端实测。
- 换行符：`.sh` 保持 LF，`.bat/.ps1` 允许 CRLF；提交前用编辑器确认。
- 报错提示与文档示例必须双端写法，例如 `bash scripts/start.sh` / `start.bat`。

**验收：**

- 在 Mac 与 Win 各跑一次 `install.*` → `start.*` → 打开 `http://localhost:3000` → `stop.*` 全链路通过。

---

## 2. 国内镜像与多源容灾

**原则**：不假设用户有梯子；所有外网依赖必须有国内可达路径。

**覆盖面：**

- PyPI：`requirements.txt` 安装时轮询阿里云/清华/华为/腾讯/中科大 5 源（见 `install.sh:setup python deps` 与 `scripts/setup-env.*`）。
- GitHub：`install.ps1` 通过 `mirror.ghproxy.com` 等加速做 `install.sh` 拉取的容灾。
- 运行环境：OpenJDK 17 / Node 绿色便携版走国内镜像自动下载解压（`scripts/install-neo4j.*`、`start.*` 中相关段）。

**执行要求：**

- 新增任何 `curl`/`wget`/`uv pip install`/`npm install` 外网拉取，必须补国内镜像分支与失败回退。
- 超时与重试要有界（例如 3 次、指数退避），并在失败时给出中文可操作提示。

---

## 3. 依赖自愈与幂等

**原则**：脚本可反复执行，结果收敛；历史脏状态能自动修复。

**已固化实践（不可回退）：**

- 删除 `uv.lock`，改 `requirements.txt` + `uv pip --system` 直装，规避 `neo4j`/`oasis`/`graphiti` 的 `No solution found` 解析冲突。
- 物理删除 `requirements-oasis.txt` 与 `pyproject.toml` 中 `oasis` 声明，OASIS 分支与主启动流程完全解耦。
- `start.*` 最前置阶段无条件检测并删除 `app/backend/.venv-simulation` 损坏残留（如缺 `pip` / `ensurepip` 失败产物）。
- `install.*` / `update.*` / `start.*` 均幂等：已存在则跳过或修复，不抛错中断。

**执行要求：**

- 任何新增依赖，必须写清“缺失时如何自愈、已存在时如何跳过、损坏时如何重建”。
- 禁止引入需要本机 Rust 编译链的依赖；如必须，PR 中需说明替代方案。

---

## 4. 中文路径兼容（subst 虚拟盘符）

**原则**：Windows 中文用户名/路径不得导致 Neo4j/Java 崩溃。

**方案：**

- `start.bat` 启动前扫描并释放旧 `subst` 盘符，创建单一干净虚拟盘符承载 `neo4j`/`app` 路径，退出时自动卸载。
- 涉及 `neo4j`、`Java`、`日志` 的任何路径构造，必须走虚拟盘符或短路径，避免 `Log4j` 对非 ASCII 的解析失败。

**执行要求：**

- 任何涉及文件路径、日志路径、归档路径的改动，必须在“含中文的 Windows 用户名”环境做回归。
- 不得将绝对路径硬编码进配置模板；用变量或相对路径拼装。

---

## 5. 不替用户做决策

**原则**：只做“看得见、比得上、选得快”的工具，不做“替你选最好”的自动化。

**具体约束：**

- 禁止实现“最佳流程/最佳分支自动推荐”。
- 允许并鼓励：筛选、发现、对比、标注、批量操作、差异高亮、时间线分叉预览等辅助决策能力。
- 文案与交互不得暗示系统已替用户选出最优解。

**执行要求：**

- 新功能评审时自问：“这是帮用户看清，还是帮用户拍板？”前者通过，后者打回。

---

## 6. 中文回复与每轮提交推送

**原则**：沟通与交付节奏固定，降低协作成本。

- 默认中文回复；引用代码/日志时保留原文。
- 每轮修复/功能完成后必须 `commit + push`（保持 `origin/main` 可回放）。
- 提交信息用中文或中英混合，首行概括改动，必要时正文列出影响面与验证步骤。

---

## 7. 四项自检清单

每个任务收尾前必检（任一项不满足不得标记完成）：

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | Windows 适配 | `*.sh` 改动已同步 `*.bat/.ps1`，含中文路径回归 |
| 2 | 手机适配 | 关键页面在窄屏（≤ 390px）无溢出与遮挡，触控可达 |
| 3 | 残余清理 | 无遗留 `MiroFish` 文案/旧路径/废弃依赖与临时文件 |
| 4 | AI 使用支持 | 涉及 LLM 的改动走 OpenCode 网关（见 §8 关联），并在 UI/报错中可追溯 |

> 注：本清单源于 `MiroFish → Miro World` 迁移与前端残余清理的教训，已纳入 `75f7590` 等重构的验收条件。

---

## 8. Git 与测试纪律

**Git：**

- 禁止 `git add -A` 误提交他人 WIP；提交前用 `git status --short` 与 `git diff --cached --stat` 复核。
- 大文件/生成物/运行时数据已在 `.gitignore`：`app/backend/data/`、`uploads/`、`.venv*`、`neo4j/`、`logs/` 等不得入库。

**运行与测试：**

- 生产启动：`FLASK_DEBUG=false nohup app/backend/.venv/bin/python app/backend/run.py`（无 reloader）。
- 健康检查：每次后端改动后 `pkill -f run.py; FLASK_DEBUG=false nohup ... &; curl localhost:5001/api/health`。
- 测试：`PYTHONPATH=app/backend app/backend/.venv/bin/python -m pytest -q`；前端改动后 `cd app/frontend && npm run build`。
- 端口：前端 `:3000` / 后端 `:5001` / Neo4j `:7687`；脚本中需做端口占用检测与提示。

**模型与网关（与 §3、§7 联动）：**

- 运行时 LLM 统一走 OpenCode 网关；SiliconFlow 仅用于向量/embedding。
- 新增模型调用需支持从快照/配置解析 `model_id`/`base_url`/`api_key`，不在代码中硬编码密钥。

---

## 9. 版本与强制更新机制

**原则**：版本可追溯、更新可一键、损坏可强制对齐。

- `VERSION` 文件为真值（当前 `6ade6d2` 对应版本），`README` 与脚本中展示一致。
- `update.sh` / `update.bat` 采用 `git fetch + git reset --hard origin/main` 强制对齐，成功后无条件清理 `.venv-simulation` 损坏残留并提示重启 `start.*`。
- `install.sh` / `install.ps1` 同步强化为 `fetch + reset --hard`，并直接调用具备自愈保护的 `start.*`。
- 任何涉及更新流程的改动，必须保证“本地有未提交修改也能一键回到最新可用态”，并在文档中写明数据目录不受影响（`app/backend/data/` 不被重置）。

---

## 附录

### A. 关联文件索引

- 启动/停止/更新：`start.sh` `start.bat` `stop.sh` `stop.bat` `update.sh` `update.bat`
- 安装：`install.sh` `install.ps1`
- 环境：`scripts/setup-env.sh` `scripts/setup-env.bat` `scripts/install-neo4j.sh` `scripts/install-neo4j.bat`
- 后端：`app/backend/app/{api,services,models,utils}/` `app/backend/requirements.txt` `app/backend/pyproject.toml`
- 前端：`app/frontend/src/{views,components,api,i18n,router}/`
- 文档：`README.md` `docs/PROJECT-STRUCTURE.md` `docs/QUICK-START.md` `docs/DEPLOYMENT.md` `docs/TROUBLESHOOTING.md`

### B. 校验清单（PR 自检）

- [ ] 双端脚本成对修改并实测
- [ ] 镜像/容灾分支覆盖新增外网拉取
- [ ] 幂等与自愈路径验证（重复执行、损坏重建）
- [ ] 中文路径回归（Win 中文用户名）
- [ ] 未引入自动推荐决策逻辑
- [ ] 中文回复与 commit+push 已执行
- [ ] 四项自检（Win/手机/残余/AI）通过
- [ ] 测试与构建通过（后端 pytest / 前端 build / /api/health）

### C. 修订记录

- v1.0 2026-08-19：首版，纳入 9 项原则，基于 `a2b6a67 → 6ade6d2` 的 40+ 次迭代沉淀。
