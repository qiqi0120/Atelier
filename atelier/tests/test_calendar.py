"""SPEC-09 §8 · 日历域测试（M2-2 前半）。

CRUD / 月视图 / 提醒窗口 / 内置节点补种 全部确定性可测；suggest 走
conftest 的脚本化 fake harness（与 test_topics 同一套，不另写第二套），
断言「AI 输出解析 → 门禁 → 落池」与 TurnRequest 画像注入。

合规门禁用「全网最好」触发 BLOCK（见 gates/compliance.py 的 _PATTERNS）。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from atelier.server.calendar.service import local_today
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


def _mk_event(client: TestClient, **kw: Any) -> dict[str, Any]:
    body = {"title": kw.pop("title", "测试事件"), "date": kw.pop("date", "2026-10-15"),
            "kind": kw.pop("kind", "festival"), **kw}
    r = client.post("/api/calendar", json=body, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_topic(client: TestClient, **kw: Any) -> dict[str, Any]:
    r = client.post("/api/topics", json={"title": kw.pop("title", "测试选题"), **kw}, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()


def _profile(client: TestClient, name: str = "测评画像") -> str:
    r = client.post("/api/profiles", json={"name": name, "platforms": ["xhs"]}, headers=JSON)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _d(offset: int) -> str:
    """相对「今天」（北京时间，与 local_today 同口径）的 ISO 日期。"""
    return (local_today() + timedelta(days=offset)).isoformat()


# --------------------------------------------------------------------------- schema


class TestSchemaV4:
    def test_version_and_tables(self, client: TestClient) -> None:
        conn = db.get_conn()
        assert db.schema_version(conn) == db.SCHEMA_VERSION == 4
        assert "calendar_events" in db.table_names(conn)
        idx = {r[1] for r in conn.execute("PRAGMA index_list(calendar_events)").fetchall()}
        assert "idx_calendar_date" in idx
        # topics.due_date 由 _add_missing_columns 依 _EXPECTED 自动补（SPEC-09 §1）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(topics)").fetchall()}
        assert "due_date" in cols

    def test_migration_v3_to_v4(self, tmp_path: Path) -> None:
        """**真实的升级路径**：v3 库（topics 无 due_date、无 calendar_events）升 v4。"""
        legacy = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(legacy))
        conn.row_factory = sqlite3.Row
        try:
            db._apply_v1(conn)
            db._apply_v2(conn)
            db._apply_v3(conn)
            conn.execute("PRAGMA user_version=3")
            conn.commit()
            now = db.utcnow()
            conn.execute(
                "INSERT INTO topics (id, profile_id, title, angle, source, source_ref, status,"
                " decode, created_at, updated_at) VALUES ('t1', NULL, '老选题', '', 'manual',"
                " '', 'todo', NULL, ?, ?)",
                (now, now),
            )
            conn.commit()
            assert "calendar_events" not in db.table_names(conn), "前提：v3 库不该有这张表"

            applied = db.migrate(conn)
            assert "v4" in applied, applied
            assert "add_column:topics.due_date" in applied, applied
            assert db.schema_version(conn) == db.SCHEMA_VERSION
            assert "calendar_events" in db.table_names(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(topics)").fetchall()}
            assert "due_date" in cols
            # 老数据完整，新列可空
            row = conn.execute("SELECT * FROM topics WHERE id = 't1'").fetchone()
            assert row["title"] == "老选题" and row["due_date"] is None
        finally:
            conn.close()


# --------------------------------------------------------------------------- CRUD


class TestCrud:
    def test_create_get_patch_delete(self, client: TestClient) -> None:
        ev = _mk_event(client, title="双11 开箱选题节点", date="2026-11-11", kind="ecommerce",
                       note="带货向", remind_days=7)
        assert ev["source"] == "manual" and ev["end_date"] == ""
        got = client.get(f"/api/calendar/{ev['id']}", headers=JSON)
        # 没有 GET /{id} 端点：详情靠月视图带出（SPEC-09 §5），这里只断言 405/404 形状
        assert got.status_code in (404, 405)
        r = client.patch(f"/api/calendar/{ev['id']}", json={"title": "双11", "remind_days": 1}, headers=JSON)
        assert r.status_code == 200 and r.json()["title"] == "双11" and r.json()["remind_days"] == 1
        assert client.delete(f"/api/calendar/{ev['id']}", headers=JSON).json()["ok"] is True
        assert client.delete(f"/api/calendar/{ev['id']}", headers=JSON).status_code == 404

    def test_validation(self, client: TestClient) -> None:
        # kind 非法
        r = client.post("/api/calendar", json={"title": "x", "date": "2026-10-15", "kind": "party"}, headers=JSON)
        assert r.status_code == 422
        # date 非法：非零填充 / 纯垃圾
        for bad in ("2026-10-5", "不是日期", ""):
            r = client.post("/api/calendar", json={"title": "x", "date": bad, "kind": "festival"}, headers=JSON)
            assert r.status_code == 422, bad
        # end_date 早于 date
        r = client.post("/api/calendar", json={"title": "x", "date": "2026-10-15",
                                               "end_date": "2026-10-14", "kind": "platform"}, headers=JSON)
        assert r.status_code == 422
        # remind_days 越界（0..30）
        for bad in (-1, 31):
            r = client.post("/api/calendar", json={"title": "x", "date": "2026-10-15",
                                                   "kind": "festival", "remind_days": bad}, headers=JSON)
            assert r.status_code == 422
        # 标题空 / 超 80；备注超 200
        assert client.post("/api/calendar", json={"title": "  ", "date": "2026-10-15",
                                                  "kind": "festival"}, headers=JSON).status_code == 422
        assert client.post("/api/calendar", json={"title": "长" * 81, "date": "2026-10-15",
                                                  "kind": "festival"}, headers=JSON).status_code == 422
        assert client.post("/api/calendar", json={"title": "x", "date": "2026-10-15", "kind": "festival",
                                                  "note": "长" * 201}, headers=JSON).status_code == 422
        # PATCH 组合校验：把 end_date 改到 date 之前 → 422
        ev = _mk_event(client, date="2026-10-15", end_date="2026-10-20", kind="platform")
        r = client.patch(f"/api/calendar/{ev['id']}", json={"end_date": "2026-10-10"}, headers=JSON)
        assert r.status_code == 422
        # PATCH 清空 end_date（空串）合法
        r = client.patch(f"/api/calendar/{ev['id']}", json={"end_date": ""}, headers=JSON)
        assert r.status_code == 200 and r.json()["end_date"] == ""


# --------------------------------------------------------------------------- 月视图


class TestMonthView:
    def test_events_overlap_month(self, client: TestClient) -> None:
        _mk_event(client, title="单日事件", date="2026-10-15", kind="festival")
        _mk_event(client, title="跨月活动", date="2026-10-30", end_date="2026-11-02", kind="platform")
        oct_ = client.get("/api/calendar", params={"month": "2026-10"}, headers=JSON).json()
        assert [e["title"] for e in oct_["events"]] == ["单日事件", "跨月活动"]
        nov = client.get("/api/calendar", params={"month": "2026-11"}, headers=JSON).json()
        assert [e["title"] for e in nov["events"]] == ["跨月活动"]
        dec = client.get("/api/calendar", params={"month": "2026-12"}, headers=JSON).json()
        assert dec["events"] == []

    def test_topics_by_due_date(self, client: TestClient) -> None:
        _mk_topic(client, title="十月内的选题", source="calendar", due_date="2026-10-18")
        _mk_topic(client, title="十一月的选题", source="calendar", due_date="2026-11-01")
        _mk_topic(client, title="没日期的选题")
        oct_ = client.get("/api/calendar", params={"month": "2026-10"}, headers=JSON).json()
        assert [t["title"] for t in oct_["topics"]] == ["十月内的选题"]
        assert oct_["month"] == "2026-10"

    def test_month_format(self, client: TestClient) -> None:
        assert client.get("/api/calendar", params={"month": "2026-1"}, headers=JSON).status_code == 422
        assert client.get("/api/calendar", params={"month": "垃圾"}, headers=JSON).status_code == 422
        r = client.get("/api/calendar", headers=JSON)  # 缺省当月
        assert r.status_code == 200 and len(r.json()["month"]) == 7


# --------------------------------------------------------------------------- 提醒窗口


class TestUpcoming:
    def test_window_and_states(self, client: TestClient) -> None:
        _mk_event(client, title="明天", date=_d(1), kind="festival", remind_days=3)   # 激活
        _mk_event(client, title="五天后", date=_d(5), kind="festival", remind_days=3)  # 未进提醒期
        _mk_event(client, title="今天", date=_d(0), kind="ecommerce")                  # days_left=0
        _mk_event(client, title="昨天开始的活动", date=_d(-1), end_date=_d(1), kind="platform")
        _mk_event(client, title="窗外", date=_d(20), kind="industry")                  # days=14 之外

        body = client.get("/api/calendar/upcoming", params={"days": 14}, headers=JSON).json()
        by_title = {i["title"]: i for i in body["items"]}
        assert "窗外" not in by_title
        assert by_title["明天"]["remind_active"] is True and by_title["明天"]["days_left"] == 1
        assert by_title["今天"]["remind_active"] is True and by_title["今天"]["days_left"] == 0
        assert by_title["五天后"]["remind_active"] is False and by_title["五天后"]["days_left"] == 5
        ongoing = by_title["昨天开始的活动"]
        assert ongoing["days_left"] == -1 and ongoing["remind_active"] is True  # 进行中且在提醒期
        assert body["today"] == local_today().isoformat()
        # 按 date 升序
        dates = [i["date"] for i in body["items"]]
        assert dates == sorted(dates)

    def test_remind_boundary_is_activation_day(self, client: TestClient) -> None:
        """remind_days=N 的激活边界：today ≥ date - N 当天算激活（SPEC-09 §3）。"""
        _mk_event(client, title="边界", date=_d(3), kind="festival", remind_days=3)
        r = client.get("/api/calendar/upcoming", params={"days": 14}, headers=JSON).json()
        assert r["items"][0]["remind_active"] is True  # 今天正好是 date - 3
        _mk_event(client, title="差一天", date=_d(4), kind="festival", remind_days=3)
        r = client.get("/api/calendar/upcoming", params={"days": 14}, headers=JSON).json()
        by_title = {i["title"]: i for i in r["items"]}
        assert by_title["差一天"]["remind_active"] is False

    def test_days_validation(self, client: TestClient) -> None:
        for bad in (0, 32, -5):
            assert client.get("/api/calendar/upcoming", params={"days": bad}, headers=JSON).status_code == 422
        assert client.get("/api/calendar/upcoming", headers=JSON).status_code == 200  # 缺省 14


# --------------------------------------------------------------------------- 内置节点


class TestSeed:
    def test_seed_is_idempotent(self, client: TestClient) -> None:
        r1 = client.post("/api/calendar/seed", json={}, headers=JSON)
        assert r1.status_code == 200
        body = r1.json()
        assert body["added"] == 15 and body["skipped"] == 0  # 13 固定 + 母亲节 + 父亲节
        r2 = client.post("/api/calendar/seed", json={}, headers=JSON)
        assert r2.json() == {"year": body["year"], "added": 0, "skipped": 15}
        year = body["year"]
        kinds_nov = {e["kind"] for e in client.get(
            "/api/calendar", params={"month": f"{year}-11"}, headers=JSON).json()["events"]}
        assert kinds_nov == {"ecommerce"}  # 11 月只有双11
        kinds_oct = {e["kind"] for e in client.get(
            "/api/calendar", params={"month": f"{year}-10"}, headers=JSON).json()["events"]}
        assert kinds_oct == {"festival"}  # 国庆节 + 万圣夜

    def test_seed_computes_movable_days(self, client: TestClient) -> None:
        """母亲节/父亲节按年计算：2026 → 05-10 / 06-21；2027 → 05-09 / 06-20。"""
        client.post("/api/calendar/seed", json={"year": 2026}, headers=JSON)
        client.post("/api/calendar/seed", json={"year": 2027}, headers=JSON)
        may26 = client.get("/api/calendar", params={"month": "2026-05"}, headers=JSON).json()["events"]
        assert [e["date"] for e in may26 if e["title"] == "母亲节"] == ["2026-05-10"]
        jun26 = client.get("/api/calendar", params={"month": "2026-06"}, headers=JSON).json()["events"]
        assert [e["date"] for e in jun26 if e["title"] == "父亲节"] == ["2026-06-21"]
        may27 = client.get("/api/calendar", params={"month": "2027-05"}, headers=JSON).json()["events"]
        assert [e["date"] for e in may27 if e["title"] == "母亲节"] == ["2027-05-09"]
        jun27 = client.get("/api/calendar", params={"month": "2027-06"}, headers=JSON).json()["events"]
        assert [e["date"] for e in jun27 if e["title"] == "父亲节"] == ["2027-06-20"]

    def test_deleted_builtin_returns_on_reseed(self, client: TestClient) -> None:
        """删除内置条目后重新导入会带回——语义就是「重新导入」（SPEC-09 §0 D4）。"""
        year = client.post("/api/calendar/seed", json={}, headers=JSON).json()["year"]
        ev = next(e for e in client.get("/api/calendar",
                   params={"month": f"{year}-12"}, headers=JSON).json()["events"]
                  if e["title"] == "双12")
        assert client.delete(f"/api/calendar/{ev['id']}", headers=JSON).json()["ok"] is True
        r = client.post("/api/calendar/seed", json={}, headers=JSON).json()
        assert r["added"] == 1 and r["skipped"] == 14

    def test_year_validation(self, client: TestClient) -> None:
        assert client.post("/api/calendar/seed", json={"year": 1999}, headers=JSON).status_code == 422
        assert client.post("/api/calendar/seed", json={"year": 2101}, headers=JSON).status_code == 422


# --------------------------------------------------------------------------- suggest


def _suggest_json(items: list[dict[str, str]]) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


class TestSuggest:
    def test_suggest_lands_in_pool(self, client: TestClient, fake: ScriptedHarness) -> None:
        _mk_event(client, title="双11", date=_d(3), kind="ecommerce")
        fake.outputs = [_suggest_json([
            {"date": _d(3), "title": "双11 开箱：300 元内好物实测", "angle": "总价锚定", "event": "双11"},
            {"date": _d(8), "title": "不蹭节点也能拍的 3 个选题", "angle": "日常向", "event": ""},
        ])]
        r = client.post("/api/calendar/suggest", json={"days": 14}, headers=JSON)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["count"] == 2
        assert [t["due_date"] for t in body["items"]] == [_d(3), _d(8)]
        # 落池断言：source=calendar、source_ref=事件名、status=todo（SPEC-09 §0 D3）
        pool = client.get("/api/topics", headers=JSON).json()
        assert pool["total"] == 2
        first = next(t for t in pool["items"] if t["title"].startswith("双11"))
        assert first["source"] == "calendar" and first["source_ref"] == "双11"
        assert first["status"] == "todo"
        # prompt 里带了窗口内的节点（溯源到事件）
        assert "双11" in fake.requests[0].prompt

    def test_profile_injection_and_session_prefix(self, client: TestClient, fake: ScriptedHarness) -> None:
        pid = _profile(client)
        fake.outputs = [_suggest_json([
            {"date": _d(1), "title": "针对画像的一条选题", "angle": "贴合受众", "event": ""},
        ])]
        r = client.post("/api/calendar/suggest", json={"profile_id": pid}, headers=JSON)
        assert r.status_code == 201, r.text
        req = fake.requests[0]
        assert req.profile is not None and req.profile.id == pid
        assert req.session_id.startswith("calendar-suggest-")
        # 建议出的选题绑画像（SPEC-09 §0 D2）
        assert client.get("/api/topics", headers=JSON).json()["items"][0]["profile_id"] == pid

    def test_no_profile_means_general(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [_suggest_json([
            {"date": _d(1), "title": "通用建议", "angle": "", "event": ""},
        ])]
        assert client.post("/api/calendar/suggest", json={}, headers=JSON).status_code == 201
        assert fake.requests[0].profile is None

    def test_profile_not_found(self, client: TestClient, fake: ScriptedHarness) -> None:
        r = client.post("/api/calendar/suggest", json={"profile_id": "nope"}, headers=JSON)
        assert r.status_code == 404 and fake.requests == []

    def test_bad_output_is_502(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = ["我给你出几个主意吧，就不按 JSON 来了。"]
        r = client.post("/api/calendar/suggest", json={}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"
        # 日期越窗（窗口 14 天，日期给到 40 天后）
        fake.outputs = [_suggest_json([
            {"date": _d(40), "title": "越窗的建议", "angle": "", "event": ""},
        ])]
        r = client.post("/api/calendar/suggest", json={"days": 14}, headers=JSON)
        assert r.status_code == 502 and "超出窗口" in r.json()["error"]["message"]
        # 日期格式非法（模型违约，同样 502）
        fake.outputs = [_suggest_json([{"date": "10月1号", "title": "x", "angle": "", "event": ""}])]
        assert client.post("/api/calendar/suggest", json={}, headers=JSON).status_code == 502
        # 条数越界（>30）
        fake.outputs = [_suggest_json([
            {"date": _d(1), "title": f"建议 {i}", "angle": "", "event": ""} for i in range(31)
        ])]
        r = client.post("/api/calendar/suggest", json={}, headers=JSON)
        assert r.status_code == 502 and r.json()["error"]["code"] == "AIOutputInvalid"
        # 标题超 80 字
        fake.outputs = [_suggest_json([
            {"date": _d(1), "title": "长" * 81, "angle": "", "event": ""},
        ])]
        assert client.post("/api/calendar/suggest", json={}, headers=JSON).status_code == 502

    def test_days_validation(self, client: TestClient, fake: ScriptedHarness) -> None:
        for bad in (0, 32):
            r = client.post("/api/calendar/suggest", json={"days": bad}, headers=JSON)
            assert r.status_code == 422
        assert fake.requests == []  # 参数层就拒了，不调模型

    def test_compliance_block(self, client: TestClient, fake: ScriptedHarness) -> None:
        fake.outputs = [_suggest_json([
            {"date": _d(1), "title": "全网最好的省钱攻略", "angle": "极限词会触发 BLOCK", "event": ""},
        ])]
        r = client.post("/api/calendar/suggest", json={}, headers=JSON)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "GateBlocked"
        blocked = [i for i in err["detail"]["gate_items"]
                   if i["severity"] == "block" and not i["passed"]]
        assert blocked and blocked[0]["gate"] == "compliance"
        # 整批拒绝：池里什么都没有（不静默过滤，SPEC-09 §4）
        assert client.get("/api/topics", headers=JSON).json()["total"] == 0
