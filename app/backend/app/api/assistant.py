"""内置项目助手 API。

助手读取当前项目上下文（项目状态、设定库、时间线、人物、冲突、图谱），
用项目绑定的 LLM 回答“哪里不对劲、应该去哪个栏目改、下一步做什么”。

端点：
- POST /api/assistant/ask   body: { project_id, question }
"""

from flask import jsonify, request

from . import assistant_bp
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger("mirofish.assistant")


def _build_llm_client_for_project(project_id: str) -> LLMClient:
    """优先项目绑定模型，其次注册表第一个已验证 chat，最后回退默认。"""
    try:
        from ..services.model_registry import ModelRegistryService
        from ..services.model_resolver import ModelResolver
        from ..models.model_config import ModelRole

        registry = ModelRegistryService()
        bindings = registry.get_project_bindings(project_id)
        if bindings and bindings.to_dict().get(ModelRole.PRIMARY.value):
            snapshot = registry.create_snapshot(
                owner_type="project",
                owner_id=project_id,
                bindings=bindings,
                expected_revision=None,
            )
            resolved = ModelResolver(registry).resolve_chat(ModelRole.PRIMARY, snapshot["id"])
            return LLMClient(
                api_key=resolved.api_key,
                base_url=resolved.endpoint,
                model=resolved.model_id,
            )
    except Exception as e:
        logger.warning(f"项目绑定模型解析失败，尝试回退: {e}")

    try:
        from ..services.zep_graphiti_impl import GraphitiClient
        resolved = GraphitiClient._resolve_registry_chat_model()
        if resolved:
            api_key, base_url, model = resolved
            return LLMClient(api_key=api_key, base_url=base_url, model=model)
    except Exception as e:
        logger.warning(f"注册表模型回退失败: {e}")
    return LLMClient()


def _build_project_context(project_id: str) -> str:
    """汇总项目当前状态，供助手参考。"""
    from ..models.project import ProjectManager
    from ..services import timeline_service
    from ..services.world_bible import WorldBibleService
    from ..services.conflict_detector import load_conflict_report

    lines = []
    project = ProjectManager.get_project(project_id)
    if project is None:
        return "项目不存在。"

    lines.append(f"项目：{project.name}（{project.project_id}）")
    lines.append(f"状态：{project.status.value if hasattr(project.status, 'value') else project.status}")
    lines.append(f"本体实体类型：{len((project.ontology or {}).get('entity_types', []))}，关系类型：{len((project.ontology or {}).get('edge_types', []))}")
    lines.append(f"图谱 graph_id：{project.graph_id or '未构建'}")

    bible = WorldBibleService.get_bible(project_id)
    if bible is not None:
        lines.append(f"设定库：背景 {len(bible.background_text)} 字 / 正文 {len(bible.story_text)} 字，分块 {len(bible.chunks)}")
    else:
        lines.append("设定库：无")

    timeline = timeline_service.load_timeline(project_id, None)
    events = timeline.get("events", [])
    threads = sorted({e.get("thread_name") or e.get("thread_id") for e in events if e.get("thread_name") or e.get("thread_id")})
    dims = sorted({e.get("dimension") for e in events if e.get("dimension") and e.get("dimension") != "main"})
    lines.append(f"时间线事件：{len(events)}；线程：{threads or '无'}；非主线维度：{dims or '无'}")

    chars = timeline_service.load_characters(project_id)
    lines.append(f"人物档案：{len(chars)} 人" + (f"，含别名 {sum(len(c.get('aliases') or []) for c in chars)} 个" if chars else ""))

    report = load_conflict_report(project_id)
    if report is not None:
        statuses = {}
        for c in report.conflicts:
            statuses[c.status] = statuses.get(c.status, 0) + 1
        lines.append(f"冲突报告：{len(report.conflicts)} 条，状态 {statuses}")
    else:
        lines.append("冲突报告：无")

    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "你是 MiroFish 的内置项目助手。你非常了解这个工具的功能分区："
    "「世界设定库」负责输入背景/正文、冲突检测、图谱、时间线、模拟；"
    "「时间线」负责抽取/修正/分叉/批量编辑；「模型设置」负责模型接入与向量；"
    "「图谱」负责本体与 Graphiti/Neo4j 建图。"
    "用户会给你当前项目上下文和一个问题。请判断问题属于哪个栏目、应该修改哪个具体对象，"
    "并给出可操作步骤。若信息不足，明确说明还需要什么。回答用中文，简洁、分点，不超过 400 字。"
)


@assistant_bp.route("/ask", methods=["POST"])
def ask():
    """根据项目上下文回答用户问题。"""
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get("project_id") or "").strip()
        question = str(data.get("question") or "").strip()
        if not project_id:
            return jsonify({"success": False, "error": "缺少 project_id"}), 400
        if not question:
            return jsonify({"success": False, "error": "缺少 question"}), 400

        context = _build_project_context(project_id)
        if context == "项目不存在。":
            return jsonify({"success": False, "error": "项目不存在"}), 404

        llm = _build_llm_client_for_project(project_id)
        user = f"项目上下文：\n{context}\n\n用户问题：{question}"
        answer = llm.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        return jsonify({"success": True, "data": {"answer": answer, "context": context}})
    except Exception as e:
        logger.error(f"项目助手调用失败: {e}")
        return jsonify({"success": False, "error": f"助手调用失败: {e}"}), 500
