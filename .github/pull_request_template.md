# Pull Request

## 改动说明
<!-- 一句话概括本 PR 做了什么 -->

## 关联 Issue
<!-- 如 Closes #123 -->

## 自检清单（按 docs/DEVELOPMENT.md）

- [ ] 双端脚本成对修改并实测（`*.sh` ↔ `*.bat/.ps1`）
- [ ] 镜像/容灾分支覆盖新增外网拉取
- [ ] 幂等与自愈验证（重复执行、损坏重建）
- [ ] 中文路径回归（Win 中文用户名）
- [ ] 未引入“替用户做决策”的自动推荐逻辑
- [ ] 四项自检通过：Windows 适配 / 手机适配 / 残余清理 / AI 使用支持

## 测试与构建

- [ ] `PYTHONPATH=app/backend app/backend/.venv/bin/python -m pytest -q` 通过
- [ ] `cd app/frontend && npm run build` 通过
- [ ] `curl localhost:5001/api/health` 正常

## 截图/录屏（可选）

## 补充说明

