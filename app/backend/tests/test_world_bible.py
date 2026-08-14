"""世界设定库服务测试"""

import json
import tempfile
from pathlib import Path

import pytest

from app.services.world_bible import WorldBibleService, WorldBible


@pytest.fixture()
def world_root(tmp_path):
    """将世界数据根目录重定向到临时目录"""
    import app.services.world_bible as wb
    original = wb.WORLD_DATA_ROOT
    wb.WORLD_DATA_ROOT = str(tmp_path / "world")
    yield wb.WORLD_DATA_ROOT
    wb.WORLD_DATA_ROOT = original


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
