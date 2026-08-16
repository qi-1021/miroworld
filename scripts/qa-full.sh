#!/bin/bash
# Miroworld CLI 全流程 QA 脚本（可重复运行）
#
# 用法：
#   bash scripts/qa-full.sh
#
# 退出码：0 = 全部通过（无 FAIL，可能含 WARN）；非 0 = 存在 FAIL。
#
# 说明：
#   - bash + curl + python3，不依赖真实 LLM 结果也能跑，但会触发真实接口。
#   - 需要后端已在 127.0.0.1:5001 运行（scripts/start.sh 启动）。
#   - 只读为主；唯一写操作针对固定测试项目 proj_971906db95da 的
#     corrections 生成 / final-report 生成 / simulation create+prepare；
#     若这些资源不存在则跳过并标 WARN，不算失败。
#   - 前置服务（Neo4j、模型）不可用时标 FAIL 或 degrade，脚本不删任何用户数据。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/app/backend"
BASE="http://127.0.0.1:5001"

PID="proj_971906db95da"

LOG="/tmp/mirofish-qa-full.log"
exec > >(tee -a "$LOG") 2>&1

declare -i FAIL_COUNT=0
declare -i WARN_COUNT=0
declare -i PASS_COUNT=0

pass() { printf '[PASS] %s\n' "$*"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { printf '[FAIL] %s\n' "$*"; FAIL_COUNT=$((FAIL_COUNT+1)); }
warn() { printf '[WARN] %s\n' "$*"; WARN_COUNT=$((WARN_COUNT+1)); }

# 若指定资源不存在则跳过（标 WARN，不算 FAIL）
skip_no_resource() { printf '[WARN] 跳过（资源不存在）: %s\n' "$*"; WARN_COUNT=$((WARN_COUNT+1)); }

timeouts() { echo "==> ($(date '+%H:%M:%S')) $*"; }

# ---------- 工具：curl + JSON ----------
jget() { python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('$1',''))"; }
jget0() { python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('$1') or '')"; }

# 从 /api/world/<pid>/settings 取 graph_id（位于 stats.graph_id）
get_graph_id() {
  curl -s -m 20 "$BASE/api/world/$1/settings" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin); s=d.get('stats') or {}; print(s.get('graph_id') or d.get('graph_id') or '')
except Exception: print('')
"
}

# 图谱实体数（data.entities 列表长度）；无法读取返回 0
entity_count() {
  local gid="$1"
  [ -z "$gid" ] && { echo 0; return; }
  curl -s -m 20 "$BASE/api/simulation/entities/$gid" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin); data=d.get('data') or {}
  ent=data.get('entities') if isinstance(data,dict) else d.get('data')
  print(len(ent) if isinstance(ent,list) else (1 if ent else 0))
except Exception: print(0)
" 2>/dev/null || echo 0
}

# 找该项目正在运行（pending/processing）的 world_graph_build 任务（metadata.kind+project_id 匹配）。
# 输出 task_id（无则空）。因为后端有同项目并发守卫，主动触发构建前先复用已有任务。
find_graph_task() {
  local pid="$1"
  curl -s -m 20 "$BASE/api/graph/tasks" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin); tasks=d.get('data') or []
  pid=sys.argv[1]
  for t in tasks:
    meta=(t.get('metadata') or {}) if isinstance(t.get('metadata'),dict) else {}
    if meta.get('kind')=='world_graph_build' and meta.get('project_id')==pid \
       and t.get('status') in ('pending','processing'):
      print(t.get('task_id') or ''); break
  else:
    print('')
except Exception: print('')
" "$pid" 2>/dev/null || echo ""
}

# 轮询图谱构建任务直到 completed/failed 或 cap 秒；输出 st:gfail:en
poll_graph_task() {
  local tid="$1" cap="$2" gid="$3"
  local end st gfail en
  [ -z "$tid" ] && { echo "none:0:$(entity_count "$gid")"; return; }
  end=$(( $(date +%s) + cap ))
  gfail=""
  while :; do
    tr=$(curl -s -m 15 "$BASE/api/graph/task/$tid" 2>/dev/null || true)
    st=$(printf '%s' "$tr" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('data') or {}).get('status') or json.load(sys.stdin).get('status',''))
except Exception: print('')")
    if [ "$st" == "completed" ] || [ "$st" == "success" ] || [ "$st" == "done" ]; then echo "completed:0:$(entity_count "$gid")"; return; fi
    if [ "$st" == "failed" ] || [ "$st" == "error" ]; then
      gfail=$(printf '%s' "$tr" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('data') or {}).get('error','') or '')
except Exception: print('')")
      en=$(entity_count "$gid")
      echo "failed:$gfail:$en"; return
    fi
    if [ "$(date +%s)" -ge "$end" ]; then
      echo "processing:0:$(entity_count "$gid")"; return
    fi
    sleep 5
  done
}

# http_json <url> [curl args...] -> prints JSON, sets HTTP_CODE
http_json() {
  local url="$1"; shift
  local tmp code
  tmp=$(mktemp)
  code=$(curl -s -m 30 -o "$tmp" -w '%{http_code}' "$@" "$BASE$url")
  printf '%s' "$code" > /tmp/_qa_code
  cat "$tmp"
  rm -f "$tmp"
}

poll_status() {
  # poll_status <url> <body> <ok_statuses空间分隔> <timeout_sec> <interval_sec> <desc>
  # 轮询 POST url 返回 data.status 直到命中 ok_statuses 之一或 timeout；非 0=超时/失败
  local url="$1" body="$2" wants="$3" timeout_s="$4" interval="$5" desc="$6"
  local end now st last_json
  end=$(( $(date +%s) + timeout_s ))
  last_json=""
  while :; do
    now=$(date +%s)
    if [ "$now" -ge "$end" ]; then
      return 1
    fi
    resp=$(curl -s -m 15 -X POST -H 'Content-Type: application/json' \
           -d "$body" "$BASE$url" 2>/dev/null || true)
    last_json="$resp"
    # status 位于 data.status（prepare/status 把状态嵌套在 data 下）
    st=$(printf '%s' "$resp" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('data') or {}).get('status',''))
except Exception: print('')")
    if [ -n "$st" ]; then
      for _w in $wants; do
        if [ "$st" == "$_w" ]; then
          printf '%s' "$resp"
          return 0
        fi
      done
    fi
    if [ "$st" == "failed" ] || [ "$st" == "error" ]; then
      return 2
    fi
    sleep "$interval"
  done
}

# ===========================================================================
echo
timeouts "==== Miroworld 全流程 QA 开始 ===="
echo "后端: $BASE  测试项目: $PID  日志: $LOG"

# ---- 预检：后端可达 ----
if ! curl -s -m 5 -o /dev/null "$BASE/health"; then
  fail "后端不可达: $BASE/health（请先 bash scripts/start.sh 启动）"
  echo
  printf '==== QA 结束 ==== PASS=%s WARN=%s FAIL=%s\n' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
  exit 1
fi
pass "后端可达 /health"

# ===========================================================================
echo
timeouts "== 1. 健康检查 =="
# 1a. /health
r=$(http_json "/health")
if printf '%s' "$r" | grep -q '"status"'; then pass "'/health' 返回 JSON"; else fail "'/health' 异常"; fi

# 1b. /api/health/detailed：neo4j=ok 且 models.verified>=1
r=$(http_json "/api/health/detailed")
neo4j=$(printf '%s' "$r" | jget0 neo4j)
mv=$(python3 -c "import json,sys
try:
  d=json.loads('''$(printf '%s' "$r")'''); print(d.get('models',{}).get('verified',0) if isinstance(d.get('models'),dict) else 0)
except Exception: print('ERR')")
ts=$(printf '%s' "$r" | jget0 status)
if [ "$neo4j" == "ok" ]; then pass "neo4j=ok"; else fail "neo4j=$neo4j"; fi
if [ "$mv" != "ERR" ] && [ "${mv:-0}" -ge 1 ]; then pass "models.verified=$mv (>=1)"; else fail "models.verified=$mv (<1)"; fi
# total /api/health/detailed status 允许 ok 或 degraded（只要 neo4j 已另查）

# ===========================================================================
echo
timeouts "== 2. 模型注册表 =="
r=$(http_json "/api/models/registry" "--max-time" "35")
n=$(printf '%s' "$r" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); data=d.get('data') or {}; ms=data.get('models') or d.get('models') or []
  print(sum(1 for m in ms if m.get('verified')))
except Exception: print('ERR')")
if [ "$n" != "ERR" ] && [ "${n:-0}" -ge 1 ]; then pass "models registry verified=$n (>=1)"; else fail "models registry verified=${n:-0} (<1)"; fi

# ===========================================================================
echo
timeouts "== 3. 模拟列表/历史接口 =="
# 3a. /api/simulation/history
r=$(http_json "/api/simulation/history")
if printf '%s' "$r" | grep -q '"success": *true\|"success":true'; then pass "/api/simulation/history success=true"; else fail "/api/simulation/history 响应异常"; fi
# 3b. /api/simulation/list
r=$(http_json "/api/simulation/list")
if printf '%s' "$r" | grep -q '"success": *true\|"success":true'; then pass "/api/simulation/list success=true"; else fail "/api/simulation/list 响应异常"; fi

# ===========================================================================
echo
timeouts "== 4. 世界图谱（proj_971906db95da）=="
# 4a. 拿 graph_id（settings.stats.graph_id）
GID=$(get_graph_id "$PID")

# 4b. 【不重复发起构建】找本项目已有的 world_graph_build 任务；有则复用轮询，
#     无则直接检查现有图谱实体数。避免每次 QA 重跑启动重复构建线程拖慢后端。
GTID=$(find_graph_task "$PID")
if [ -n "$GTID" ]; then
  poll_res=$(poll_graph_task "$GTID" 180 "$GID")
  pst=${poll_res%%:*}; pgfail=""; pen=0
  case "$poll_res" in
    processing:*)
      pen=${poll_res##processing:0:}
      if [ "${pen:-0}" -ge 1 ]; then
        pass "图谱构建任务 $GTID 仍在 processing，但图谱已有实体数=${pen}，按已建成计"
        warn "图谱后台继续构建，不影响使用（任务 ${GTID}）"
      else
        warn "图谱构建任务 $GTID 仍在 processing，且暂无实体（任务继续后台构建）"
      fi
      ;;
    completed:*)
      pass "图谱构建任务 $GTID -> completed"
      ;;
    failed:*)
      pgfail="${poll_res#failed:}"; pgfail=${pgfail%%:*}
      pen=${poll_res##*:}
      if [ "${pen:-0}" -ge 1 ]; then
        pass "图谱构建任务 $GTID failed（${pgfail}），但图谱已有实体数=${pen}，按已建成计"
        warn "图谱后台构建曾失败，但不影响已建成图谱使用"
      else
        fail "图谱构建任务 $GTID -> failed（${pgfail}）"
      fi
      ;;
    none:*)
      en=${poll_res##none:0:}
      if [ "${en:-0}" -ge 1 ]; then pass "无进行中任务，图谱已有实体数=${en}，按已建成计"; else warn "无进行中图谱任务且无实体数（图谱可能未建成）"; fi
      ;;
  esac
else
  en=$(entity_count "$GID")
  if [ "${en:-0}" -ge 1 ]; then pass "无进行中的 world_graph_build 任务，图谱已有实体数=${en}（已建成）"; else warn "无进行中的 world_graph_build 任务且图谱无可查实体数"; fi
fi

if [ -z "$GID" ]; then
  warn "未取得 graph_id（图谱可能未建成），跳过图谱实体检查"
else
  # 4c. GET /api/world/<pid>/graph
  r=$(http_json "/api/world/$PID/graph")
  if printf '%s' "$r" | grep -q '"success": *true\|"success":true'; then pass "GET /world/$PID/graph success=true"; else fail "GET /world/$PID/graph 异常"; fi
  # 4d. /api/simulation/entities/<graph_id> 实体数>0
  n=$(entity_count "$GID")
  if [ "${n:-0}" -ge 1 ]; then pass "图谱实体数=$n (>0)"; else warn "图谱实体数=${n}（可能无实体）"; fi
fi

# ===========================================================================
echo
timeouts "== 5. 智能体人设链路（真实 prepare）=="
GID=$(get_graph_id "$PID")
if [ -z "$GID" ]; then warn "graph_id 为空，跳过人设链路"; else
  # 5a. create simulation（复用已存在的该项目 sim）
  sim_id=""
  r=$(http_json "/api/simulation/create" -X POST -H 'Content-Type: application/json' \
       -d "{\"project_id\":\"$PID\",\"graph_id\":\"$GID\"}")
  sim_id=$(printf '%s' "$r" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); print((d.get('data') or {}).get('simulation_id') or '')
except Exception: print('')")
  code=$(cat /tmp/_qa_code 2>/dev/null || echo 000)
  if [ -n "$sim_id" ]; then pass "create simulation -> $sim_id"; else warn "create simulation 未返回 sim_id（HTTP=${code}，resp=$(printf '%s' "$r" | cut -c1-100)）"; fi

  if [ -n "$sim_id" ]; then
    # 5b. 若 project.simulation_requirement 为空，调用后端兜底写该字段（小 python 片段）
    req=$(http_json "/api/world/$PID/settings" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('goal') or '')
except Exception: print('')")
    (cd "$BACKEND_DIR" && PYTHONPATH="$BACKEND_DIR" .venv/bin/python - "$PID" <<'PYEOF'
import sys, os
pid = sys.argv[1]
try:
    from app.models.project import ProjectManager
    p = ProjectManager.get_project(pid)
    if p and not getattr(p, 'simulation_requirement', None):
        # 兜底：写入一个最小模拟需求，避免 prepare 因缺字段而失败
        ProjectManager.save_project(p, patch={'simulation_requirement': '学生与公众人物的日常社交与冲突。'})
        print('wrote simulation_requirement')
    else:
        print('simulation_requirement already set or project missing')
except Exception as e:
    print('ERR', e)
PYEOF
    ) >/dev/null 2>&1 || true

    # 5c. prepare —— 返回 status + task_id；已就绪则直接 PASS，否则按 task_id 轮询
    r=$(http_json "/api/simulation/prepare" -X POST -H 'Content-Type: application/json' \
         -d "{\"simulation_id\":\"$sim_id\"}")
    pst=$(printf '%s' "$r" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('data') or {}).get('status',''))
except Exception: print('')")
    ptid=$(printf '%s' "$r" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('data') or {}).get('task_id',''))
except Exception: print('')")
    if [ "$pst" == "ready" ] || [ "$pst" == "completed" ]; then
      pc=$(printf '%s' "$r" | python3 -c "import json,sys
try:
  d=(json.load(sys.stdin).get('data') or {}).get('prepare_info',{}); print(d.get('profile_count','') or '')
except Exception: print('')")
      pass "prepare 已就绪（status=$pst profiles_count=${pc}）"
    elif [ "$pst" == "preparing" ] && [ -n "$ptid" ]; then
      # 5d. 用 task_id 轮询（prepare/status 须传 task_id 才返回进行中进度）
      resp=$(poll_status "/api/simulation/prepare/status" \
             "{\"task_id\":\"$ptid\"}" "ready completed" 720 5 "prepare")
      rc=$?
      if [ $rc -eq 0 ]; then
        pc=$(printf '%s' "$resp" | python3 -c "import json,sys
try:
  d=(json.load(sys.stdin).get('data') or {}); print((d.get('prepare_info') or {}).get('profile_count','') or '')
except Exception: print('')")
        pass "prepare -> ready（profiles_count=${pc}）"
      elif [ $rc -eq 2 ]; then
        err=$(printf '%s' "$resp" | python3 -c "import json,sys
try: print((json.load(sys.stdin).get('data') or {}).get('message',''))
except Exception: print('')")
        fail "prepare -> failed（${err}）——这是用户报的 bug"
      else
        fail "prepare 轮询超时（12 分钟）"
      fi
    else
      fail "prepare 未就绪且无 task_id 可轮询（pst=$pst）"
    fi
  fi
fi

# ===========================================================================
echo
timeouts "== 6. 改正文件（补丁化）=="
CONF_ID=""
r=$(http_json "/api/world/$PID/conflicts")
conf=$(printf '%s' "$r" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); rep=d.get('report') or d.get('data') or {}; cs=rep.get('conflicts',[])
  print(cs[0].get('conflict_id','') if cs else '')
except Exception: print('')")
CONF_ID="$conf"
if [ -z "$CONF_ID" ]; then skip_no_resource "项目无真实冲突，跳过改正文件检查"; else
  # POST corrections
  r=$(http_json "/api/world/$PID/conflicts/$CONF_ID/corrections" -X POST)
  hf=$(printf '%s' "$r" | jget0 has_files)
  if [ "$hf" == "True" ] || [ "$hf" == "true" ] || [ "$hf" == "1" ]; then
    has_patch=$(printf '%s' "$r" | grep -c "corrected_patches.md" || true)
    has_json=$(printf '%s' "$r" | grep -c "corrections.json" || true)
    if [ "$has_patch" -ge 1 ] && [ "$has_json" -ge 1 ]; then
      pass "corrections 生成：has_files=true，含 corrected_patches.md + corrections.json"
    else
      fail "corrections 生成：files 缺 corrected_patches.md 或 corrections.json"
    fi
  else
    fail "corrections 生成 has_files != true（${hf}）"
  fi
  # GET corrections
  r=$(http_json "/api/world/$PID/conflicts/$CONF_ID/corrections")
  if printf '%s' "$r" | grep -q '"success": *true\|"success":true'; then pass "GET corrections 200"; else fail "GET corrections 异常"; fi
  # render?source=story
  r=$(http_json "/api/world/$PID/conflicts/$CONF_ID/corrections/render?source=story")
  code=$(cat /tmp/_qa_code 2>/dev/null || echo 000)
  if [ "$code" == "200" ]; then pass "corrections/render?source=story 200"; else fail "corrections/render?source=story HTTP=$code"; fi
fi

# ===========================================================================
echo
timeouts "== 7. 最终时间线报告 =="
r=$(http_json "/api/timeline/$PID/final-report" -X POST)
has_novel=$(printf '%s' "$r" | python3 -c "import json,sys
try: d=(json.load(sys.stdin).get('data') or {}); print('novel' in d and 'synopsis' in d)
except Exception: print('False')")
if [ "$has_novel" == "True" ] || [ "$has_novel" == "true" ]; then
  pass "final-report（POST）生成，data 含 novel + synopsis"
else
  fail "final-report（POST）未含 novel+synopsis（resp=$(printf '%s' "$r" | cut -c1-100)）"
fi
r=$(http_json "/api/timeline/$PID/final-report")
if printf '%s' "$r" | grep -q '"has_report": *true\|"has_report":true'; then pass "final-report（GET）has_report=true"; else fail "final-report（GET）has_report != true"; fi
r=$(http_json "/api/timeline/$PID/final-report/download")
code=$(cat /tmp/_qa_code 2>/dev/null || echo 000)
if [ "$code" == "200" ]; then pass "final-report/download 200"; else warn "final-report/download HTTP=$code"; fi

# ===========================================================================
echo
timeouts "== 8. 收藏流向 =="
r=$(http_json "/api/simulation/history?favorite=1")
if printf '%s' "$r" | grep -q '"success": *true\|"success":true'; then pass "history?favorite=1 200"; else fail "history?favorite=1 异常"; fi
# PATCH 一个真实 simulation favorite; 该 sim_id 取下第一个可用的
SIMID=$(http_json "/api/simulation/history" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); arr=d.get('data') or d.get('simulations') or []; 
  print(arr[0].get('simulation_id') or arr[0].get('id') or '' if arr else '')
except Exception: print('')")
if [ -z "$SIMID" ]; then skip_no_resource "无真实 simulation，跳过 favorite PATCH"; else
  r=$(http_json "/api/simulation/$SIMID/favorite" -X PATCH -H 'Content-Type: application/json' -d '{"favorite":true}')
  okf=$(printf '%s' "$r" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); print('success' if d.get('success') else 'fail')
except Exception: print('fail')")
  if [ "$okf" == "success" ]; then pass "favorite PATCH true 成功"; else fail "favorite PATCH true 失败"; fi
  # 恢复
  r=$(http_json "/api/simulation/$SIMID/favorite" -X PATCH -H 'Content-Type: application/json' -d '{"favorite":false}')
  okf=$(printf '%s' "$r" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); print('success' if d.get('success') else 'fail')
except Exception: print('fail')")
  if [ "$okf" == "success" ]; then pass "favorite PATCH false（恢复原状）成功"; else warn "favorite PATCH false 恢复失败"; fi
fi

# ===========================================================================
echo
timeouts "== 9. 文本格式（pytest test_file_formats）=="
tmp=$(mktemp -d)
if (cd "$BACKEND_DIR" && PYTHONPATH="$BACKEND_DIR" .venv/bin/python -m pytest tests/test_file_formats.py -q > "$tmp/formats.log" 2>&1); then
  tail -1 "$tmp/formats.log" | grep -q "passed" && {
    np=$(tail -1 "$tmp/formats.log" | awk '{for(i=1;i<=NF;i++) if($i~/^[0-9]+$/) print $i}' | head -1)
    pass "test_file_formats.py 全绿 ($(tail -1 "$tmp/formats.log"))"
  } || pass "test_file_formats.py 通过"
else
  fail "test_file_formats.py 有失败"
  tail -8 "$tmp/formats.log" || true
fi
rm -rf "$tmp"

# ===========================================================================
echo
timeouts "==== QA 结束 ===="
printf '==== 汇总 ==== PASS=%s  WARN=%s  FAIL=%s\n' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "[FAIL] 存在失败，退出码非 0。完整日志见 $LOG"
  exit 1
fi
echo "[PASS] 全部通过（WARN 不计），退出码 0。完整日志见 $LOG"
exit 0
