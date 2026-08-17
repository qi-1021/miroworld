"""
本体生成服务
接口1：分析文本内容，生成适合社会模拟的实体和关系类型定义
"""

import json
import os
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient


def generate_ontology_with_cache(
    generator: "OntologyGenerator",
    document_texts: List[str],
    simulation_requirement: str,
    additional_context: Optional[str] = None,
    cache_key_parts: tuple = (),
) -> Dict[str, Any]:
    """
    在本体生成前先查磁盘缓存；命中直接返回封装后的本体，未命中调用
    generator.generate 并把结果写回缓存。任何缓存读写异常都静默降级
    （仅 warning），绝不影响本体生成的正常路径。

    缓存键 = sha256(cache_key_parts)，通常为 (输入文本, goal, model_id)。
    """
    try:
        from ..utils.logger import get_logger
        from .cache_utils import cache_root, compute_cache_key, read_cache, write_cache
        logger = get_logger('mirofish.api')
        # 缓存根目录可从环境变量覆盖（测试隔离）；默认 data/ontology_cache
        override = os.environ.get('MIROFISH_ONTOLOGY_CACHE_DIR')
        ontology_cache_dir = override or os.path.join(cache_root(), 'ontology_cache')
        hash_key = compute_cache_key(list(cache_key_parts))
    except Exception:
        hash_key = None

    if hash_key:
        try:
            from .cache_utils import read_cache
            cached = read_cache(ontology_cache_dir, hash_key)
            if cached is not None:
                get_logger('mirofish.api').info(
                    f"本体缓存命中（key={hash_key[:12]}…），跳过 LLM 调用"
                )
                return cached
        except Exception:
            pass

    ontology = generator.generate(
        document_texts=document_texts,
        simulation_requirement=simulation_requirement,
        additional_context=additional_context,
    )

    if hash_key:
        try:
            from .cache_utils import write_cache
            write_cache(ontology_cache_dir, hash_key, ontology)
        except Exception:
            pass
    return ontology


# 本体生成的系统提示词
ONTOLOGY_SYSTEM_PROMPT = """你是一个专业的知识图谱本体设计专家。你的任务是分析给定的文本内容，为**小说世界/虚构世界推演**设计知识图谱的实体类型和关系类型。

**重要：你必须输出有效的JSON格式数据，不要输出任何其他内容。**

## 核心任务背景

我们正在为一部小说、故事或虚构世界构建知识图谱，用于世界推演和角色模拟。图谱需要捕捉：
- 世界中存在的**人物与角色**（主角、配角、对立势力等）
- **组织与势力**（帝国、宗门、公会、种族、国家、阵营等）
- **地理与场所**（城市、地域、国家、神域、异界等）
- **物品与器物**（法宝、神器、道具、技术装置等）
- **法则与概念**（修炼体系、魔法体系、制度规则、核心思想等）
- 以及实体之间的**关联与因果关系**

## 输出格式

请输出JSON格式，包含以下结构：

```json
{
    "entity_types": [
        {
            "name": "实体类型名称（使用文档主要语言命名：中文文档用中文，如 人物、宗门；英文文档用英文）",
            "description": "简短描述（不超过100字符）",
            "attributes": [
                {
                    "name": "属性名（英文，snake_case）",
                    "type": "text",
                    "description": "属性描述"
                }
            ],
            "examples": ["示例实体1", "示例实体2"]
        }
    ],
    "edge_types": [
        {
            "name": "关系类型名称（使用文档主要语言命名，如 隶属于、位于、持有、对立于）",
            "description": "简短描述（不超过100字符）",
            "source_targets": [
                {"source": "源实体类型", "target": "目标实体类型"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "对文本内容的简要分析说明（中文）"
}
```

## 设计指南（极其重要！）

### 1. 实体类型设计

**数量要求：必须正好10个实体类型**

**语言要求：所有类型名称和描述必须使用文档的主要语言**（中文文档用中文，英文文档用英文）。

**层次结构要求**：

你的10个实体类型必须包含以下层次：

A. **兜底类型（必须包含，放在列表最后2个）**：
   - `人物`（或 `个人`）：任何人类/类人角色（如主角、配角、个人个体）的兜底 entity_type，不属于更具体角色类型时归入此类
   - `势力`（或 `组织`）：任何组织、集团、公会、阵营的兜底 entity_type，不属于更具体组织类型时归入此类

B. **具体类型（8个，根据文本内容设计）**，优先从以下维度选取：
   - **角色/个人维度**（文本有具体个人与角色时）：如 `主角`、`反派`、`盟友`、`君主`、`修士`、`武者` 等
   - **组织维度**（文本有组织与势力集团时）：如 `宗门`、`帝国`、`王国`、`公会`、`种族` 等
   - **地理维度**（文本有地理描述时）：如 `城市`、`秘境`、`大陆`、`神域` 等
   - **物品维度**（文本有重要器物时）：如 `法宝`、`神器`、`道具`、`典籍` 等
   - **概念维度**（文本有核心规则时）：如 `功法`、`境界`、`法则`、`制度` 等

**设计原则**：
- 类型必须对应文本中**真实出现**的重要元素
- 每个类型有明确的边界，避免重叠
- 优先选择覆盖面广、文中高频出现的类别

### 2. 关系类型设计

数量：6-10个，优先设计以下关系：
- **从属/归属**：如 效忠于、隶属于、出身于
- **对立/同盟**：如 对立于、同盟于、敌对
- **持有/掌控**：如 持有、掌控、统治
- **位于/管辖**：如 位于、管辖
- **衍生/传承**：如 师承、传授、继承
- **因果/影响**：如 影响、引发、依赖

### 3. 属性设计

- 每个实体类型1-3个关键属性
- **禁止使用系统保留字**：`name`、`uuid`、`group_id`、`created_at`、`summary`、`entity_type`、`fact`、`fact_type`、`valid_at`、`invalid_at`、`attributes`
- 推荐：`title`、`role`、`realm`（境界）、`affiliation`（归属势力）、`location`、`description`、`power_level`（属性名保持英文 snake_case）
"""


class OntologyGenerator:
    """
    本体生成器
    分析文本内容，生成实体和关系类型定义
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成本体定义

        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模拟需求描述
            additional_context: 额外上下文

        Returns:
            本体定义（entity_types, edge_types等）
        """
        # 构建用户消息
        user_message = self._build_user_message(
            document_texts,
            simulation_requirement,
            additional_context
        )

        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

        # 调用LLM
        import time as _time
        _t0 = _time.time()
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )
        try:
            from ..models.task import record_current_task_llm
            full_prompt = f"[System Prompt]:\n{ONTOLOGY_SYSTEM_PROMPT}\n\n[User Prompt]:\n{user_message}"
            record_current_task_llm(
                stage="世界本体生成 (Ontology Generation)",
                model=getattr(self.llm_client, "model", "default"),
                prompt=full_prompt,
                response=json.dumps(result, ensure_ascii=False, indent=2),
                duration=_time.time() - _t0,
            )
        except Exception as e:
            logger.error(f"记录本体生成大模型交互失败: {e}", exc_info=True)

        # 验证和后处理
        result = self._validate_and_process(result)

        return result

    # 传给 LLM 的文本最大长度（5万字）
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """构建用户消息"""

        # 合并文本
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        # 如果文本超过5万字，截断（仅影响传给LLM的内容，不影响图谱构建）
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(原文共{original_length}字，已截取前{self.MAX_TEXT_LENGTH_FOR_LLM}字用于本体分析)..."

        message = f"""## 模拟需求

{simulation_requirement}

## 文档内容

{combined_text}
"""

        if additional_context:
            message += f"""
## 额外说明

{additional_context}
"""

        message += """
请根据以上内容，设计适合小说与架空世界推演的实体类型和关系类型。

**必须遵守的规则**：
1. 必须正好输出10个实体类型
2. 包含主要人物/主宰（Person）、势力/宗门/国家（Faction/Organization）、地点/世界秘境（Location/Realm）、关键道具/法宝/资源（Item/Artifact）、法则/事件规则（Law/Rule）等
3. 最后2个必须是兜底类型：Person（个人兜底）和 Organization（组织/势力兜底）
4. 前8个是根据小说与设定文本内容精心设计的具体核心类型
5. 属性名不能使用 name、uuid、group_id 等保留字，用 full_name、org_name 等替代
"""

        return message

    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """验证和后处理结果"""

        # 确保必要字段存在
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""

        # 验证实体类型
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # 确保description不超过100字符
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."

        # 验证关系类型
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."

        # Zep API 限制：最多 10 个自定义实体类型，最多 10 个自定义边类型
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # 兜底类型定义（跟随文档语言，默认中文）
        person_fallback = {
            "name": "个人",
            "description": "不属于任何更具体类型的自然人个体。",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "人物姓名"},
                {"name": "role", "type": "text", "description": "角色或职业"}
            ],
            "examples": ["普通市民", "匿名网友"]
        }

        organization_fallback = {
            "name": "组织",
            "description": "不属于任何更具体类型的组织机构。",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "组织名称"},
                {"name": "org_type", "type": "text", "description": "组织类型"}
            ],
            "examples": ["小企业", "社区团体"]
        }

        # 检查是否已有兜底类型（兼容英文旧数据）
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "个人" in entity_names or "Person" in entity_names
        has_organization = "组织" in entity_names or "Organization" in entity_names

        # 需要添加的兜底类型
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)

        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)

            # 如果添加后会超过 10 个，需要移除一些现有类型
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # 计算需要移除多少个
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # 从末尾移除（保留前面更重要的具体类型）
                result["entity_types"] = result["entity_types"][:-to_remove]

            # 添加兜底类型
            result["entity_types"].extend(fallbacks_to_add)

        # 最终确保不超过限制（防御性编程）
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        return result

    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        将本体定义转换为Python代码（类似ontology.py）

        Args:
            ontology: 本体定义

        Returns:
            Python代码字符串
        """
        code_lines = [
            '"""',
            '自定义实体类型定义',
            '由Miroworld自动生成，用于世界观与小说沙盘推演',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== 实体类型定义 ==============',
            '',
        ]

        # 生成实体类型
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")

            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        code_lines.append('# ============== 关系类型定义 ==============')
        code_lines.append('')

        # 生成关系类型
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # 转换为PascalCase类名
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")

            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        # 生成类型字典
        code_lines.append('# ============== 类型配置 ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')

        # 生成边的source_targets映射
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')

        return '\n'.join(code_lines)

