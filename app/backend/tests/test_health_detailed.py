"""详细健康检查端点测试。"""

from app import create_app


def test_detailed_health_returns_checks():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/health/detailed")
        assert r.status_code == 200
        data = r.get_json()
        assert data["service"] == "MiroFish Backend"
        assert "neo4j" in data  # ok 或 unavailable 都允许
        assert "models" in data
        assert "verified" in data["models"]
        assert "data_writable" in data
        assert data["status"] in ("ok", "degraded")
