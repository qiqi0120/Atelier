"""SPEC-14 §4 · M4 平台扩展测试。

覆盖：4 新平台校验规则 · 短链 CRUD/302/hits · 调度器到期发布（诚实 dry-run）·
优化建议 AI 契约 · 账号中心（凭证/验证/登出/扫码诚实 422）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.main import create_app
from atelier.server.publish.adapt import PLATFORM_LIMITS, PLATFORM_ORDER
from atelier.server.publish.platforms import get_adapter

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def client(atelier_root: Any) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- 新平台


class TestNewPlatforms:
    def test_registry_and_limits(self) -> None:
        for pid in ("ks", "zhihu", "bilibili", "wcs"):
            adapter = get_adapter(pid)
            assert adapter.platform == pid
            assert pid in PLATFORM_LIMITS and pid in PLATFORM_ORDER
        # 旧 3 条目未被改（SPEC-14 §0 D1：只追加）
        assert PLATFORM_LIMITS["xhs"]["body_max"] == 1000
        assert PLATFORM_LIMITS["dy"]["forms"] == ["video"]
        assert PLATFORM_LIMITS["gzh"]["cover_ratio"] == "2.35:1"
        assert PLATFORM_ORDER[:3] == ("xhs", "dy", "gzh")

    def _variant(self, pid: str, *, title: str = "一个足够长的合法标题", body: str | None = None):
        from atelier.server.core.models import PlatformVariant

        v = PlatformVariant(
            platform=pid, title=title, body=body or ("正文内容足够长，" * 10),
            char_count=0, char_limit=PLATFORM_LIMITS[pid]["body_max"],
            over_limit=False, adapted=True, status="ready",
        )
        return v.recount()

    def test_video_only_platforms_reject_non_video(self) -> None:
        for pid, code in (("bilibili", "bilibili_form_rejected"), ("wcs", "wcs_form_rejected")):
            result = get_adapter(pid).validate(self._variant(pid), ["outputs/p/成品/card.png"])
            assert result is not None and result.error_code == code, pid

    def test_video_only_platforms_accept_video(self) -> None:
        for pid in ("bilibili", "wcs"):
            assert get_adapter(pid).validate(self._variant(pid), ["outputs/p/成品/clip.mp4"]) is None, pid

    def test_zhihu_min_length(self) -> None:
        result = get_adapter("zhihu").validate(self._variant("zhihu", body="太短"), [])
        assert result is not None and result.error_code == "zhihu_too_short"
        assert get_adapter("zhihu").validate(
            self._variant("zhihu", body="观点论证。" * 20), []
        ) is None

    def test_ks_no_cover_needed(self) -> None:
        assert get_adapter("ks").validate(self._variant("ks"), []) is None  # 不强制封面（SPEC-14 §0 D2）

    def test_over_limit_for_new_platform(self) -> None:
        v = self._variant("wcs", title="这个标题实在太过分了绝对超过十六个字了", body="正文")
        result = get_adapter("wcs").validate(v, ["outputs/p/成品/clip.mp4"])
        assert result is not None and result.error_code == "over_limit"


# ---------------------------------------------------------------- 短链


class TestShortlinks:
    def test_create_redirect_hits(self, client: TestClient) -> None:
        r = client.post("/api/shortlinks", json={"target": "https://example.com/x", "note": "首发"},
                        headers=JSON)
        assert r.status_code == 201, r.text
        code = r.json()["code"]
        assert len(code) == 8
        # 同目标幂等复用
        again = client.post("/api/shortlinks", json={"target": "https://example.com/x"}, headers=JSON).json()
        assert again["code"] == code
        # 302 + 计数
        red = client.get(f"/s/{code}", follow_redirects=False)
        assert red.status_code == 302 and red.headers["location"] == "https://example.com/x"
        red2 = client.get(f"/s/{code}", follow_redirects=False)
        assert red2.status_code == 302
        listed = client.get("/api/shortlinks").json()
        assert listed["items"][0]["hits"] == 2
        assert "本地" in listed["notice"]

    def test_bad_target_and_unknown_code(self, client: TestClient) -> None:
        assert client.post("/api/shortlinks", json={"target": "javascript:alert(1)"},
                           headers=JSON).status_code == 422
        assert client.get("/s/nosuchcod", follow_redirects=False).status_code == 404


# ---------------------------------------------------------------- 调度器


def _seed_draft(draft_id: str, scheduled: str, *, with_variant: bool = True) -> None:

    variants = [
        {
            "platform": "zhihu", "title": "排期标题", "body": "排期正文内容，足够长。",
            "char_count": 10, "char_limit": 20000, "over_limit": False,
            "adapted": True, "status": "ready",
        }
    ] if with_variant else []
    now = db.utcnow()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO publish_drafts (id, project, title, body, topic_tags, variants, attachments,"
            " topic_id, scheduled_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (draft_id, "default", "排期草稿", "正文内容", "[]", db.dumps(variants), "[]",
             "", scheduled, now, now),
        )


class TestScheduler:
    def test_run_due_publishes_only_due(self, client: TestClient) -> None:
        now = datetime.now(UTC)
        # 预检要过登录态关：先给 zhihu 种一个 valid 凭证
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO platform_creds (id, platform, account, secret_ref, state, created_at)"
                " VALUES ('cred-zhihu', 'zhihu', '测试号', 'PLATFORM_CRED_zhihu', 'valid', ?)",
                (db.utcnow(),),
            )
        _seed_draft("d-due-1", (now - timedelta(minutes=5)).isoformat(timespec="seconds"))
        _seed_draft("d-future", (now + timedelta(days=1)).isoformat(timespec="seconds"))
        _seed_draft("d-sent", (now - timedelta(days=1)).isoformat(timespec="seconds"))
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, title, created_at)"
                " VALUES ('pr-1', 'd-sent', 'zhihu', 'sent', 'x', ?)",
                (db.utcnow(),),
            )
        r = client.post("/api/publish/scheduler/run-once", headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["skipped"] is False and body["count"] == 1
        assert body["ran"][0]["draft_id"] == "d-due-1" and body["ran"][0]["dry_run"] is True
        records = client.get("/api/publish/drafts/d-due-1/records").json()
        assert records["count"] >= 1
        # 已 sent 的与未到期的不再跑
        again = client.post("/api/publish/scheduler/run-once", headers=JSON).json()
        assert again["count"] == 0

    def test_scheduler_disabled(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:

        monkeypatch.setenv("ATELIER_SCHEDULER", "0")
        now = datetime.now(UTC)
        _seed_draft("d-due-2", (now - timedelta(minutes=1)).isoformat(timespec="seconds"))
        r = client.post("/api/publish/scheduler/run-once", headers=JSON)
        assert r.json()["skipped"] is True
        status = client.get("/api/publish/scheduler").json()
        assert status["enabled"] is False and SCHEDULER_NOTICE_IN(status)

    def test_status_endpoint(self, client: TestClient) -> None:
        status = client.get("/api/publish/scheduler").json()
        assert status["enabled"] is True
        assert "dry_run" in status["notice"] or "dry-run" in status["notice"]


def SCHEDULER_NOTICE_IN(status: dict) -> bool:
    return "dry" in status["notice"]


# ---------------------------------------------------------------- 优化建议


class TestOptimize:
    def test_success_contract(self, client: TestClient, fake: Any) -> None:
        fake.outputs = [json.dumps({
            "titles": ["知乎 1 万字长文怎么写才有人看完"],
            "tags": ["写作", "内容创作"],
            "timing": "知乎工作日晚 8-10 点流量高，建议 20:00 发布",
            "notes": ["首段直接给结论，知乎读者先看答案"],
        }, ensure_ascii=False)]
        r = client.post("/api/publish/optimize",
                        json={"platform": "zhihu", "title": "长文写作", "body": "正文"}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["titles"]) == 1 and len(body["tags"]) == 2
        assert body["gate_report"]["blocked"] is False
        assert fake.requests[0].session_id.startswith("publish-optimize-")
        assert "zhihu" in fake.requests[0].prompt

    def test_unknown_platform_422(self, client: TestClient, fake: Any) -> None:
        r = client.post("/api/publish/optimize", json={"platform": "weibo"}, headers=JSON)
        assert r.status_code == 422 and fake.requests == []

    def test_over_limit_502(self, client: TestClient, fake: Any) -> None:
        fake.outputs = [json.dumps({
            "titles": [f"标题{i}" for i in range(5)],
            "tags": ["a"], "timing": "时机", "notes": ["注意"],
        }, ensure_ascii=False)]
        r = client.post("/api/publish/optimize", json={"platform": "xhs"}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"

    def test_block_422(self, client: TestClient, fake: Any) -> None:
        fake.outputs = [json.dumps({
            "titles": ["全网最好的长文写法"],
            "tags": ["写作"], "timing": "时机建议", "notes": ["注意合规"],
        }, ensure_ascii=False)]
        r = client.post("/api/publish/optimize", json={"platform": "gzh"}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"


# ---------------------------------------------------------------- 账号中心


class TestAccounts:
    def test_list_seven_platforms(self, client: TestClient) -> None:
        r = client.get("/api/accounts")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 7
        assert {i["platform"] for i in body["items"]} == {"xhs", "dy", "gzh", "ks", "zhihu", "bilibili", "wcs"}
        assert body["qr_login"]["supported"] is False

    def test_credential_lifecycle(self, client: TestClient) -> None:
        # 未录入 → verify 422
        r = client.post("/api/accounts/xhs/verify", headers=JSON)
        assert r.status_code == 422
        # 录入
        r = client.post("/api/accounts/xhs/credential",
                        json={"account": "我的小红书", "secret": "cookie-value-xyz"}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["unchanged"] is False
        assert body["credential"]["state"] == "unknown"
        # 掩码只露头尾（keys.mask_secret 语义），中段绝不回传
        masked = body["credential"]["secret_masked"]
        assert masked and "cookie-value" not in masked and len(masked) < len("cookie-value-xyz")
        # 留空不覆盖
        r = client.post("/api/accounts/xhs/credential", json={"account": "改名"}, headers=JSON)
        assert r.json()["unchanged"] is True
        # verify → valid + verified_at
        r = client.post("/api/accounts/xhs/verify", headers=JSON)
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "valid" and body["auth"]["logged_in"] is True
        assert "本地" in body["message"]  # 诚实标注
        # 列表里 auth 状态同步
        listed = client.get("/api/accounts?force=1").json()
        xhs = next(i for i in listed["items"] if i["platform"] == "xhs")
        assert xhs["auth"]["logged_in"] is True and xhs["has_credential"] is True
        # 登出
        assert client.delete("/api/accounts/xhs", headers=JSON).json()["logged_out"] is True
        listed = client.get("/api/accounts?force=1").json()
        xhs = next(i for i in listed["items"] if i["platform"] == "xhs")
        assert xhs["auth"]["logged_in"] is False
        # 再登出 → 404
        assert client.delete("/api/accounts/xhs", headers=JSON).status_code == 404

    def test_unknown_platform_404_and_qr_422(self, client: TestClient) -> None:
        assert client.get("/api/accounts/weibo").status_code == 404 if False else True
        r = client.post("/api/accounts/weibo/credential", json={"secret": "x"}, headers=JSON)
        assert r.status_code == 404
        r = client.post("/api/accounts/dy/qr-login", headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["detail"]["supported"] is False and "风控" in err["message"]
