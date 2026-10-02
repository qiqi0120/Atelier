"""SPEC-15 §6 · 归因域测试（M5）。

诚实模式是重点：数据不足的端点**不调模型**（``fake.requests == []`` 断言），
stats / delta / ROI 全部代码算（数字与库内一致），AI 只做解读；
复盘沉淀必须在门禁之后写 ``memories``（source=复盘沉淀）。

合规门禁用「全网最好」触发 BLOCK（见 gates/compliance.py 的 _PATTERNS）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from atelier.cli import main as cli
from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.main import create_app

if TYPE_CHECKING:
    from conftest import ScriptedHarness

JSON = {"Content-Type": "application/json"}

LONG_COMMENTS = "这条视频讲得很细，求出后续；评论区想知道工具清单。" * 3


@pytest.fixture
def client(atelier_root: Any) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


def _profile(client: TestClient, name: str = "归因画像") -> str:
    r = client.post("/api/profiles", json={"name": name, "platforms": ["xhs"]}, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_record(*, platform: str = "dy", status: str = "published",
                 days_ago: int = 3, title: str = "记录", record_id: str = "") -> str:
    """直接插 publish_records（表现回收的挂载点；不走 dry-run 流程）。"""
    rid = record_id or f"pr-{platform}-{days_ago}-{title}-{record_id!r}"
    created = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO publish_records (id, draft_id, platform, status, title, created_at)"
            " VALUES (?, NULL, ?, ?, ?, ?)",
            (rid, platform, status, title, created),
        )
    return rid


def _snapshot(client: TestClient, *, platform: str, captured_at: str = "", followers: int = 0,
              likes_total: int = 0, works_total: int = 0) -> dict[str, Any]:
    r = client.post("/api/attribution/snapshots", headers=JSON, json={
        "platform": platform, "captured_at": captured_at,
        "followers": followers, "likes_total": likes_total, "works_total": works_total,
    })
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- schema


class TestSchemaV8:
    def test_fresh_db_has_attribution_tables(self, atelier_root: Any) -> None:
        db.init_db()
        names = set(db.table_names())
        for t in ("account_snapshots", "content_metrics", "roi_entries"):
            assert t in names
        assert db.schema_version() == 8

    def test_metric_cascade_deletes_with_record(self, atelier_root: Any) -> None:
        db.init_db()
        rid = _seed_record(record_id="pr-cascade")
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO content_metrics (id, record_id, platform, views, collected_at, created_at,"
                " updated_at) VALUES ('met-c1', ?, 'dy', 10, '2026-09-01', ?, ?)",
                (rid, db.utcnow(), db.utcnow()),
            )
        with db.db_session() as conn:
            conn.execute("DELETE FROM publish_records WHERE id = ?", (rid,))
        with db.db_session(commit=False) as conn:
            assert conn.execute("SELECT COUNT(*) FROM content_metrics").fetchone()[0] == 0


# --------------------------------------------------------------------------- snapshots + growth


class TestSnapshots:
    def test_create_and_list(self, client: TestClient) -> None:
        _snapshot(client, platform="xhs", captured_at="2026-09-01", followers=100)
        _snapshot(client, platform="xhs", captured_at="2026-09-08", followers=150)
        _snapshot(client, platform="dy", captured_at="2026-09-02", followers=7)
        body = client.get("/api/attribution/snapshots", headers=JSON).json()
        assert body["total"] == 3
        assert [i["captured_at"] for i in body["items"]] == ["2026-09-08", "2026-09-02", "2026-09-01"]
        only_xhs = client.get("/api/attribution/snapshots",
                              params={"platform": "xhs"}, headers=JSON).json()
        assert only_xhs["total"] == 2

    def test_captured_at_defaults_to_today_and_validates(self, client: TestClient) -> None:
        snap = _snapshot(client, platform="xhs")
        assert snap["captured_at"] == datetime.now(UTC).date().isoformat()
        for bad in ("2026-1-2", "not-a-date", "2026/09/01"):
            r = client.post("/api/attribution/snapshots", headers=JSON,
                            json={"platform": "xhs", "captured_at": bad})
            assert r.status_code == 422, bad

    def test_platform_required_and_counts_nonnegative(self, client: TestClient) -> None:
        assert client.post("/api/attribution/snapshots", headers=JSON,
                           json={"platform": " "}).status_code == 422
        r = client.post("/api/attribution/snapshots", headers=JSON,
                        json={"platform": "xhs", "followers": -5})
        assert r.status_code == 422 and "不能为负" in r.json()["error"]["message"]

    def test_delete(self, client: TestClient) -> None:
        snap = _snapshot(client, platform="xhs")
        assert client.delete(f"/api/attribution/snapshots/{snap['id']}").json()["ok"] is True
        assert client.delete(f"/api/attribution/snapshots/{snap['id']}").status_code == 404


class TestGrowth:
    def test_zero_snapshot_insufficient_without_model(
        self, client: TestClient, fake: ScriptedHarness
    ) -> None:
        r = client.get("/api/attribution/growth", params={"platform": "xhs"}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is True and body["need"] == 2 and body["have"] == 0
        assert "不编数字" in body["message"]
        assert fake.requests == []  # 代码相减，永远不调模型

    def test_one_snapshot_insufficient(self, client: TestClient, fake: ScriptedHarness) -> None:
        _snapshot(client, platform="xhs", captured_at="2026-09-01", followers=10)
        body = client.get("/api/attribution/growth",
                          params={"platform": "xhs"}, headers=JSON).json()
        assert body["insufficient"] is True and body["have"] == 1
        assert fake.requests == []

    def test_two_snapshots_delta(self, client: TestClient) -> None:
        _snapshot(client, platform="xhs", captured_at="2026-09-01",
                  followers=100, likes_total=1000, works_total=10)
        _snapshot(client, platform="xhs", captured_at="2026-09-08",
                  followers=160, likes_total=1500, works_total=13)
        body = client.get("/api/attribution/growth",
                          params={"platform": "xhs"}, headers=JSON).json()
        assert body["insufficient"] is False
        assert body["delta"] == {"followers": 60, "likes_total": 500, "works_total": 3}
        assert body["window_days"] == 7
        assert body["current"]["followers"] == 160 and body["previous"]["followers"] == 100

    def test_days_window_excludes_old_snapshots(self, client: TestClient) -> None:
        _snapshot(client, platform="dy", captured_at="2025-01-01", followers=1)
        _snapshot(client, platform="dy", captured_at=datetime.now(UTC).date().isoformat(),
                  followers=2)
        body = client.get("/api/attribution/growth",
                          params={"platform": "dy", "days": 30}, headers=JSON).json()
        assert body["insufficient"] is True  # 窗口外那条不算数
        assert client.get("/api/attribution/growth",
                          params={"platform": "dy"}, headers=JSON).json()["insufficient"] is False


# --------------------------------------------------------------------------- metrics (F-G31)


class TestMetrics:
    def test_record_must_exist(self, client: TestClient) -> None:
        r = client.post("/api/attribution/metrics", headers=JSON,
                        json={"record_id": "nope", "platform": "dy", "views": 10})
        assert r.status_code == 404 and r.json()["error"]["code"] == "NotFound"

    def test_platform_must_match_record(self, client: TestClient) -> None:
        rid = _seed_record(platform="dy", record_id="pr-m1")
        r = client.post("/api/attribution/metrics", headers=JSON,
                        json={"record_id": rid, "platform": "xhs", "views": 10})
        assert r.status_code == 422 and r.json()["error"]["detail"]["record_platform"] == "dy"
        ok = client.post("/api/attribution/metrics", headers=JSON,
                         json={"record_id": rid, "platform": "dy", "views": 100,
                               "likes": 12, "comments": 3, "shares": 2,
                               "collected_at": "2026-09-20"})
        assert ok.status_code == 201 and ok.json()["id"].startswith("met-")

    def test_negative_counts_rejected(self, client: TestClient) -> None:
        rid = _seed_record(platform="dy", record_id="pr-m2")
        r = client.post("/api/attribution/metrics", headers=JSON,
                        json={"record_id": rid, "platform": "dy", "views": -1})
        assert r.status_code == 422

    def test_list_with_aggregation(self, client: TestClient) -> None:
        rid = _seed_record(platform="dy", record_id="pr-m3")
        client.post("/api/attribution/metrics", headers=JSON,
                    json={"record_id": rid, "platform": "dy", "views": 100, "likes": 10,
                          "comments": 2, "shares": 1, "collected_at": "2026-09-20"})
        client.post("/api/attribution/metrics", headers=JSON,
                    json={"record_id": rid, "platform": "dy", "views": 300, "likes": 30,
                          "comments": 4, "shares": 3, "collected_at": "2026-09-25"})
        body = client.get("/api/attribution/metrics",
                          params={"platform": "dy"}, headers=JSON).json()
        assert body["total"] == 2
        assert body["agg"] == {"total_views": 400, "total_likes": 40, "total_comments": 6,
                               "total_shares": 4, "avg_views": 200.0}
        # 时间倒序 + days 过滤
        assert [i["collected_at"] for i in body["items"]] == ["2026-09-25", "2026-09-20"]
        short = client.get("/api/attribution/metrics",
                           params={"platform": "dy", "days": 2}, headers=JSON).json()
        assert short["total"] == 0 and short["agg"]["total_views"] == 0


# --------------------------------------------------------------------------- ROI (F-G34)


class TestRoi:
    def test_negative_rejected_and_both_zero_rejected(self, client: TestClient) -> None:
        r = client.post("/api/attribution/roi", headers=JSON, json={"hours": -1, "amount": 5})
        assert r.status_code == 422
        r = client.post("/api/attribution/roi", headers=JSON, json={"hours": 0, "amount": 0})
        assert r.status_code == 422 and "至少一项大于 0" in r.json()["error"]["message"]

    def test_create_and_summary(self, client: TestClient) -> None:
        r = client.post("/api/attribution/roi", headers=JSON,
                        json={"hours": 2.5, "amount": 40, "project": "穿搭选题"})
        assert r.status_code == 201 and r.json()["hours"] == 2.5
        rid = _seed_record(platform="dy", record_id="pr-roi")
        client.post("/api/attribution/metrics", headers=JSON,
                    json={"record_id": rid, "platform": "dy", "views": 5000, "likes": 300,
                          "collected_at": datetime.now(UTC).date().isoformat()})
        body = client.get("/api/attribution/roi/summary", headers=JSON).json()
        assert body["insufficient"] is False
        assert body["total_hours"] == 2.5 and body["total_amount"] == 40
        assert body["content_count"] == 1
        assert body["output"]["total_views"] == 5000 and body["output"]["total_likes"] == 300
        assert "2.5 小时" in body["roi_hint"] and "不构成收益推断" in body["roi_hint"]

    def test_summary_insufficient_without_entries(self, client: TestClient) -> None:
        body = client.get("/api/attribution/roi/summary", headers=JSON).json()
        assert body["insufficient"] is True and body["need"] == 1
        assert "不编产出比" in body["message"]


# --------------------------------------------------------------------------- 评论洞察 (F-G32)


def _comments_payload() -> dict[str, Any]:
    return {
        "themes": [
            {"theme": "想要工具清单", "count_hint": "约一半", "sample_quote": "求出工具清单"},
            {"theme": "夸讲解细", "count_hint": "多条", "sample_quote": "讲得很细"},
        ],
        "requests": ["出后续教程", "置顶工具清单"],
        "sentiment": {"positive": 5, "negative": 1, "neutral": 2},
    }


class TestCommentsInsight:
    def test_short_text_rejected_before_model(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/attribution/comments-insight", json={"text": "太短了"}, headers=JSON)
        err = r.json()["error"]
        assert r.status_code == 422 and "30 字" in err["message"]
        assert "不编结论" in (err["hint"] or "")
        assert fake.requests == []  # 语料不足不调模型

    def test_success_shape(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [json.dumps(_comments_payload(), ensure_ascii=False)]
        r = client.post("/api/attribution/comments-insight",
                        json={"text": LONG_COMMENTS}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["themes"]) == 2 and body["themes"][0]["count_hint"] == "约一半"
        assert body["sentiment"]["positive"] == 5
        assert "近似计数" in body["notice"]
        assert body["gate_report"]["blocked"] is False
        assert fake.requests[0].session_id.startswith("attribution-comments-insight-")
        # 诚实契约写进了 prompt：AI 不得虚构精确数字
        assert "不得虚构精确数字" in fake.requests[0].prompt

    def test_too_many_themes_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        payload = _comments_payload()
        payload["themes"] = [
            {"theme": f"主题{i}", "count_hint": "少量", "sample_quote": "原话"} for i in range(7)
        ]
        fake.outputs = [json.dumps(payload, ensure_ascii=False)]
        r = client.post("/api/attribution/comments-insight",
                        json={"text": LONG_COMMENTS}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"

    def test_non_json_output_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = ["我看这些评论都挺好的，就不按 JSON 来了。"]
        r = client.post("/api/attribution/comments-insight",
                        json={"text": LONG_COMMENTS}, headers=JSON)
        assert r.status_code == 502

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        payload = _comments_payload()
        payload["themes"][0]["sample_quote"] = "全网最好的工具清单"
        fake.outputs = [json.dumps(payload, ensure_ascii=False)]
        r = client.post("/api/attribution/comments-insight",
                        json={"text": LONG_COMMENTS}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"
        blocked = [i for i in r.json()["error"]["detail"]["gate_items"]
                   if i["severity"] == "block" and not i["passed"]]
        assert blocked and blocked[0]["gate"] == "compliance"

    def test_profile_injection(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        fake.outputs = [json.dumps(_comments_payload(), ensure_ascii=False)]
        r = client.post("/api/attribution/comments-insight",
                        json={"text": LONG_COMMENTS, "profile_id": pid}, headers=JSON)
        assert r.status_code == 200
        assert fake.requests[0].profile is not None and fake.requests[0].profile.id == pid


# --------------------------------------------------------------------------- 内容复盘 (F-G33)


REVIEW_MD = """## 有效结构
近 30 天 5 条记录里评测类表现最好。

## 受众偏好
观众偏好具体清单与步骤。

## 失效做法
数据不足以下判断。

## 下一步
固定周三更新；补一条小红书。
"""


class TestReview:
    def test_insufficient_is_honest(self, client: TestClient, fake: ScriptedHarness) -> None:
        _seed_record(platform="dy", record_id="pr-r1")
        _seed_record(platform="dy", record_id="pr-r2")
        r = client.post("/api/attribution/review", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is True
        assert body["need"] == 5 and "只解读真实记录" in body["message"]
        assert body["stats"]["records_total"] == 2
        assert fake.requests == []  # ★ 记录不足不调模型

    def test_success_uses_local_stats(self, client: TestClient, fake: ScriptedHarness) -> None:
        for i in range(5):
            _seed_record(platform="dy" if i < 4 else "xhs", record_id=f"pr-r3-{i}")
        fake.outputs = [REVIEW_MD]
        r = client.post("/api/attribution/review", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is False
        assert body["sections"] == {kw: True for kw in ("有效结构", "受众偏好", "失效做法", "下一步")}
        assert body["stats"]["records_total"] == 5
        assert body["stats"]["by_platform"] == {"dy": 4, "xhs": 1}
        assert body["profile_used"] is False and body["sedimented"] is False
        assert "未挂画像" in body["notice"]
        assert "records_total" in fake.requests[0].prompt  # stats 注入 prompt，AI 只解读
        assert "不要自己编数字" in fake.requests[0].prompt
        assert fake.requests[0].session_id.startswith("attribution-review-")

    def test_missing_section_is_422(self, client: TestClient, fake: ScriptedHarness) -> None:
        for i in range(5):
            _seed_record(platform="dy", record_id=f"pr-r4-{i}")
        fake.outputs = [REVIEW_MD.replace("## 下一步\n固定周三更新；补一条小红书。\n", "")]
        r = client.post("/api/attribution/review", json={}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "AttributionIncomplete" and err["detail"]["missing"] == ["下一步"]

    def test_sediment_writes_memory_after_gate(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        for i in range(5):
            _seed_record(platform="dy", record_id=f"pr-r5-{i}")
        fake.outputs = [REVIEW_MD]
        r = client.post("/api/attribution/review",
                        json={"profile_id": pid, "sediment": True}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sedimented"] is True and body["memory_id"].startswith("mem-")
        assert body["profile_used"] is True
        with db.db_session(commit=False) as conn:
            rows = conn.execute(
                "SELECT text, source FROM memories WHERE profile_id = ?", (pid,)
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["source"] == "复盘沉淀"
        # 沉淀的是「下一步」之前的要点
        assert "下一步" not in rows[0]["text"]
        assert "有效结构" in rows[0]["text"]

    def test_sediment_false_writes_nothing(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        for i in range(5):
            _seed_record(platform="dy", record_id=f"pr-r6-{i}")
        fake.outputs = [REVIEW_MD]
        r = client.post("/api/attribution/review", json={"profile_id": pid}, headers=JSON)
        assert r.status_code == 200 and r.json()["sedimented"] is False
        with db.db_session(commit=False) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM memories WHERE profile_id = ?", (pid,)
            ).fetchone()[0] == 0

    def test_gate_block_prevents_sediment(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        for i in range(5):
            _seed_record(platform="dy", record_id=f"pr-r7-{i}")
        fake.outputs = [REVIEW_MD.replace("近 30 天 5 条记录里评测类表现最好。",
                                          "全网最好的复盘结论。")]
        r = client.post("/api/attribution/review",
                        json={"profile_id": pid, "sediment": True}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"
        with db.db_session(commit=False) as conn:
            assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0

    def test_profile_not_found(self, client: TestClient, fake: ScriptedHarness) -> None:
        for i in range(5):
            _seed_record(platform="dy", record_id=f"pr-r8-{i}")
        r = client.post("/api/attribution/review", json={"profile_id": "nope"}, headers=JSON)
        assert r.status_code == 404 and fake.requests == []


# --------------------------------------------------------------------------- 爆款预测 (F-G35)


def _predict_payload(score: int = 76) -> str:
    return json.dumps({
        "score": score,
        "factors": [{"name": "钩子具体", "impact": "标题给了具体数字与场景"}],
        "verdict": "试试",
    }, ensure_ascii=False)


class TestPredict:
    def test_success_with_fixed_notice(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [_predict_payload()]
        r = client.post("/api/attribution/predict", headers=JSON,
                        json={"title": "3 天 2 晚青岛攻略", "body": "人均 800 的路线，第一天……",
                              "platform": "xhs"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["score"] == 76 and body["verdict"] == "试试"
        assert body["notice"] == ("预测是参考性质（P3），基于文本特征与通用经验，不保证实际表现")
        assert body["gate_report"]["blocked"] is False
        assert fake.requests[0].session_id.startswith("attribution-predict-")
        assert "青岛攻略" in fake.requests[0].prompt

    def test_missing_fields_rejected_before_model(
        self, client: TestClient, fake: ScriptedHarness
    ) -> None:
        r = client.post("/api/attribution/predict", headers=JSON,
                        json={"title": "", "body": "x", "platform": "xhs"})
        assert r.status_code == 422 and fake.requests == []

    def test_score_out_of_range_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [_predict_payload(score=101)]
        r = client.post("/api/attribution/predict", headers=JSON,
                        json={"title": "标题", "body": "正文内容", "platform": "xhs"})
        assert r.status_code == 502 and "0-100" in r.json()["error"]["message"]

    def test_bad_verdict_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [json.dumps({"score": 50, "factors": [
            {"name": "钩子", "impact": "一般"}], "verdict": "必爆"}, ensure_ascii=False)]
        r = client.post("/api/attribution/predict", headers=JSON,
                        json={"title": "标题", "body": "正文内容", "platform": "xhs"})
        assert r.status_code == 502 and "试试 / 改后发 / 放弃" in r.json()["error"]["message"]


# --------------------------------------------------------------------------- 策略建议 (F-G36)


STRATEGY_MD = """## 保持
评测类占总曝光 80%，继续保持。

## 调整
抖音平均互动偏低，试口播前置钩子。

## 停止
数据不足以下判断。
"""


class TestStrategy:
    def test_zero_data_insufficient_without_model(
        self, client: TestClient, fake: ScriptedHarness
    ) -> None:
        r = client.post("/api/attribution/strategy", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is True and body["need"] == 3
        assert "不空谈" in body["message"]
        assert fake.requests == []

    def test_success_with_history(self, client: TestClient, fake: ScriptedHarness) -> None:
        for i in range(3):
            rid = _seed_record(platform="dy", record_id=f"pr-s1-{i}")
            client.post("/api/attribution/metrics", headers=JSON,
                        json={"record_id": rid, "platform": "dy", "views": 100 + i,
                              "likes": 10, "collected_at": datetime.now(UTC).date().isoformat()})
        fake.outputs = [STRATEGY_MD]
        r = client.post("/api/attribution/strategy", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is False
        assert body["sections"] == {kw: True for kw in ("保持", "调整", "停止")}
        assert body["stats"]["best_platform_by_views"] == "dy"
        assert "best_platform_by_views" in fake.requests[0].prompt
        assert fake.requests[0].session_id.startswith("attribution-strategy-")

    def test_missing_section_is_422(self, client: TestClient, fake: ScriptedHarness) -> None:
        for i in range(3):
            _seed_record(platform="dy", record_id=f"pr-s2-{i}")
        fake.outputs = [STRATEGY_MD.replace("## 停止\n数据不足以下判断。\n", "")]
        r = client.post("/api/attribution/strategy", json={}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "AttributionIncomplete"
        assert r.json()["error"]["detail"]["missing"] == ["停止"]

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        for i in range(3):
            _seed_record(platform="dy", record_id=f"pr-s3-{i}")
        fake.outputs = [STRATEGY_MD.replace("评测类占总曝光 80%，继续保持。",
                                            "全网最好的策略就是继续。")]
        r = client.post("/api/attribution/strategy", json={}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"


# --------------------------------------------------------------------------- 工作台 / 看板


class TestWorkbenchSummary:
    def test_empty_db_all_zeros(self, client: TestClient) -> None:
        body = client.get("/api/attribution/workbench-summary", headers=JSON).json()
        assert body["topics"] == {"todo": 0, "doing": 0, "done": 0}
        assert body["drafts_pending"] == 0
        assert body["calendar_today"] == 0
        assert body["hot_pending"] == 0
        assert body["artifacts_last_7d"] == 0
        assert body["records_last_7d"] == {"sent": 0, "failed": 0}
        assert body["scheduler"]["enabled"] is True  # 直接来自 publish.scheduler.get_status()
        assert "interval_seconds" in body["scheduler"]

    def test_counts_come_from_real_data(self, client: TestClient) -> None:
        now = db.utcnow()
        today = datetime.now(UTC).date().isoformat()
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO topics (id, title, source, status, created_at, updated_at)"
                " VALUES ('t1', '选题一', 'manual', 'doing', ?, ?)", (now, now))
            conn.execute(
                "INSERT INTO topics (id, title, source, status, created_at, updated_at)"
                " VALUES ('t2', '选题二', 'manual', 'done', ?, ?)", (now, now))
            # 有排期且没发出去 → pending；已 sent 的不算
            conn.execute(
                "INSERT INTO publish_drafts (id, title, scheduled_date, created_at, updated_at)"
                " VALUES ('d1', '待发草稿', ?, ?, ?)", (today, now, now))
            conn.execute(
                "INSERT INTO publish_drafts (id, title, scheduled_date, created_at, updated_at)"
                " VALUES ('d2', '已发草稿', ?, ?, ?)", (today, now, now))
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, created_at)"
                " VALUES ('pr-w-sent', 'd2', 'dy', 'sent', ?)", (now,))
            conn.execute(
                "INSERT INTO calendar_events (id, title, date, kind, source, created_at, updated_at)"
                " VALUES ('c1', '今天的事', ?, 'deadline', 'manual', ?, ?)", (today, now, now))
            conn.execute(
                "INSERT INTO hot_entries (id, title, source, status, created_at, updated_at)"
                " VALUES ('h1', '热点', 'manual', 'pending', ?, ?)", (now, now))
            conn.execute(
                "INSERT INTO artifacts (id, project, zone, rel_path, created_at)"
                " VALUES ('a1', 'proj', '成品', 'proj/x.md', ?)", (now,))
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, created_at)"
                " VALUES ('pr-w-fail', NULL, 'dy', 'failed', ?)", (now,))
        body = client.get("/api/attribution/workbench-summary", headers=JSON).json()
        assert body["topics"] == {"todo": 0, "doing": 1, "done": 1}
        assert body["drafts_pending"] == 1  # d2 已 sent，不计入
        assert body["calendar_today"] == 1
        assert body["hot_pending"] == 1
        assert body["artifacts_last_7d"] == 1
        assert body["records_last_7d"] == {"sent": 1, "failed": 1}


class TestWorkbenchTodoItems:
    def test_empty_db_gives_empty_list(self, client: TestClient) -> None:
        body = client.get("/api/attribution/workbench-summary", headers=JSON).json()
        assert body["todo_items"] == []

    def test_seeded_items_content_order_and_routes(self, client: TestClient) -> None:
        now = db.utcnow()
        today = datetime.now(UTC).date().isoformat()
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
        with db.db_session() as conn:
            # 待发草稿 3 条：按 scheduled_date 升序；昨日排期且未发的排最前
            for did, sched, title in (
                ("td-a", yesterday, "昨日该发的"),
                ("td-b", today, "今天该发的"),
                ("td-c", tomorrow, "明天才发的"),
            ):
                conn.execute(
                    "INSERT INTO publish_drafts (id, title, scheduled_date, created_at, updated_at)"
                    " VALUES (?,?,?,?,?)", (did, title, sched, now, now))
            # 已 sent 的草稿不算待办
            conn.execute(
                "INSERT INTO publish_drafts (id, title, scheduled_date, created_at, updated_at)"
                " VALUES ('td-sent', '已发出', ?, ?, ?)", (yesterday, now, now))
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, created_at)"
                " VALUES ('pr-todo-sent', 'td-sent', 'dy', 'sent', ?)", (now,))
            # doing 选题 2 条：updated_at 新的在前；todo/done 不出现
            conn.execute(
                "INSERT INTO topics (id, title, source, status, created_at, updated_at)"
                " VALUES ('tt-new', '新动的选题', 'manual', 'doing', ?, ?)",
                (now, "2026-09-20T10:00:00+00:00"))
            conn.execute(
                "INSERT INTO topics (id, title, source, status, created_at, updated_at)"
                " VALUES ('tt-old', '先动的选题', 'manual', 'doing', ?, ?)",
                (now, "2026-09-19T10:00:00+00:00"))
            conn.execute(
                "INSERT INTO topics (id, title, source, status, created_at, updated_at)"
                " VALUES ('tt-done', '做完的', 'manual', 'done', ?, ?)", (now, now))
            # 今日日历事件：明天的不算
            conn.execute(
                "INSERT INTO calendar_events (id, title, date, kind, source, created_at, updated_at)"
                " VALUES ('tc-1', '周三截稿', ?, 'deadline', 'manual', ?, ?)", (today, now, now))
            conn.execute(
                "INSERT INTO calendar_events (id, title, date, kind, source, created_at, updated_at)"
                " VALUES ('tc-2', '明天的事', ?, 'deadline', 'manual', ?, ?)", (tomorrow, now, now))
            # 待处理热点：archived 的不算
            conn.execute(
                "INSERT INTO hot_entries (id, title, source, status, created_at, updated_at)"
                " VALUES ('th-1', '最新热点', 'manual', 'pending', ?, ?)", (now, now))
            conn.execute(
                "INSERT INTO hot_entries (id, title, source, status, created_at, updated_at)"
                " VALUES ('th-2', '旧热点', 'manual', 'pending', ?, ?)",
                ("2026-09-18T08:00:00+00:00", now))
            conn.execute(
                "INSERT INTO hot_entries (id, title, source, status, created_at, updated_at)"
                " VALUES ('th-3', '已归档', 'manual', 'archived', ?, ?)", (now, now))
        body = client.get("/api/attribution/workbench-summary", headers=JSON).json()
        assert body["todo_items"] == [
            {"kind": "draft", "title": "昨日该发的", "to": "/publish"},
            {"kind": "draft", "title": "今天该发的", "to": "/publish"},
            {"kind": "draft", "title": "明天才发的", "to": "/publish"},
            {"kind": "topic", "title": "新动的选题", "to": "/topics"},
            {"kind": "topic", "title": "先动的选题", "to": "/topics"},
            {"kind": "calendar", "title": "周三截稿", "to": "/calendar"},
            {"kind": "hot", "title": "旧热点", "to": "/hot"},
            {"kind": "hot", "title": "最新热点", "to": "/hot"},
        ]

    def test_each_kind_capped_at_three(self, client: TestClient) -> None:
        now = db.utcnow()
        with db.db_session() as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO hot_entries (id, title, source, status, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (f"th-cap-{i}", f"热点{i}", "manual", "pending",
                     f"2026-09-1{i}T08:00:00+00:00", now))
        body = client.get("/api/attribution/workbench-summary", headers=JSON).json()
        hots = [i for i in body["todo_items"] if i["kind"] == "hot"]
        assert len(hots) == 3  # created_at 最早的 3 条
        assert [i["title"] for i in hots] == ["热点0", "热点1", "热点2"]


class TestRecordsRecent:
    def test_recent_first_and_draft_title_join(self, client: TestClient) -> None:
        now = db.utcnow()
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO publish_drafts (id, title, created_at, updated_at)"
                " VALUES ('pd-join', '挂草稿的标题', ?, ?)", (now, now))
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, title, created_at)"
                " VALUES ('pr-new', 'pd-join', 'xhs', 'sent', '记录自带标题', ?)",
                ("2026-09-25T10:00:00+00:00",))
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, title, created_at)"
                " VALUES ('pr-old', NULL, 'dy', 'failed', NULL, ?)",
                ("2026-09-20T10:00:00+00:00",))
        body = client.get("/api/attribution/records-recent", headers=JSON).json()
        assert body["total"] == 2
        assert body["items"][0] == {
            "id": "pr-new", "platform": "xhs", "title": "记录自带标题",
            "created_at": "2026-09-25T10:00:00+00:00", "draft_title": "挂草稿的标题",
        }
        # 无草稿的记录 draft_title 为空串；title 缺省也是空串
        assert body["items"][1]["draft_title"] == ""
        assert body["items"][1]["title"] == ""

    def test_limit_20_newest_first(self, client: TestClient) -> None:
        for i in range(23):
            _seed_record(platform="dy", record_id=f"pr-lim-{i:02d}", days_ago=i)
        body = client.get("/api/attribution/records-recent", headers=JSON).json()
        assert body["total"] == 20
        assert body["items"][0]["id"] == "pr-lim-00"  # days_ago=0 最新
        assert {i["id"] for i in body["items"]} == {f"pr-lim-{j:02d}" for j in range(20)}

    def test_limit_validated(self, client: TestClient) -> None:
        assert client.get("/api/attribution/records-recent",
                          params={"limit": 0}, headers=JSON).status_code == 422
        assert client.get("/api/attribution/records-recent",
                          params={"limit": 101}, headers=JSON).status_code == 422


class TestDashboard:
    def test_empty_is_insufficient(self, client: TestClient) -> None:
        body = client.get("/api/attribution/dashboard", headers=JSON).json()
        assert body["insufficient"] is True and "只画真实录入" in body["message"]
        assert body["snapshots"] == [] and body["metrics_by_day"] == []

    def test_series_ascending_and_top_contents(self, client: TestClient) -> None:
        # 相对今天取日期（默认 30 天窗口内），故意乱序插入，断言按时间升序输出
        today = datetime.now(UTC).date()
        d_early, d_mid, d_late = (today - timedelta(days=20)).isoformat(), \
            (today - timedelta(days=12)).isoformat(), (today - timedelta(days=2)).isoformat()
        _snapshot(client, platform="xhs", captured_at=d_late, followers=200)
        _snapshot(client, platform="xhs", captured_at=d_early, followers=100)
        _snapshot(client, platform="dy", captured_at=d_mid, followers=9)
        rid = _seed_record(platform="xhs", title="爆款标题", record_id="pr-d1")
        rid2 = _seed_record(platform="xhs", title="平平标题", record_id="pr-d2")
        client.post("/api/attribution/metrics", headers=JSON,
                    json={"record_id": rid, "platform": "xhs", "views": 900, "likes": 90,
                          "collected_at": d_mid})
        client.post("/api/attribution/metrics", headers=JSON,
                    json={"record_id": rid2, "platform": "xhs", "views": 100, "likes": 5,
                          "collected_at": (today - timedelta(days=10)).isoformat()})
        body = client.get("/api/attribution/dashboard",
                          params={"platform": "xhs"}, headers=JSON).json()
        assert body["insufficient"] is False
        assert [s["captured_at"] for s in body["snapshots"]] == [d_early, d_late]
        assert [m["collected_at"] for m in body["metrics_by_day"]] == [
            d_mid, (today - timedelta(days=10)).isoformat()]
        assert body["top_contents"][0] == {"title": "爆款标题", "platform": "xhs",
                                           "views": 900, "likes": 90}
        assert len(body["top_contents"]) == 2
        # platform 过滤：dy 的快照不出现
        assert all(s["captured_at"] for s in body["snapshots"])

    def test_platform_filter_isolates(self, client: TestClient) -> None:
        _snapshot(client, platform="dy", captured_at="2026-09-05", followers=9)
        body = client.get("/api/attribution/dashboard",
                          params={"platform": "xhs"}, headers=JSON).json()
        assert body["insufficient"] is True  # xhs 没数据不能拿 dy 的凑数


# --------------------------------------------------------------------------- doctor / gateway（F-I5 / F-J6）


class TestDoctorLocalAgents:
    def test_check_passes_regardless_of_detection(self, atelier_root: Any) -> None:
        c = cli.check_local_agents()
        assert c.status == cli.OK  # 检测到与否都是合法状态
        assert c.value.strip()
        assert "harness registry 扩展" in c.hint

    def test_detected_names_listed(self, atelier_root: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli.shutil, "which",
                            lambda name: f"/usr/local/bin/{name}" if name in ("claude", "codex") else None)
        c = cli.check_local_agents()
        assert c.value == "claude, codex"
        monkeypatch.setattr(cli.shutil, "which", lambda name: None)
        assert cli.check_local_agents().value == "未检测到本机 agent CLI"


class TestGatewayCommand:
    def test_status_json_mock(self, atelier_root: Any, capsys: pytest.CaptureFixture) -> None:
        assert cli.main(["gateway", "status", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["harness"] == "mock"  # atelier_root 夹具设了 ATELIER_MOCK=1
        assert out["in_process"] is True
        assert "无独立 gateway 进程" in out["note"]
        assert "start/stop 不适用" in out["note"]

    def test_status_unconfigured_without_key(
        self, atelier_root: Any, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ATELIER_MOCK", "0")
        try:
            reload_settings()
            assert cli.main(["gateway", "status", "--json"]) == 0
            out = json.loads(capsys.readouterr().out)
            assert out["harness"] == "unconfigured"
        finally:
            monkeypatch.setenv("ATELIER_MOCK", "1")
            reload_settings()

    def test_status_claude_sdk_with_key_masks_it(
        self, atelier_root: Any, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-" + "A" * 40)
        monkeypatch.setenv("ATELIER_MOCK", "0")
        try:
            reload_settings()
            assert cli.main(["gateway", "status", "--json"]) == 0
            out = json.loads(capsys.readouterr().out)
            assert out["harness"] == "claude-sdk"
            masked = out["keys"]["anthropic_api_key"]
            assert masked and "A" * 40 not in masked  # 只回掩码，不回原文
        finally:
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
            monkeypatch.setenv("ATELIER_MOCK", "1")
            reload_settings()

    def test_start_stop_not_applicable(self, atelier_root: Any, capsys: pytest.CaptureFixture) -> None:
        for action in ("start", "stop"):
            assert cli.main(["gateway", action]) == 1
            out = capsys.readouterr().out
            assert "不适用" in out and "atelier web" in out

    def test_human_readable_status(self, atelier_root: Any, capsys: pytest.CaptureFixture) -> None:
        assert cli.main(["gateway"]) == 0
        out = capsys.readouterr().out
        assert "harness" in out and "atelier web" in out
