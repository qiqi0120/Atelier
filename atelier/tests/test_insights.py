"""SPEC-11 §6 · 分析域测试（M2-3a）。

四个即席 AI 工具统一走 conftest 的脚本化 fake harness（与 test_topics 同一套）。
诊断的「诚实模式」是重点：记录不足时**不调模型**（fake.requests 为空断言），
stats 由代码聚合（数字与库内一致），AI 只做解读。

合规门禁用「全网最好」触发 BLOCK（见 gates/compliance.py 的 _PATTERNS）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.main import create_app

if TYPE_CHECKING:
    from conftest import ScriptedHarness

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def client(atelier_root: Any) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


def _profile(client: TestClient, name: str = "测评画像") -> str:
    r = client.post("/api/profiles", json={"name": name, "platforms": ["xhs"]}, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_records(n: int, *, platform: str = "dy", days_ago: int = 3, title: str = "记录") -> None:
    """直接插 publish_records（诊断的原始数据；不发 dry-run 流程）。"""
    now = datetime.now(UTC)
    with db.db_session() as conn:
        for i in range(n):
            created = (now - timedelta(days=days_ago + i)).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO publish_records (id, draft_id, platform, status, title, created_at)"
                " VALUES (?, NULL, ?, 'published', ?, ?)",
                (f"pr-{platform}-{days_ago}-{i}", platform, f"{title} {i}", created),
            )


# --------------------------------------------------------------------------- competitor


class TestCompetitor:
    def test_short_text_rejected_before_model(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/analytics/competitor", json={"text": "太短了"}, headers=JSON)
        assert r.status_code == 422 and "分析不动" in r.json()["error"]["message"]
        assert fake.requests == []  # 参数层就拒了，不调模型（SPEC-11 §0 D6）

    def test_success_shape(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [json.dumps({
            "topics": ["平价通勤穿搭公式", "小个子显高穿搭"],
            "formats": ["三图一文", "口播+字幕"],
            "patterns": ["首图信息密度高", "结尾引导收藏"],
        }, ensure_ascii=False)]
        r = client.post("/api/analytics/competitor", json={"text": "这是一段足够长的竞品内容，" * 10}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["topics"]) == 2 and len(body["formats"]) == 2 and len(body["patterns"]) == 2
        assert body["gate_report"]["blocked"] is False
        assert fake.requests[0].session_id.startswith("insights-competitor-")

    def test_profile_injection(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        fake.outputs = [json.dumps({"topics": ["选题甲"], "formats": ["图文"], "patterns": ["结构紧凑"]}, ensure_ascii=False)]
        r = client.post("/api/analytics/competitor",
                        json={"text": "足够长的竞品原文内容，写满四十字以上才给分析。" * 3, "profile_id": pid},
                        headers=JSON)
        assert r.status_code == 200
        assert fake.requests[0].profile is not None and fake.requests[0].profile.id == pid

    def test_bad_output_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = ["我看着这段内容挺不错的，就不按 JSON 来了。"]
        r = client.post("/api/analytics/competitor", json={"text": "足够长的竞品原文内容。" * 10}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"
        # 数组越界（>6 条）同样违约
        fake.outputs = [json.dumps({"topics": [f"选题{i}" for i in range(7)], "formats": ["图文"], "patterns": ["x"]})]
        r = client.post("/api/analytics/competitor", json={"text": "足够长的竞品原文内容。" * 10}, headers=JSON)
        assert r.status_code == 502

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [json.dumps({
            "topics": ["全网最好的省钱攻略"], "formats": ["图文"], "patterns": ["首图冲击"],
        }, ensure_ascii=False)]
        r = client.post("/api/analytics/competitor", json={"text": "足够长的竞品原文内容。" * 10}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "GateBlocked"
        blocked = [i for i in err["detail"]["gate_items"] if i["severity"] == "block" and not i["passed"]]
        assert blocked and blocked[0]["gate"] == "compliance"


# --------------------------------------------------------------------------- strategy


STRATEGY_MD = """## 内容支柱架构
评测 40% + 教程 30% + 观点 30%。

## 受众路径
刷到 → 收藏 → 关注。

## 90 天节奏
第一个月打垂直，第二个月扩格式，第三个月做联动。

## KPI
涨粉 1000；完播率 30%；无数据回收渠道的指标先看收藏率替代。
"""


class TestStrategy:
    def test_success_sections(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [STRATEGY_MD]
        r = client.post("/api/analytics/strategy", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sections"] == {kw: True for kw in [
            "内容支柱", "受众路径", "90 天", "KPI",
        ]}
        assert body["markdown"].startswith("## 内容支柱架构")

    def test_missing_section_is_honest(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [STRATEGY_MD.replace("## KPI\n涨粉 1000；完播率 30%；无数据回收渠道的指标先看收藏率替代。\n", "")]
        r = client.post("/api/analytics/strategy", json={}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "InsightsIncomplete" and err["detail"]["missing"] == ["KPI"]

    def test_no_profile_means_general(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [STRATEGY_MD]
        client.post("/api/analytics/strategy", json={}, headers=JSON)
        assert fake.requests[0].profile is None
        assert "通用模式" in fake.requests[0].prompt
        assert fake.requests[0].session_id.startswith("insights-strategy-")

    def test_profile_not_found(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/analytics/strategy", json={"profile_id": "nope"}, headers=JSON)
        assert r.status_code == 404 and fake.requests == []


# --------------------------------------------------------------------------- audience


def _card_json() -> str:
    return json.dumps({
        "persona": "25-35 岁一线通勤党，内容行业新人",
        "pains": ["下班没时间研究穿搭"],
        "scenarios": ["地铁上刷短视频"],
        "preferences": ["直接给结论的清单体"],
        "notes": ["别用爹味说教"],
    }, ensure_ascii=False)


class TestAudience:
    def test_success_card(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [_card_json()]
        r = client.post("/api/analytics/audience", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        card = r.json()["card"]
        assert card["persona"].startswith("25-35 岁")
        for field in ("pains", "scenarios", "preferences", "notes"):
            assert len(card[field]) == 1

    def test_missing_persona_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [json.dumps({"pains": ["x"], "scenarios": [], "preferences": [], "notes": []})]
        r = client.post("/api/analytics/audience", json={}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"

    def test_general_mode_marked(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [json.dumps({"persona": "通用版：所有创作者", "pains": ["没灵感"],
                                    "scenarios": ["睡前刷手机"], "preferences": ["短平快"], "notes": ["别堆术语"]},
                                   ensure_ascii=False)]
        r = client.post("/api/analytics/audience", json={}, headers=JSON)
        assert r.status_code == 200
        assert fake.requests[0].profile is None
        assert fake.requests[0].session_id.startswith("insights-audience-")


# --------------------------------------------------------------------------- diagnose


class TestDiagnose:
    def test_insufficient_is_honest(self, client: TestClient, fake: ScriptedHarness) -> None:
        _seed_records(3)
        r = client.post("/api/analytics/diagnose", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is True
        assert body["need"] == 5 and "不编造分数" in body["message"]
        assert body["stats"]["records_total"] == 3
        assert fake.requests == []  # ★ 不调模型（SPEC-11 §0 D3，PLAN 硬要求）

    def test_diagnosis_uses_local_stats(self, client: TestClient, fake: ScriptedHarness) -> None:
        _seed_records(4, platform="dy")
        _seed_records(1, platform="xhs", days_ago=40)  # 40 天前，不计入近 30 天
        fake.outputs = [json.dumps({
            "findings": [
                {"dimension": "垂直度", "status": "good", "note": "5 条记录里 4 条抖音"},
                {"dimension": "定位清晰度", "status": "warn", "note": "标题主题分散"},
                {"dimension": "更新节奏", "status": "bad", "note": "近 30 天仅 4 条"},
                {"dimension": "平台覆盖", "status": "warn", "note": "双平台覆盖不均"},
            ],
            "advice": ["把周更固定到周三", "补一条小红书"],
        }, ensure_ascii=False)]
        r = client.post("/api/analytics/diagnose", json={}, headers=JSON)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["insufficient"] is False
        # stats 与库内一致（代码持有，D4）
        assert body["stats"]["records_total"] == 5
        assert body["stats"]["by_platform"] == {"dy": 4, "xhs": 1}
        assert body["stats"]["records_last_30d"] == 4
        assert len(body["findings"]) == 4
        assert "M5" in body["notice"]  # 限流/流量池如实标注依赖
        # prompt 里带了 stats 摘要（AI 只解读不自算）
        assert "records_total" in fake.requests[0].prompt
        assert fake.requests[0].session_id.startswith("insights-diagnose-")

    def test_bad_dimension_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        _seed_records(5)
        fake.outputs = [json.dumps({
            "findings": [{"dimension": "限流信号", "status": "bad", "note": "编造的"}],
            "advice": ["x"],
        }, ensure_ascii=False)]
        r = client.post("/api/analytics/diagnose", json={}, headers=JSON)
        assert r.status_code == 502 and "不在冻结的 4 维里" in r.json()["error"]["message"]

    def test_bad_status_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        _seed_records(5)
        fake.outputs = [json.dumps({
            "findings": [{"dimension": "垂直度", "status": "excellent", "note": "x"}],
            "advice": ["x"],
        }, ensure_ascii=False)]
        assert client.post("/api/analytics/diagnose", json={}, headers=JSON).status_code == 502

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        _seed_records(5)
        fake.outputs = [json.dumps({
            "findings": [
                {"dimension": "垂直度", "status": "good", "note": "全网最好的垂直度"},
                {"dimension": "定位清晰度", "status": "warn", "note": "定位待收敛"},
                {"dimension": "更新节奏", "status": "warn", "note": "节奏偏慢"},
                {"dimension": "平台覆盖", "status": "warn", "note": "覆盖单一"},
            ],
            "advice": ["继续"],
        }, ensure_ascii=False)]
        r = client.post("/api/analytics/diagnose", json={}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"
