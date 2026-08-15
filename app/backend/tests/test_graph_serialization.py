"""图谱序列化：节点/边响应不得包含向量（embedding）字段。"""

from types import SimpleNamespace

from app.services.graph_builder import GraphBuilderService, strip_embedding_fields


def _node(name='阿米娅', **extra):
    d = {
        "uuid": "n1", "name": name, "labels": ["人物", "Entity"],
        "summary": "罗德岛的年轻领袖", "attributes": {"年龄": "14岁"},
        "created_at": "2026-01-01",
        "name_embedding": [0.1] * 1024,
        "description_embedding": [0.2] * 1024,
    }
    d.update(extra)
    return SimpleNamespace(**d)


def _edge():
    return SimpleNamespace(
        uuid="e1", name="属于", fact="阿米娅属于罗德岛",
        source_node_uuid="n1", target_node_uuid="n2",
        attributes={"权重": 1}, created_at="2026-01-01",
        valid_at=None, invalid_at=None, expired_at=None, episodes=[],
        fact_embeddings=[[0.3] * 1024],
    )


def test_get_graph_data_strips_embeddings(monkeypatch):
    client = SimpleNamespace(
        get_all_nodes=lambda gid: [_node()],
        get_all_edges=lambda gid: [_edge()],
    )
    builder = GraphBuilderService()
    monkeypatch.setattr(builder, 'client', client)

    data = builder.get_graph_data('g1')

    assert data["node_count"] == 1 and data["edge_count"] == 1
    raw = data["nodes"][0]
    assert 'name_embedding' not in raw and 'description_embedding' not in raw
    assert raw["name"] == '阿米娅' and raw["attributes"] == {"年龄": "14岁"}
    raw_e = data["edges"][0]
    assert 'fact_embeddings' not in raw_e
    assert raw_e["fact"] == '阿米娅属于罗德岛'
    # 全量 JSON 无 embedding 字样
    import json
    blob = json.dumps(data, ensure_ascii=False)
    assert 'embedding' not in blob.lower()


def test_strip_embedding_fields_recursive():
    obj = {
        "a": {"name_embedding": [1], "ok": 1},
        "b": [{"fact_embeddings": [1]}, {"name": "x"}],
        "c": "plain",
    }
    out = strip_embedding_fields(obj)
    # 注意：仅含 embedding 的 dict 剥离后保留为空 dict {}
    assert out == {"a": {"ok": 1}, "b": [{}, {"name": "x"}], "c": "plain"}
    # 非 dict/list 原样返回
    assert strip_embedding_fields(42) == 42
