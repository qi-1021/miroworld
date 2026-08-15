"""世界设定库服务测试"""

import json
from pathlib import Path

import pytest

from app.services.world_bible import WorldBibleService, WorldBible


@pytest.fixture()
def world_root(tmp_path, monkeypatch):
    """将世界数据根目录重定向到临时目录；默认禁用真实向量模型（保持离线快速）。

    需要验证语义检索的测试应注入 FakeEmbedder。
    """
    import app.services.world_bible as wb
    original = wb.WORLD_DATA_ROOT
    wb.WORLD_DATA_ROOT = str(tmp_path / "world")
    # 默认禁用真实模型加载（避免现有用例触发 bge-m3 加载与向量生成）
    WorldBibleService._reset_embedder_cache()
    WorldBibleService._reset_embeddings_cache()
    monkeypatch.setattr(
        WorldBibleService, "_get_embedder",
        classmethod(lambda cls: None),
    )
    yield wb.WORLD_DATA_ROOT
    wb.WORLD_DATA_ROOT = original
    WorldBibleService._reset_embedder_cache()
    WorldBibleService._reset_embeddings_cache()


BG_TEXT = (
    "艾泽拉斯大陆的东方是东境，由龙裔王国统治。龙裔王国建于三百年前，首都是龙脊城。"
    "王国信奉烈焰女神，禁止信仰冰霜教派。魔法需要付出代价：施法者每使用一次高阶魔法，"
    "就会消耗自身寿命。"
)

STORY_TEXT = (
    "清晨，龙脊城的街道上，平民艾拉正在抱怨。'五百年前建立的龙裔王国，如今连城门都破了。'"
    "她低声说。路过的法师卡尔随手施展了禁咒级火球术，将城门炸开一个大洞，毫发无损地走进来。"
)


def test_save_input_requires_at_least_one_source(world_root):
    with pytest.raises(ValueError):
        WorldBibleService.save_input("p1", background="", story="")


def test_save_input_background_only(world_root):
    bible = WorldBibleService.save_input("p1", background=BG_TEXT)
    assert bible.stats()["has_background"] is True
    assert bible.stats()["has_story"] is False
    assert bible.stats()["total_chunks"] >= 1
    assert all(c.source == "background" for c in bible.chunks)


def test_save_input_story_only(world_root):
    bible = WorldBibleService.save_input("p1", story=STORY_TEXT)
    assert bible.stats()["has_story"] is True
    assert bible.stats()["has_background"] is False


def test_save_input_both_sources(world_root):
    bible = WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)
    stats = bible.stats()
    assert stats["background_chunks"] >= 1
    assert stats["story_chunks"] >= 1
    sources = {c.source for c in bible.chunks}
    assert sources == {"background", "story"}


def test_chunks_have_offsets_and_keywords(world_root):
    bible = WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)
    for c in bible.chunks:
        assert c.char_end > c.char_start >= 0
        assert c.keywords, "每个块应有提取的关键词"
    # 背景块中应包含设定关键词
    bg_chunk = next(c for c in bible.chunks if c.source == "background")
    assert any("龙裔王国" in k for k in bg_chunk.keywords)


def test_bible_persists_to_disk(world_root):
    WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)
    path = Path(world_root) / "p1" / "bible.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["project_id"] == "p1"
    assert len(data["chunks"]) >= 2


def test_get_bible_roundtrip(world_root):
    WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)
    bible = WorldBibleService.get_bible("p1")
    assert isinstance(bible, WorldBible)
    assert bible.background_text == BG_TEXT
    assert bible.story_text == STORY_TEXT


def test_get_stats_missing_project(world_root):
    assert WorldBibleService.get_stats("nope") is None


def test_stats_exposes_saved_file_manifest(world_root):
    manifest = [
        {"filename": "背景设定.md", "size": 128, "source": "background"},
        {"filename": "第一章.txt", "size": 256, "source": "story"},
    ]
    bible = WorldBibleService.save_input(
        "p1", background=BG_TEXT, story=STORY_TEXT,
        metadata={"files": manifest},
    )
    stats = bible.stats()
    assert stats["files"] == manifest
    # 落盘后再次读取仍可见（前端世界设定页依赖 /settings 展示首页上传的文件）
    assert WorldBibleService.get_stats("p1")["files"] == manifest


def test_save_input_merges_file_manifest_across_uploads(world_root):
    first = [
        {"filename": "背景设定.md", "size": 128, "source": "background"},
        {"filename": "第一章.txt", "size": 256, "source": "story"},
    ]
    WorldBibleService.save_input(
        "p1", background=BG_TEXT, story=STORY_TEXT, metadata={"files": first}
    )
    second = [
        {"filename": "第二章.txt", "size": 300, "source": "story"},
        {"filename": "背景设定.md", "size": 200, "source": "background"},  # 同名同源 → 替换
    ]
    WorldBibleService.save_input("p1", story=STORY_TEXT, metadata={"files": second})
    files = WorldBibleService.get_stats("p1")["files"]
    by_key = {(f["filename"], f["source"]): f["size"] for f in files}
    assert by_key == {
        ("背景设定.md", "background"): 200,
        ("第一章.txt", "story"): 256,
        ("第二章.txt", "story"): 300,
    }


def test_search_finds_relevant_chunks(world_root):
    WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)

    results = WorldBibleService.search("p1", "龙脊城")
    assert len(results) >= 1
    assert all(r["score"] > 0 for r in results)

    # 来源过滤
    bg_only = WorldBibleService.search("p1", "龙脊城", source="background")
    assert all(r["source"] == "background" for r in bg_only)


def test_search_empty_query(world_root):
    WorldBibleService.save_input("p1", background=BG_TEXT)
    assert WorldBibleService.search("p1", "") == []


def test_search_missing_project(world_root):
    assert WorldBibleService.search("nope", "龙脊城") == []


def test_search_exclude_chunks(world_root):
    WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)
    results = WorldBibleService.search("p1", "龙脊城", limit=10)
    ids = [r["chunk_id"] for r in results]
    filtered = WorldBibleService.search("p1", "龙脊城", exclude_chunk_ids=ids)
    assert filtered == []


def test_delete_removes_all_data(world_root):
    WorldBibleService.save_input("p1", background=BG_TEXT)
    assert WorldBibleService.delete("p1") is True
    assert WorldBibleService.get_bible("p1") is None


# ---------------- 语义向量（bge-m3）检索 ----------------

class FakeEmbedder:
    """小维度假嵌入：按"概念家族"生成可解释向量，便于验证融合排序。

    dim=8；同义/近义概念词（如"神明/诸神/神殿"）映射到同一分量，
    这让不含查询字面词但概念相近的文本也能获得高余弦相似度，
    从而可验证"语义召回 + 语义/关键词融合"而不仅是字面命中。
    """

    DIM = 8

    def __init__(self):
        self.model_dir = "/fake/bge-m3"

    @property
    def dimension(self):
        return self.DIM

    # 概念家族 -> 分量下标（家族内任意词命中即激活该分量）
    FAMILIES = {
        0: {"火焰", "烈火", "烈焰"},
        1: {"魔法", "法术", "咒法"},
        2: {"施法者", "法师"},
        3: {"神明", "诸神", "神殿", "神祇"},
        4: {"城门", "城墙"},
        5: {"国王", "王城", "君主"},
        6: {"地牢", "监牢"},
        7: {"弩箭", "弓箭"},
    }

    def _vec(self, text):
        v = [0.0] * self.DIM
        for idx, family in self.FAMILIES.items():
            if any(word in text for word in family):
                v[idx] = 1.0
        return v

    def _encode(self, texts):
        return [self._vec(t) for t in texts]

    async def create(self, input_data):
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        return self._vec(texts[0])

    async def create_batch(self, input_data_list):
        return self._encode(list(input_data_list))


@pytest.fixture()
def semantic_embedder(world_root, monkeypatch):
    """注入小维度假嵌入（启用语义向量 + 融合检索）。"""
    WorldBibleService._reset_embedder_cache()
    WorldBibleService._reset_embeddings_cache()
    monkeypatch.setattr(
        WorldBibleService, "_get_embedder",
        classmethod(lambda cls: FakeEmbedder()),
    )
    return FakeEmbedder()


def test_save_input_generates_and_persists_embeddings(semantic_embedder, world_root):
    """分块后生成向量，落盘 embeddings.npy + meta，bible.json 不含向量。"""
    bible = WorldBibleService.save_input("p1", background=BG_TEXT)
    root = Path(world_root)
    npy_path = root / "p1" / "embeddings.npy"
    meta_path = root / "p1" / "embeddings_meta.json"
    assert npy_path.exists()
    assert meta_path.exists()
    # 元数据记录模型名
    assert bible.metadata.get("embedding_model") == "bge-m3"
    # 返回的块内存中带向量
    for c in bible.chunks:
        assert c.embedding, "分块应带语义向量"
        assert len(c.embedding) == FakeEmbedder.DIM
    # bible.json 不得含向量（防体积爆炸）
    bible_on_disk = json.loads((root / "p1" / "bible.json").read_text(encoding="utf-8"))
    assert all("embedding" not in c for c in bible_on_disk["chunks"])


def test_load_embeddings_roundtrip(semantic_embedder, world_root):
    """懒读取向量：load_embeddings 返回 {chunk_id: vec}。"""
    WorldBibleService.save_input("p1", background=BG_TEXT)
    bible = WorldBibleService.get_bible("p1")
    vecs = WorldBibleService.load_embeddings("p1")
    assert vecs is not None
    assert set(vecs.keys()) == {c.chunk_id for c in bible.chunks}
    # 第二次读取走缓存，仍正确
    vecs2 = WorldBibleService.load_embeddings("p1")
    assert vecs2 == vecs


def test_search_semantic_fusion_ranking(semantic_embedder, world_root):
    """融合排序：语义更贴近查询的块应排在前面。

    两块都命中关键词"神明"，但 A 只含"神明"（高余弦），
    B 还携带大量无关概念稀释相似度（低余弦），故 A 语义分更高、排第一。
    """
    WorldBibleService.save_input(
        "p1",
        background="信徒在神庙中祭拜神明",         # A：仅含"神明"，语义最贴近
        story="守城的士兵同时谈论神明、城门、国王、地牢和弩箭",  # B：语义被稀释
    )
    results = WorldBibleService.search("p1", "神明")
    assert len(results) >= 2
    top_text = results[0]["text"]
    assert "神庙" in top_text or "祭拜" in top_text
    assert results[0]["score"] > results[1]["score"]


def test_search_semantic_only_via_concept(semantic_embedder, world_root):
    """语义可召回不含查询字面词但概念相近的块（0.6 * 语义分）。"""
    WorldBibleService.save_input(
        "p1",
        background="我们信奉掌控烈火的诸神，神殿遍布王城各地",
    )
    # 查询"神明"（字面不在文本中），但"诸神/神殿"属同一概念家族 → 语义召回
    results = WorldBibleService.search("p1", "神明")
    assert len(results) >= 1
    assert results[0]["score"] > 0


def test_search_semantic_false_skips_vector(semantic_embedder, world_root):
    """semantic=False 时跳过语义向量化，仅关键词检索。"""
    WorldBibleService.save_input(
        "p1",
        background="我们信奉掌控烈火的诸神，神殿遍布王城各地",
    )
    # semantic=False：查询"神明"字面不在文本 → 无语义召回 → 结果为空
    off = WorldBibleService.search("p1", "神明", semantic=False)
    assert off == []
    # 语义开关默认(True)：概念相近 → 被召回
    on = WorldBibleService.search("p1", "神明", semantic=True)
    assert len(on) >= 1


def test_search_degradation_no_embedder(world_root):
    """本地向量模型不可用时降级为纯关键词，仍返回关键词结果。"""
    # world_root 已把 _get_embedder 置为 None；不落盘向量
    WorldBibleService.save_input("p1", background=BG_TEXT)
    results = WorldBibleService.search("p1", "龙脊城")
    assert len(results) >= 1
    assert all(r["score"] > 0 for r in results)
    # 结构保持
    keys = {"chunk_id", "source", "text", "section", "char_start", "char_end", "score"}
    for r in results:
        assert keys <= set(r.keys())


def test_search_source_filter_preserved_with_semantic(semantic_embedder, world_root):
    """语义检索仍保留 source 过滤。"""
    WorldBibleService.save_input("p1", background=BG_TEXT, story=STORY_TEXT)
    bg = WorldBibleService.search("p1", "龙脊城", source="background")
    assert bg and all(r["source"] == "background" for r in bg)
    st = WorldBibleService.search("p1", "城门", source="story")
    assert st and all(r["source"] == "story" for r in st)


def test_search_degrades_to_keyword_when_query_embedding_raises(world_root, monkeypatch):
    """查询向量化抛异常时应优雅降级为纯关键词，不向上抛错。"""
    WorldBibleService._reset_embeddings_cache()
    WorldBibleService._reset_embedder_cache()

    # 保存时用可用假嵌入生成向量，随后搜索时让查询向量化抛异常
    ok_embedder = FakeEmbedder()
    monkeypatch.setattr(
        WorldBibleService, "_get_embedder",
        classmethod(lambda cls: ok_embedder),
    )
    WorldBibleService.save_input("p1", background=BG_TEXT)

    # 让 embedder 在查询时抛异常（create 抛）→ 应回退关键词
    class BrokenEmbedder:
        dimension = FakeEmbedder.DIM
        model_dir = "/fake/bge-m3"
        async def create(self, *a, **k):
            raise RuntimeError("模型加载失败")
        async def create_batch(self, *a, **k):
            raise RuntimeError("模型加载失败")
        def _encode(self, *a, **k):
            raise RuntimeError("模型加载失败")

    monkeypatch.setattr(
        WorldBibleService, "_get_embedder",
        classmethod(lambda cls: BrokenEmbedder()),
    )
    # 不抛异常，且仍能按关键词命中
    results = WorldBibleService.search("p1", "龙脊城")
    assert results, "查询向量化失败后仍应返回关键词结果"
    assert all(r["score"] > 0 for r in results)


def test_save_input_degrades_when_embedding_generation_raises(world_root, monkeypatch):
    """save_input 向量生成抛异常时仍应成功保存主体，降级为纯关键词。"""
    WorldBibleService._reset_embeddings_cache()
    WorldBibleService._reset_embedder_cache()

    class ExplodingEmbedder:
        dimension = FakeEmbedder.DIM
        model_dir = "/fake/bge-m3"
        async def create_batch(self, *a, **k):
            raise RuntimeError("编码器不可用")

    monkeypatch.setattr(
        WorldBibleService, "_get_embedder",
        classmethod(lambda cls: ExplodingEmbedder()),
    )
    # 不应抛出；bible 仍保存
    bible = WorldBibleService.save_input("p1", background=BG_TEXT)
    assert bible.project_id == "p1"
    assert bible.chunks
    # 未生成向量
    assert not any(c.embedding for c in bible.chunks)
    assert bible.metadata.get("embedding_model") is None
    # 检索仍可用（降级为关键词）
    results = WorldBibleService.search("p1", "龙脊城")
    assert results
