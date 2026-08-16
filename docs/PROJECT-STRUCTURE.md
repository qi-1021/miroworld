# 项目结构说明

本文帮助你快速理解 Miroworld 的目录组织。

```
miroworld/
├── README.md                  # 总览与快速开始
├── docs/                      # 文档中心
│   ├── USER-GUIDE.md          # 使用者指南（推荐先读）
│   ├── QUICK-START.md         # 快速部署
│   ├── DEPLOYMENT.md          # 部署/运维
│   ├── CONFIG-REFERENCE.md    # 配置项参考
│   ├── TROUBLESHOOTING.md     # 排障
│   └── ...
├── app/
│   ├── backend/               # Flask 后端
│   │   ├── app/
│   │   │   ├── api/           # HTTP 路由（graph/simulation/report/models/world/timeline/assistant）
│   │   │   ├── models/        # 数据模型（项目、任务、模型配置）
│   │   │   ├── services/      # 业务服务（时间线、世界模拟、图谱、冲突、模型、快照…）
│   │   │   └── utils/         # 通用工具（原子写、LLM 客户端、日志…）
│   │   ├── scripts/           # 后端可执行脚本（含世界模拟子进程）
│   │   ├── tests/             # 后端测试
│   │   ├── data/              # 运行时数据（已 gitignore）
│   │   ├── uploads/           # 项目上传文件（已 gitignore）
│   │   ├── requirements*.txt  # 依赖清单（主环境 / OASIS 隔离环境）
│   │   └── pyproject.toml     # Python 项目配置
│   ├── frontend/              # Vue 3 + Vite 前端
│   │   └── src/
│   │       ├── api/           # 前端 API 封装
│   │       ├── components/    # 组件（时间线、图谱、模型设置…）
│   │       ├── views/         # 页面（Home/WorldSetup/MainView/Simulation…）
│   │       ├── i18n/          # 国际化
│   │       └── router/        # 路由
│   ├── locales/               # 中英文语言包（zh.json / en.json）
│   └── package.json           # 前端/后端统一 npm 脚本
├── scripts/                   # 一键脚本
│   ├── start.sh / start.bat   # 启动
│   ├── stop.sh / stop.bat     # 停止
│   ├── smoke.sh / smoke.bat   # 冒烟
│   ├── setup-env.sh / .bat    # 环境搭建（Graphiti + OASIS 隔离）
│   └── install-neo4j.*        # Neo4j 安装
└── neo4j/                     # Neo4j 数据库（本地）
```

## 关键数据目录（运行时）

| 路径 | 内容 |
|------|------|
| `app/backend/data/world/<project_id>/` | 世界设定库 `bible.json`、向量、冲突报告 |
| `app/backend/data/world-timeline/<project_id>/` | 时间线 `timeline.json`、人物 `characters.json`、线索 `threads.json` |
| `app/backend/data/world-sim/<project_id>/` | 世界模拟状态与事件 |
| `app/backend/data/world-graph/<project_id>/` | 图谱补边缓存 |
| `app/backend/data/task-manager/` | 通用任务持久化 |
| `app/backend/uploads/projects/<project_id>/` | 项目元数据与上传文件 |

## 主要流程

1. 首页选择“世界推演”并上传资料 → 创建项目。
2. 世界设定库保存背景/正文 → 建立分块索引。
3. 可选：冲突检测 → 自定义辩解。
4. 可选：构建世界图谱（Graphiti/Neo4j）→ 补边。
5. 抽取时间线 → 多线程/多维度、分叉、未来、批量编辑。
6. 世界模拟 → 固定分钟或叙事跳跃推演。
7. 内置助手可回答问题并直接执行部分操作。
8. 导出快照备份/迁移。
