"""SPEC-12 §6 · 发现域测试（M2-3b）。

抓取测试 monkeypatch ``rss.httpx.get`` 给假响应，不打真网络。
「诚实模式」是重点：日报/内容缺口在数据不足时**不调模型**（fake.requests 为空）。
合规门禁用「全网最好」触发 BLOCK。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from atelier.server import paths
from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.discovery import rss as rss_mod
from atelier.server.main import create_app

if TYPE_CHECKING:
    from conftest import ScriptedHarness

JSON = {"Content-Type": "application/json"}

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>测试源</title>
<item><title>AI 工具横评：写作者的真实体感</title><link>https://example.com/a</link>
<description>一篇关于 AI 写作工具的横评</description><pubDate>Tue, 30 Sep 2026 10:00:00 +0800</pubDate>
<guid>guid-a</guid></item>
<item><title>今天天气很好</title><link>https://example.com/b</link><description>无关内容</description>
<pubDate>Wed, 01 Oct 2026 09:00:00 +0800</pubDate><guid>guid-b</guid></item>
</channel></rss>"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom 源</title>
<entry><title>Atom 条目：选题方法</title><link href="https://example.org/1"/>
<summary>怎么选题</summary><updated>2026-10-01T12:00:00Z</updated><id>atom-1</id></entry>
</feed>"""

DIGEST_OK = (
    "## 热点盘点\n\n素材 1 讲 AI 工具横评，属于工具类话题。\n\n"
    "## 机会点\n\n素材 1 与创作方向相关，可以做实操对比。\n\n"
    "## 建议动作\n\n针对素材 1 出一篇亲测体感文。"
)


@pytest.fixture
def client(atelier_root: Any) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


def _sub(client: TestClient, *, source: str = "rss", url: str | None = "https://example.com/rss",
         keywords: str | None = None, name: str = "测试博主") -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "kind": "blogger", "source": source}
    if url is not None:
        body["url"] = url
    if keywords is not None:
        body["keywords"] = keywords
    r = client.post("/api/discovery/subscriptions", json=body, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()


def _fake_http(payload: bytes | Exception, status: int = 200):
    """替换 rss.httpx.get：返回指定字节或抛指定异常。"""

    def fake_get(url: str, **kwargs: Any):
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload, status)

    return fake_get


class _FakeResponse:
    def __init__(self, content: bytes, status: int) -> None:
        self.content = content
        self.status_code = status


# --------------------------------------------------------------------------- schema


class TestSchemaV6:
    def test_fresh_db_has_all_tables(self, client: TestClient) -> None:
        names = set(db.table_names())
        for t in ("subscriptions", "feed_items", "hot_entries", "hot_digests", "algorithm_notes"):
            assert t in names
        assert db.schema_version() == 8  # M5 起 v8（归因域 3 表，SPEC-15）

    def test_migration_v5_to_v6_keeps_old_data(self, atelier_root: Any) -> None:
        """老库（v5）升级到 v6：新表出现、老数据保留。"""
        paths.ensure_dirs()
        conn = sqlite3.connect(str(db.db_path()))
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, title TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO topics (id, title) VALUES ('t-old', '老选题')")
            conn.execute("PRAGMA user_version=5")
        conn.close()
        db.reset_conn()
        applied = db.migrate()
        assert "v6" in applied
        assert db.schema_version() == 8  # M5 起 v8（归因域 3 表，SPEC-15）
        with db.db_session(commit=False) as c:
            assert c.execute("SELECT title FROM topics WHERE id='t-old'").fetchone()[0] == "老选题"
            assert c.execute(
                "SELECT 1 FROM sqlite_master WHERE name='subscriptions'"
            ).fetchone() is not None

    def test_delete_subscription_cascades_feed(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        assert r.status_code == 200 and r.json()["inserted"] == 2
        assert client.delete(f"/api/discovery/subscriptions/{sub['id']}").json()["ok"] is True
        with db.db_session(commit=False) as c:
            assert c.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0] == 0


# --------------------------------------------------------------------------- 订阅 CRUD


class TestSubscriptions:
    def test_create_and_get(self, client: TestClient) -> None:
        sub = _sub(client, keywords="AI, 工具,效率")
        assert sub["keywords"] == ["AI", "工具", "效率"]
        assert sub["enabled"] is True and sub["last_fetched_at"] == ""
        got = client.get("/api/discovery/subscriptions").json()
        assert got["total"] == 1

    def test_rss_requires_url(self, client: TestClient) -> None:
        r = client.post(
            "/api/discovery/subscriptions",
            json={"name": "无地址", "kind": "blogger", "source": "rss"},
            headers=JSON,
        )
        assert r.status_code == 422 and "URL" in r.json()["error"]["message"]

    def test_bad_url_and_kind(self, client: TestClient) -> None:
        r = client.post(
            "/api/discovery/subscriptions",
            json={"name": "x", "kind": "blogger", "source": "rss", "url": "ftp://x"},
            headers=JSON,
        )
        assert r.status_code == 422
        r = client.post(
            "/api/discovery/subscriptions",
            json={"name": "x", "kind": "shop", "source": "manual"},
            headers=JSON,
        )
        assert r.status_code == 422 and "kind" in r.json()["error"]["message"]

    def test_manual_source_allows_empty_url(self, client: TestClient) -> None:
        sub = _sub(client, source="manual", url=None, name="手填博主")
        assert sub["source"] == "manual" and sub["url"] == ""

    def test_patch_keywords_and_enabled(self, client: TestClient) -> None:
        sub = _sub(client)
        r = client.patch(
            f"/api/discovery/subscriptions/{sub['id']}",
            json={"keywords": ["选题", "爆款"], "enabled": False},
            headers=JSON,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["keywords"] == ["选题", "爆款"] and body["enabled"] is False

    def test_delete_404(self, client: TestClient) -> None:
        assert client.delete("/api/discovery/subscriptions/sub-nope").status_code == 404


# --------------------------------------------------------------------------- 抓取


class TestFetch:
    def test_fetch_rss_filters_and_persists(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client, keywords="AI")
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["parsed"] == 2 and body["inserted"] == 1 and body["filtered"] == 1
        feed = client.get(f"/api/discovery/feed?subscription_id={sub['id']}").json()
        assert feed["total"] == 1
        assert "AI 工具横评" in feed["items"][0]["title"]
        assert feed["items"][0]["published_at"].startswith("2026-09-30T02:00:00")

    def test_fetch_dedup_second_round(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        first = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON).json()
        second = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON).json()
        assert first["inserted"] == 2 and second["inserted"] == 0  # 唯一索引去重（SPEC-12 §0 D4）

    def test_fetch_atom(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client, name="Atom 博主")
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(ATOM_XML.encode()))
        body = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON).json()
        assert body["inserted"] == 1
        feed = client.get("/api/discovery/feed").json()
        assert feed["items"][0]["url"] == "https://example.org/1"

    def test_fetch_bad_xml(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http("<html>这不是 RSS</html>".encode()))
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "DiscoveryFetchFailed" and "订阅格式" in err["message"]

    def test_fetch_timeout(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx as httpx_mod

        sub = _sub(client)
        exc = httpx_mod.ConnectTimeout("timeout")
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(exc))
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["detail"]["reason"] == "timeout"

    def test_fetch_http_error(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(b"gone", status=404))
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        assert r.status_code == 422 and "404" in r.json()["error"]["message"]

    def test_fetch_manual_source_rejected(self, client: TestClient) -> None:
        sub = _sub(client, source="manual", url=None)
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        assert r.status_code == 422 and "手填" in r.json()["error"]["message"]

    def test_deep_load_rss_honest_notice(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/deep-load", headers=JSON)
        assert r.status_code == 200
        body = r.json()
        assert "不假装能翻页" in body["notice"] and body["inserted"] == 2

    def test_deep_load_manual_rejected(self, client: TestClient) -> None:
        sub = _sub(client, source="manual", url=None)
        r = client.post(f"/api/discovery/subscriptions/{sub['id']}/deep-load", headers=JSON)
        assert r.status_code == 422 and "手填" in r.json()["error"]["message"]

    def test_fetch_all_partial_failure(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        ok_sub = _sub(client, name="好源")
        bad_sub = _sub(client, url="https://example.com/broken", name="坏源")

        def fake_get(url: str, **kwargs: Any):
            if "broken" in url:
                raise RuntimeError("connection refused")
            return _FakeResponse(RSS_XML.encode(), 200)

        monkeypatch.setattr(rss_mod.httpx, "get", fake_get)
        r = client.post("/api/discovery/fetch-all", headers=JSON)
        assert r.status_code == 200
        body = r.json()
        assert body["ok_count"] == 1 and body["total"] == 2
        results = {x["subscription_id"]: x for x in body["results"]}
        assert results[ok_sub["id"]]["ok"] is True
        assert results[bad_sub["id"]]["ok"] is False

    def test_ingest_manual(self, client: TestClient) -> None:
        sub = _sub(client, source="manual", url=None)
        r = client.post(
            f"/api/discovery/subscriptions/{sub['id']}/ingest",
            json={"title": "手填的一条内容", "url": "https://example.com/x", "summary": "摘要"},
            headers=JSON,
        )
        assert r.status_code == 201 and r.json()["inserted"] is True
        again = client.post(
            f"/api/discovery/subscriptions/{sub['id']}/ingest",
            json={"title": "手填的一条内容", "url": "https://example.com/x"},
            headers=JSON,
        ).json()
        assert again["inserted"] is False  # 同内容去重
        r = client.post(
            f"/api/discovery/subscriptions/{sub['id']}/ingest", json={"title": " "}, headers=JSON
        )
        assert r.status_code == 422


# --------------------------------------------------------------------------- feed / UGC


class TestFeedAndUgc:
    def test_feed_window_and_search(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        feed = client.get("/api/discovery/feed", params={"days": 7}).json()
        assert feed["days"] == 7 and feed["total"] == 2
        hit = client.get("/api/discovery/feed", params={"q": "横评"}).json()
        assert hit["total"] == 1
        bad = client.get("/api/discovery/feed", params={"days": 9999})
        assert bad.status_code == 422

    def test_ugc_search(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client, name="搜索源")
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        r = client.get("/api/discovery/ugc", params={"q": "AI"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1 and body["items"][0]["subscription_name"] == "搜索源"
        assert "订阅" in body["notice"]
        assert client.get("/api/discovery/ugc", params={"q": " "}).status_code == 422


# --------------------------------------------------------------------------- 热点素材池


class TestHot:
    def test_create_and_list(self, client: TestClient) -> None:
        r = client.post(
            "/api/discovery/hot",
            json={"title": "热点一：某平台算法调整", "platform": "dy", "heat": "榜3"},
            headers=JSON,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending" and body["entry_date"] != ""
        listed = client.get("/api/discovery/hot").json()
        assert listed["total"] == 1 and listed["counts"]["pending"] == 1

    def test_create_validation(self, client: TestClient) -> None:
        r = client.post("/api/discovery/hot", json={"title": " "}, headers=JSON)
        assert r.status_code == 422
        r = client.post("/api/discovery/hot", json={"title": "x", "source": "weibo"}, headers=JSON)
        assert r.status_code == 422

    def test_from_feed_and_dup_guard(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        feed = client.get("/api/discovery/feed").json()
        ids = [i["id"] for i in feed["items"]]
        r = client.post("/api/discovery/hot/from-feed", json={"ids": ids}, headers=JSON)
        assert r.status_code == 200
        body = r.json()
        assert body["inserted"] == 2
        entry = body["created"][0]
        full = client.get("/api/discovery/hot").json()["items"]
        target = next(x for x in full if x["id"] == entry["id"])
        assert target["source"] == "rss" and target["url"] != ""
        # 重复转入 → 全部 skip
        again = client.post("/api/discovery/hot/from-feed", json={"ids": ids}, headers=JSON).json()
        assert again["inserted"] == 0 and len(again["skipped"]) == 2
        # 不存在的 id → skip
        miss = client.post("/api/discovery/hot/from-feed", json={"ids": ["feed-nope"]}, headers=JSON).json()
        assert miss["inserted"] == 0 and miss["skipped"] == ["feed-nope"]

    def test_patch_status(self, client: TestClient) -> None:
        entry = client.post("/api/discovery/hot", json={"title": "待归档"}, headers=JSON).json()
        r = client.patch(f"/api/discovery/hot/{entry['id']}", json={"status": "archived"}, headers=JSON)
        assert r.json()["status"] == "archived"
        bad = client.patch(f"/api/discovery/hot/{entry['id']}", json={"status": "xx"}, headers=JSON)
        assert bad.status_code == 422

    def test_filter_by_status(self, client: TestClient) -> None:
        client.post("/api/discovery/hot", json={"title": "甲"}, headers=JSON)
        arch = client.post("/api/discovery/hot", json={"title": "乙"}, headers=JSON).json()
        client.patch(f"/api/discovery/hot/{arch['id']}", json={"status": "archived"}, headers=JSON)
        pend = client.get("/api/discovery/hot", params={"status": "pending"}).json()
        assert pend["total"] == 1 and pend["items"][0]["title"] == "甲"


# --------------------------------------------------------------------------- 日报


class TestDigest:
    def test_insufficient_no_model_call(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/discovery/hot/digest", json={}, headers=JSON)
        assert r.status_code == 200
        body = r.json()
        assert body["insufficient"] is True and body["need"] == 1
        assert "不编造" in body["message"]
        assert fake.requests == []  # 素材池空不调模型（SPEC-12 §0 D3）

    def test_digest_success_marks_entries(self, client: TestClient, fake: ScriptedHarness) -> None:
        client.post("/api/discovery/hot", json={"title": "热点 A", "platform": "xhs", "heat": "榜1"}, headers=JSON)
        client.post("/api/discovery/hot", json={"title": "热点 B"}, headers=JSON)
        fake.outputs = [DIGEST_OK]
        r = client.post("/api/discovery/hot/digest", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is False and body["entry_count"] == 2
        assert all(body["sections"].values())
        assert body["digest"]["markdown"] == DIGEST_OK
        assert fake.requests[0].session_id.startswith("discovery-digest-")
        assert "热点 A" in fake.requests[0].prompt  # 素材由代码注入
        pool = client.get("/api/discovery/hot").json()
        assert pool["counts"]["pending"] == 0 and pool["counts"]["digested"] == 2
        history = client.get("/api/discovery/hot/digests").json()
        assert history["total"] == 1
        detail = client.get(f"/api/discovery/hot/digests/{history['items'][0]['id']}").json()
        assert "热点盘点" in detail["markdown"]

    def test_digest_missing_section_422(self, client: TestClient, fake: ScriptedHarness) -> None:
        client.post("/api/discovery/hot", json={"title": "热点 C"}, headers=JSON)
        fake.outputs = ["## 热点盘点\n\n只有一段。"]
        r = client.post("/api/discovery/hot/digest", json={}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "DiscoveryIncomplete" and "机会点" in err["detail"]["missing"]

    def test_digest_gate_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        client.post("/api/discovery/hot", json={"title": "热点 D"}, headers=JSON)
        fake.outputs = [
            "## 热点盘点\n\n全网最好的热点来了。\n\n## 机会点\n\n可以做。\n\n## 建议动作\n\n马上做。"
        ]
        r = client.post("/api/discovery/hot/digest", json={}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "GateBlocked" and err["detail"]["gate_items"]
        # BLOCK 时日报不落库、条目不动
        assert client.get("/api/discovery/hot").json()["counts"]["pending"] == 1


# --------------------------------------------------------------------------- 内容缺口


class TestGaps:
    def test_insufficient_no_model_call(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/discovery/gaps", json={}, headers=JSON)
        assert r.status_code == 200
        body = r.json()
        assert body["insufficient"] is True and body["stats"]["feed_total"] == 0
        assert "不编造" in body["message"]
        assert fake.requests == []

    def test_success_with_stats_injection(self, client: TestClient, fake: ScriptedHarness, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client, keywords="AI")
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        client.post("/api/topics", json={"title": "我的 AI 工具选题"}, headers=JSON)
        fake.outputs = [json.dumps({
            "gaps": [
                {"direction": "AI 工具实操对比", "demand": "订阅关键词 AI 命中 1 条",
                 "evidence": "本方选题池仅 1 条泛 AI 选题，缺实操向", "action": "出一篇亲测对比"}
            ]
        }, ensure_ascii=False)]
        r = client.post("/api/discovery/gaps", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is False and len(body["gaps"]) == 1
        assert body["stats"]["keyword_counts"].get("AI") == 1  # 代码统计（SPEC-12 §0 D3）
        assert "AI" in fake.requests[0].prompt
        assert fake.requests[0].session_id.startswith("discovery-gaps-")

    def test_bad_json_502(self, client: TestClient, fake: ScriptedHarness, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        fake.outputs = ["这不是 JSON"]
        r = client.post("/api/discovery/gaps", json={}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"

    def test_gap_over_limit_502(self, client: TestClient, fake: ScriptedHarness, monkeypatch: pytest.MonkeyPatch) -> None:
        sub = _sub(client)
        monkeypatch.setattr(rss_mod.httpx, "get", _fake_http(RSS_XML.encode()))
        client.post(f"/api/discovery/subscriptions/{sub['id']}/fetch", headers=JSON)
        fake.outputs = [json.dumps({
            "gaps": [
                {"direction": f"方向{i}", "demand": "需求依据数据", "evidence": "竞争空白依据", "action": "动作"}
                for i in range(7)
            ]
        }, ensure_ascii=False)]
        r = client.post("/api/discovery/gaps", json={}, headers=JSON)
        assert r.status_code == 502 and "上限" in r.json()["error"]["message"]


# --------------------------------------------------------------------------- 算法追踪


class TestAlgorithmNotes:
    def test_crud(self, client: TestClient) -> None:
        r = client.post(
            "/api/discovery/algorithm-notes",
            json={"platform": "xhs", "noted_at": "2026-10-01", "change": "图文流量池规则调整", "impact": "首图点击率权重上升"},
            headers=JSON,
        )
        assert r.status_code == 201
        listed = client.get("/api/discovery/algorithm-notes").json()
        assert listed["total"] == 1 and "手工登记" in listed["notice"]
        nid = listed["items"][0]["id"]
        assert client.delete(f"/api/discovery/algorithm-notes/{nid}").json()["ok"] is True
        assert client.get("/api/discovery/algorithm-notes").json()["total"] == 0

    def test_validation(self, client: TestClient) -> None:
        r = client.post(
            "/api/discovery/algorithm-notes",
            json={"platform": "", "noted_at": "2026-10-01", "change": "x"},
            headers=JSON,
        )
        assert r.status_code == 422
        r = client.post(
            "/api/discovery/algorithm-notes",
            json={"platform": "xhs", "noted_at": "2026-10-1", "change": "宽松日期"},
            headers=JSON,
        )
        assert r.status_code == 422 and "不是合法日期" in r.json()["error"]["message"]
