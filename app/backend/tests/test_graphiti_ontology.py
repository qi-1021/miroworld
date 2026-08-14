"""图谱本体中文命名与 Graphiti 类型模型接入测试。"""

import pytest
from pydantic import BaseModel

from app.services.ontology_generator import ONTOLOGY_SYSTEM_PROMPT
from app.services.zep_graphiti_impl import GraphitiClient


@pytest.fixture
def client():
    return GraphitiClient(neo4j_uri="bolt://localhost:7687", neo4j_user="neo4j", neo4j_password="password")


def test_ontology_prompt_requires_document_language_naming():
    """本体提示词必须支持中文命名（跟随文档语言），且兜底类型为中文。"""
    assert "使用文档主要语言" in ONTOLOGY_SYSTEM_PROMPT
    assert "中文文档用中文" in ONTOLOGY_SYSTEM_PROMPT
    assert "个人" in ONTOLOGY_SYSTEM_PROMPT
    assert "组织" in ONTOLOGY_SYSTEM_PROMPT
    # 系统保留字列表要覆盖 graphiti 的字段，避免抽取校验失败
    assert "entity_type" in ONTOLOGY_SYSTEM_PROMPT
    assert "fact_type" in ONTOLOGY_SYSTEM_PROMPT


def test_build_graphiti_type_models_chinese_names(client):
    """中文类型名与描述必须正确进入 graphiti 的模型字典。"""
    client._ontology_cache["graph_1"] = {
        "entities": [
            {
                "name": "学生",
                "description": "在校学生",
                "attributes": [{"name": "school", "description": "就读学校"}],
            },
            {
                "name": "大学",
                "description": "高等院校",
                "attributes": [],
            },
        ],
        "edges": [
            {"name": "就读于", "description": "学生与学校之间的关系"},
        ],
    }

    entity_types, edge_types = client._build_graphiti_type_models("graph_1")

    assert set(entity_types.keys()) == {"学生", "大学"}
    student_model = entity_types["学生"]
    assert issubclass(student_model, BaseModel)
    assert student_model.__doc__ == "在校学生"
    assert "school" in student_model.model_fields
    assert student_model.model_fields["school"].description == "就读学校"

    assert set(edge_types.keys()) == {"就读于"}
    assert edge_types["就读于"].__doc__ == "学生与学校之间的关系"
    assert issubclass(edge_types["就读于"], BaseModel)


def test_build_graphiti_type_models_skips_invalid_names(client):
    """空名称的条目应被跳过，不产生非法模型。"""
    client._ontology_cache["graph_2"] = {
        "entities": [{"name": "", "description": "x"}, {"name": "   ", "description": "y"}],
        "edges": [{"name": None, "description": "z"}],
    }

    entity_types, edge_types = client._build_graphiti_type_models("graph_2")

    assert entity_types == {}
    assert edge_types == {}


def test_graphiti_type_models_pass_validation(client):
    """生成的模型必须通过 graphiti 的字段校验（属性不与 EntityNode 保留字段重名）。"""
    from graphiti_core.utils.ontology_utils.entity_types_utils import validate_entity_types

    client._ontology_cache["graph_3"] = {
        "entities": [
            {
                "name": "媒体",
                "description": "媒体机构",
                "attributes": [
                    {"name": "media_type", "description": "媒体类型"},
                    {"name": "follower_count", "description": "粉丝数"},
                ],
            }
        ],
        "edges": [],
    }

    entity_types, _ = client._build_graphiti_type_models("graph_3")

    assert validate_entity_types(entity_types) is True
