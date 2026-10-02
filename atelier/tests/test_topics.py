"""SPEC-08 §8 · 选题域测试（M2-1）。

四条 AI 任务（decode / score / matrix / hooks）统一走**脚本化 fake harness**
（同 test_chat 的模式）：真实模型不可测，mock 的写死文本又过不了结构化约定，
所以用可控输出的假 harness 断言「域服务对 harness 的用法」与「解析/门禁/落库」。

合规门禁用「全网最好」触发 BLOCK（见 gates/compliance.py 的 _PATTERNS）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.harness import registry as harness_registry
from atelier.server.harness.base import EventType, HealthReport, TurnEvent, TurnRequest
from atelier.server.main import create_app
from atelier.server.topics import score as score_mod
from atelier.server.topics.service import AI_GATES

JSON = {"Content-Type": "application/json"}


# --------------------------------------------------------------------------- fixtures


class ScriptedHarness:
    """按队列吐文本的假 harness。记录 TurnRequest，供断言画像注入与 prompt 拼装。"""

    name = "scripted"

    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs: list[str] = list(outputs or [])
        self.requests: list[TurnRequest] = []

    async def stream(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        self.requests.append(req)
        text = self.outputs.pop(0) if self.outputs else ""
        yield TurnEvent(EventType.TEXT_DELTA, req.turn_id, {"text": text})
        yield TurnEvent(EventType.DONE, req.turn_id, {"text": text, "provider": self.name})

    async def interrupt(self, turn_id: str) -> None:  # pragma: no cover - 本批用不到
        return None

    async def resume(self, turn_id: str) -> list[TurnEvent]:  # pragma: no cover
        return []

    async def health(self) -> HealthReport:
        return HealthReport(name=self.name, ok=True)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake() -> Iterator[ScriptedHarness]:
    h = ScriptedHarness()
    harness_registry.set_harness(h)
    yield h
    harness_registry.set_harness(None)


@pytest.fixture
def client(atelier_root: Any) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


def _mk_topic(client: TestClient, **kw: Any) -> dict[str, Any]:
    body = {"title": kw.pop("title", "测试选题"), **kw}
    r = client.post("/api/topics", json=body, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()


def _profile(client: TestClient, name: str = "测评画像") -> str:
    r = client.post("/api/profiles", json={"name": name, "platforms": ["xhs"]}, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()["id"]


#: 6 段齐全的拆解样例（注意别触发 compliance / secret_scan）
DECODE_MD = """## 概括
这是一篇 500 字的小红书图文笔记，主题是通勤穿搭，三图一文。

## 钩子
开头一句「打工人的 3 套通勤公式」让人停下来。

## 结构
反常识结论 → 3 套公式各配一张图 → 行动指令（收藏备用）。

## 为何火
结构性原因：选题高频、图片信息密度高；猜测：发布时间在早高峰前。

## 可复制模板
当 ⟨目标人群⟩ 需要 ⟨具体场景⟩ 时，给出 ⟨N 条公式⟩ + 每条一张图 + 收藏引导。

## 结合画像出选题
- 选题：小个子通勤包怎么选（角度：按身高给参数）
- 选题：300 元拿下全身通勤穿搭（角度：总价锚定）
"""


def _dims_json(total_target: int) -> str:
    """造一份 7 维 JSON，总和 = total_target（每维 1..5，风险维高分=低风险）。"""
    preset: dict[int, dict[str, int]] = {
        28: {"traffic": 4, "match": 4, "differentiation": 4, "timing": 4, "monetization": 4, "cost": 4, "risk": 4},
        22: {"traffic": 1, "match": 4, "differentiation": 4, "timing": 3, "monetization": 3, "cost": 4, "risk": 3},
        15: {"traffic": 1, "match": 1, "differentiation": 2, "timing": 3, "monetization": 2, "cost": 3, "risk": 3},
    }
    import json

    return json.dumps({"dims": preset[total_target], "reason": "流量潜力最突出，成本偏高是短板"})


# --------------------------------------------------------------------------- schema


class TestSchemaV3:
    def test_version_and_tables(self, client: TestClient) -> None:
        conn = db.get_conn()
        assert db.schema_version(conn) == 3
        names = set(db.table_names(conn))
        assert {"topics", "topic_scores"} <= names
        idx = {r[1] for r in conn.execute("PRAGMA index_list(topics)").fetchall()}
        assert "idx_topics_profile" in idx
        idx2 = {r[1] for r in conn.execute("PRAGMA index_list(topic_scores)").fetchall()}
        assert "idx_topic_scores_topic" in idx2

    def test_score_cascades_on_topic_delete(self, client: TestClient, fake: ScriptedHarness) -> None:
        tid = _mk_topic(client)["id"]
        fake.outputs = [_dims_json(28)]
        r = client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON)
        assert r.status_code == 201, r.text
        conn = db.get_conn()
        assert conn.execute("SELECT COUNT(*) FROM topic_scores").fetchone()[0] == 1
        client.delete(f"/api/topics/{tid}", headers=JSON)
        assert conn.execute("SELECT COUNT(*) FROM topic_scores").fetchone()[0] == 0


# --------------------------------------------------------------------------- CRUD


class TestCrud:
    def test_create_and_get(self, client: TestClient) -> None:
        t = _mk_topic(client, title="  秋天第一篇穿搭  ", angle="叠穿思路", source_ref="x")
        assert t["title"] == "秋天第一篇穿搭"  # strip
        assert t["status"] == "todo" and t["source"] == "manual"
        assert t["decode"] == "" and t["angle"] == "叠穿思路"
        got = client.get(f"/api/topics/{t['id']}").json()
        assert got["topic"]["id"] == t["id"] and got["score"] is None

    def test_validation(self, client: TestClient) -> None:
        assert client.post("/api/topics", json={"title": "   "}, headers=JSON).status_code == 422
        assert client.post("/api/topics", json={"title": "长" * 81}, headers=JSON).status_code == 422
        # SPEC-08 §0 D5：hot/calendar 来源本批不收
        r = client.post("/api/topics", json={"title": "x", "source": "hot"}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "ValidationError"
        # decode 正文只允许 source=decode 携带
        r = client.post("/api/topics", json={"title": "x", "source": "manual", "decode": "## 概括"}, headers=JSON)
        assert r.status_code == 422
        # 画像不存在 → 404
        assert client.post("/api/topics", json={"title": "x", "profile_id": "nope"}, headers=JSON).status_code == 404

    def test_list_filter_and_order(self, client: TestClient) -> None:
        _mk_topic(client, title="选题A")
        b = _mk_topic(client, title="选题B")
        _mk_topic(client, title="被搁置的预算选题", angle="省钱")
        # create 不收 status：改状态走 PATCH
        assert client.patch(f"/api/topics/{b['id']}", json={"status": "doing"}, headers=JSON).status_code == 200
        assert client.get("/api/topics").json()["total"] == 3
        assert client.get("/api/topics", params={"status": "doing"}).json()["total"] == 1
        assert client.get("/api/topics", params={"q": "预算"}).json()["total"] == 1
        assert client.get("/api/topics", params={"status": "bogus"}).status_code == 422

    def test_patch_and_delete(self, client: TestClient) -> None:
        t = _mk_topic(client, title="旧标题")
        r = client.patch(f"/api/topics/{t['id']}", json={"status": "done", "title": "新标题"}, headers=JSON)
        assert r.status_code == 200 and r.json()["status"] == "done"
        assert client.patch(f"/api/topics/{t['id']}", json={"status": "nope"}, headers=JSON).status_code == 422
        assert client.delete(f"/api/topics/{t['id']}", headers=JSON).json()["ok"] is True
        assert client.get(f"/api/topics/{t['id']}").status_code == 404
        assert client.delete(f"/api/topics/{t['id']}", headers=JSON).status_code == 404


# --------------------------------------------------------------------------- decode


class TestDecode:
    def test_success_and_manual_save(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [DECODE_MD]
        r = client.post(
            "/api/topics/decode",
            json={"text": "打工人的 3 套通勤公式，赞 3.2w 藏 1.1w 评 876，评论区都在要链接。" * 2},
            headers=JSON,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sections"] == {kw: True for kw in decode_sections()}
        assert body["gate_report"]["blocked"] is False
        assert body["topic_seed"]["title"].startswith("打工人的 3 套通勤公式")
        # 拆解不落库：池仍然为空；一键保存走 POST /topics（PRD §8.1 验收 2）
        assert client.get("/api/topics").json()["total"] == 0
        save = client.post(
            "/api/topics",
            json={"title": "通勤公式拆解选题", "source": "decode",
                  "source_ref": body["topic_seed"]["title"], "decode": body["decode_markdown"]},
            headers=JSON,
        )
        assert save.status_code == 201 and save.json()["decode"].startswith("## 概括")

    def test_missing_section_is_honest(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [DECODE_MD.replace("## 钩子\n开头一句「打工人的 3 套通勤公式」让人停下来。\n\n", "")]
        r = client.post("/api/topics/decode", json={"text": "一段足够长的原文内容" * 10}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "DecodeIncomplete" and err["detail"]["missing"] == ["钩子"]

    def test_too_short_text(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/topics/decode", json={"text": "太短了"}, headers=JSON)
        assert r.status_code == 422 and "拆不动" in r.json()["error"]["message"]
        assert fake.requests == []  # 参数层就拒了，不调模型

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [DECODE_MD + "\n这篇是全网最好的通勤内容。"]  # 极限词 → BLOCK
        r = client.post("/api/topics/decode", json={"text": "足够长的原文，内容随便写点什么都行。" * 6}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "GateBlocked"
        blocked_items = [i for i in err["detail"]["gate_items"]
                         if i["severity"] == "block" and not i["passed"]]
        assert blocked_items and blocked_items[0]["gate"] == "compliance"

    def test_profile_injection(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        fake.outputs = [DECODE_MD]
        r = client.post(
            "/api/topics/decode", json={"text": "足够长的原文内容，写满四十字以上才给拆。" * 3,
                                        "profile_id": pid},
            headers=JSON,
        )
        assert r.status_code == 200
        req = fake.requests[0]
        assert req.profile is not None and req.profile.id == pid
        assert "结合注入的创作者画像" in req.prompt
        assert req.session_id.startswith("topics-decode-")

    def test_no_profile_means_general_mode(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [DECODE_MD]
        client.post("/api/topics/decode", json={"text": "足够长的原文内容，写满四十字以上才给拆。" * 3},
                    headers=JSON)
        req = fake.requests[0]
        assert req.profile is None
        assert "通用模式" in req.prompt


def decode_sections() -> list[str]:
    from atelier.server.topics.decode import DECODE_SECTIONS

    return list(DECODE_SECTIONS)


# --------------------------------------------------------------------------- score


class TestScore:
    def _mk(self, client: TestClient) -> str:
        return _mk_topic(client, title="适老料理账号的第一条选题")["id"]

    def test_verdict_do(self, client: TestClient, fake: ScriptedHarness) -> None:
        tid = self._mk(client)
        fake.outputs = [_dims_json(28)]
        r = client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["verdict"] == "do" and body["total"] == 28
        assert set(body["dims"]) == set(score_mod.DIMENSIONS)
        got = client.get(f"/api/topics/{tid}").json()
        assert got["score"]["verdict"] == "do"  # 历史可回读

    def test_verdict_thresholds_are_code_owned(self) -> None:
        assert score_mod.verdict_for(27) == "do"
        assert score_mod.verdict_for(26) == "pivot"
        assert score_mod.verdict_for(19) == "pivot"
        assert score_mod.verdict_for(18) == "dont"
        assert score_mod.verdict_for(7) == "dont"

    def test_verdict_pivot_and_dont(self, client: TestClient, fake: ScriptedHarness) -> None:
        tid = self._mk(client)
        fake.outputs = [_dims_json(22), _dims_json(15)]
        r1 = client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON)
        r2 = client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON)
        assert r1.json()["verdict"] == "pivot" and r2.json()["verdict"] == "dont"
        # 追加式历史：最新一条胜出（SPEC-08 §3）
        got = client.get(f"/api/topics/{tid}").json()
        assert got["score"]["total"] == 15

    def test_bad_output_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        tid = self._mk(client)
        fake.outputs = ["我觉得这个选题不错，就不过 JSON 了。"]
        r = client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"
        # 维度越界同样违约
        fake.outputs = [
            (
                '{"dims": {"traffic": 9, "match": 4, "differentiation": 3, "timing": 4,'
                ' "monetization": 3, "cost": 4, "risk": 4}, "reason": "x"}'
            )
        ]
        assert client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON).status_code == 502
        # 缺维度
        fake.outputs = ['{"dims": {"traffic": 4}, "reason": "x"}']
        assert client.post("/api/topics/score", json={"topic_id": tid}, headers=JSON).status_code == 502

    def test_topic_not_found(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/topics/score", json={"topic_id": "topic-none"}, headers=JSON)
        assert r.status_code == 404 and fake.requests == []


# --------------------------------------------------------------------------- matrix


class TestMatrix:
    MATRIX_JSON = (
        '{"items": ['
        '{"pillar": "通勤穿搭", "format": "图文", "title": "3 套通勤公式，小个子直接抄", "angle": "按身高给参数"},'
        '{"pillar": "通勤穿搭", "format": "视频", "title": "跟拍我的一分钟通勤出门流程", "angle": "流程实拍"},'
        '{"pillar": "平价好物", "format": "图文", "title": "300 元拿下全身通勤穿搭", "angle": "总价锚定"},'
        '{"pillar": "平价好物", "format": "视频", "title": "平价通勤包开箱：两只都不到 150", "angle": "价格锚点"}'
        ']}'
    )

    def test_matrix_persists_pool(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [self.MATRIX_JSON]
        r = client.post(
            "/api/topics/matrix",
            json={"pillars": ["通勤穿搭", "平价好物"], "formats": ["图文", "视频"], "per_combo": 1},
            headers=JSON,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["count"] == 4
        assert all(t["source"] == "matrix" and t["status"] == "todo" for t in body["items"])
        assert body["items"][0]["source_ref"] == "通勤穿搭×图文"
        assert client.get("/api/topics").json()["total"] == 4

    def test_combo_cap_rejects_before_model(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post(
            "/api/topics/matrix",
            json={"pillars": ["p"] * 6, "formats": ["f"] * 6, "per_combo": 2},
            headers=JSON,
        )
        assert r.status_code == 422 and "60" in r.json()["error"]["message"]
        assert fake.requests == []  # 参数层拒绝，不花模型钱

    def test_per_combo_range(self, client: TestClient, fake: ScriptedHarness) -> None:
        assert client.post(
            "/api/topics/matrix",
            json={"pillars": ["p"], "formats": ["f"], "per_combo": 4},
            headers=JSON,
        ).status_code == 422

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        bad = self.MATRIX_JSON.replace("3 套通勤公式，小个子直接抄", "全网最好的通勤公式")
        fake.outputs = [bad]
        r = client.post(
            "/api/topics/matrix",
            json={"pillars": ["通勤"], "formats": ["图文"], "per_combo": 1},
            headers=JSON,
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"
        # 被拒的整批不入库（不静默过滤）
        assert client.get("/api/topics").json()["total"] == 0

    def test_bad_output_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = ["这里没有 JSON"]
        r = client.post(
            "/api/topics/matrix", json={"pillars": ["p"], "formats": ["f"]}, headers=JSON
        )
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"


# --------------------------------------------------------------------------- hooks


class TestHooks:
    HOOKS_JSON = (
        '{"variants": ['
        '{"text": "打工人的通勤公式，3 套就够了"},'
        '{"text": "谁说通勤穿搭一定贵"},'
        '{"text": "第一次写穿搭，我总结了 3 条铁律"}'
        ']}'
    )

    def test_variants_checked_against_dy_default(self, client: TestClient, fake: ScriptedHarness) -> None:
        from atelier.server.gates.wordcount import count_platform_chars

        long_text = "这条钩子特别长" * 12  # 84 个汉字 → 超 55
        fake.outputs = [self.HOOKS_JSON.replace(
            '{"text": "第一次写穿搭，我总结了 3 条铁律"}', f'{{"text": "{long_text}"}}'
        )]
        r = client.post("/api/topics/hooks", json={"title": "通勤穿搭选题"}, headers=JSON)
        assert r.status_code == 200, r.text
        variants = r.json()["variants"]
        assert len(variants) == 3
        assert all(v["limit"] == 55 for v in variants)  # 缺省按抖音标题从严（SPEC-08 §4）
        for v in variants:
            assert v["chars"] == count_platform_chars(v["text"])
            assert v["passed"] == (v["chars"] <= 55)
        assert variants[2]["passed"] is False  # 超长的那条如实标 FAIL

    def test_known_and_unknown_platform(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [self.HOOKS_JSON]
        r = client.post(
            "/api/topics/hooks", json={"title": "通勤穿搭", "platform": "gzh"}, headers=JSON
        )
        assert r.status_code == 200 and all(v["limit"] == 20000 for v in r.json()["variants"])
        r = client.post(
            "/api/topics/hooks", json={"title": "通勤穿搭", "platform": "bilibili"}, headers=JSON
        )
        assert r.status_code == 422

    def test_topic_source(self, client: TestClient, fake: ScriptedHarness) -> None:
        tid = _mk_topic(client, title="来自池里的选题", angle="叠穿")["id"]
        fake.outputs = [self.HOOKS_JSON]
        r = client.post("/api/topics/hooks", json={"topic_id": tid}, headers=JSON)
        assert r.status_code == 200
        req = fake.requests[0]
        assert "来自池里的选题" in req.prompt and "叠穿" in req.prompt

    def test_requires_title_or_topic(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/topics/hooks", json={}, headers=JSON)
        assert r.status_code == 422 and fake.requests == []

    def test_variant_count_violation(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = ['{"variants": [{"text": "只有两条"}, {"text": "不行"}]}']
        r = client.post("/api/topics/hooks", json={"title": "通勤穿搭"}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [self.HOOKS_JSON.replace("谁说通勤穿搭一定贵", "全网最好的通勤穿搭")]
        r = client.post("/api/topics/hooks", json={"title": "通勤穿搭"}, headers=JSON)
        assert r.status_code == 422 and r.json()["error"]["code"] == "GateBlocked"


# --------------------------------------------------------------------------- 门禁口径


def test_ai_gates_match_spec() -> None:
    """SPEC-08 §4 冻结：AI 产出统一跑 compliance + secret_scan + ai_flavor。"""
    assert tuple(sorted(AI_GATES)) == ("ai_flavor", "compliance", "secret_scan")
