"""技能运行记录落库（``skill_runs``）测试 —— M1 收尾欠账①的验收。

**这个文件要证明的一件事**：M1 之前运行记录只存进程内字典，重启即丢。
所以核心断言全部围绕「**清掉内存缓存后仍查得到**」——这等价于一次进程重启。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atelier.server import paths
from atelier.server.core import db
from atelier.server.main import create_app
from atelier.server.skills import store
from atelier.server.skills.loader import clear_cache
from atelier.server.skills.runner import RunResult

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """产物与元数据库重定向到 tmp，**但技能目录保持真实仓库**。

    ``paths.SKILLS`` 与 ``paths.VAR_DB`` 都从 ``ROOT`` 派生，``atelier_root`` 那种
    「整体换根」的做法会让 loader 在 tmp 里找不到技能。这里逐个改派生量，把
    ``SKILLS`` 排除在外，于是既能跑真技能、又不写脏仓库。
    """
    real_skills = paths.SKILLS
    root = tmp_path / "root"
    for attr, value in (
        ("ROOT", root),
        ("OUTPUTS", root / "outputs"),
        ("PROFILES", root / "profiles"),
        ("VAR", root / "var"),
        ("VAR_DB", root / "var" / "atelier.db"),
        ("SESSIONS", root / "var" / "sessions"),
        ("SKILLS", real_skills),
    ):
        monkeypatch.setattr(paths, attr, value, raising=False)
    paths.ensure_dirs()
    db.reset_conn()
    db.init_db()
    clear_cache()
    yield root
    db.reset_conn()
    clear_cache()


@pytest.fixture
def client(env: Path) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """每个用例前后清空 API 层的在途缓存，模拟「干净的进程」。"""
    from atelier.server.api import capability

    capability._RUNS.clear()
    yield
    capability._RUNS.clear()


def _run_card(client: TestClient, project: str = "runstest") -> dict:
    body = ("第一件事，先把定位写清楚。\n第二件事，连续发 7 条同一主题。\n"
            "第三件事，看后台哪条数据最好。\n第四件事，复刻那条的结构。\n第五件事，改成自己的话。")
    resp = client.post(
        "/api/skills/xhs-card/run",
        json={"params": {"title": "新手做号第一周", "body": body, "count": 3},
              "project": project, "wait": True},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- 迁移


def test_migration_v1_to_v2_adds_skill_runs(tmp_path: Path) -> None:
    """**真实的升级路径**：老库只有 v1 的 9 张表，migrate 后必须补出 skill_runs。

    不能只测「全新库建 10 张表」——那不证明老用户的数据库能升上去。
    """
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(legacy))
    conn.row_factory = sqlite3.Row
    try:
        db._apply_v1(conn)                      # 只建 v1 的 9 张表
        conn.execute("PRAGMA user_version=1")
        conn.commit()
        assert "skill_runs" not in db.table_names(conn), "前提：v1 库不该有这张表"
        assert len(db.table_names(conn)) == 9

        applied = db.migrate(conn)
        assert "v2" in applied, applied
        # migrate 一路升到当前最新版本（v3+），v2 这步本身必须发生
        assert db.schema_version(conn) == db.SCHEMA_VERSION
        assert "skill_runs" in db.table_names(conn)
        # v1 的 9 张 + v2 的 skill_runs + v3 的 topics/topic_scores + v4 的 calendar_events
        assert len(db.table_names(conn)) == 18  # v6 起含发现域 5 张表（SPEC-12）

        # 老数据没被动过
        assert len(conn.execute("SELECT * FROM settings").fetchall()) == 0
        # 索引也建了
        idx = {r[1] for r in conn.execute("PRAGMA index_list(skill_runs)").fetchall()}
        assert "idx_skill_runs_skill" in idx, idx
    finally:
        conn.close()


def test_migration_is_idempotent_at_latest(env: Path) -> None:
    conn = db.init_db()
    assert db.migrate(conn) == []
    assert db.schema_version(conn) == db.SCHEMA_VERSION


# ---------------------------------------------------------------- 落库读库


def test_start_then_finish_roundtrip(env: Path) -> None:
    store.start_run("r1", "xhs-card", project="p1", profile_id="prof1", params={"count": 3})
    row = store.get_run("r1")
    assert row is not None
    assert row["status"] == "running"
    assert row["params"] == {"count": 3}, "入参必须原样留档"

    done = RunResult(run_id="r1", skill_id="xhs-card", status="done", project="p1",
                     result_markdown="正文", artifacts=[{"path": "outputs/p1/a.svg"}],
                     duration=1.2345, cost_actual=0.0)
    store.finish_run(done, profile_id="prof1")

    row = store.get_run("r1")
    assert row["status"] == "done"
    assert row["result_markdown"] == "正文"
    assert row["artifacts"] == [{"path": "outputs/p1/a.svg"}], "JSON 字段必须往返成对象"
    assert row["params"] == {"count": 3}, "回写终态不能把入参冲掉"
    assert row["profile_id"] == "prof1"
    assert row["duration"] == 1.234 or row["duration"] == 1.235


def test_finish_run_without_start_still_records(env: Path) -> None:
    """``wait=True`` 同步路径不会先 start_run，finish_run 必须能补插。"""
    store.finish_run(RunResult(run_id="r9", skill_id="xhs-card", status="done", project="p9"))
    row = store.get_run("r9")
    assert row is not None and row["status"] == "done"
    assert row["project"] == "p9"


def test_get_run_missing_returns_none(env: Path) -> None:
    assert store.get_run("nope") is None


def test_list_runs_filters_and_orders(env: Path) -> None:
    for i, (sid, proj, status) in enumerate([
        ("xhs-card", "alpha", "done"), ("xhs-card", "alpha", "failed"),
        ("de-ai", "beta", "done"),
    ]):
        rid = f"r{i}"
        store.start_run(rid, sid, project=proj)
        store.finish_run(RunResult(run_id=rid, skill_id=sid, status=status, project=proj))

    assert len(store.list_runs()) == 3
    assert len(store.list_runs(skill_id="xhs-card")) == 2
    assert len(store.list_runs(project="alpha")) == 2
    assert len(store.list_runs(status="failed")) == 1
    assert [r["status"] for r in store.list_runs(skill_id="xhs-card")] == ["failed", "done"], "应按时间倒序"
    assert store.list_runs(limit=1) and len(store.list_runs(limit=1)) == 1
    # 非法 limit 夹到 [1,200]，不报错也不给无限行
    assert len(store.list_runs(limit=0)) >= 1
    assert len(store.list_runs(limit=99999)) == 3


# ---------------------------------------------------------------- API 层


def test_api_run_survives_process_restart(client: TestClient) -> None:
    """**核心断言**：跑完 → 清空内存缓存（= 重启）→ 仍查得到完整记录。"""
    data = _run_card(client)
    run_id = data["run_id"]
    assert data["status"] == "done"
    assert data["artifacts"], "xhs-card 应产出文件"

    from atelier.server.api import capability

    capability._RUNS.clear()  # ← 等价于进程重启

    got = client.get(f"/api/skills/runs/{run_id}").json()
    assert got["status"] == "done", f"重启后查不到记录：{got}"
    assert got["run_id"] == run_id
    assert got["artifacts"], "重启后产物索引应还在"
    assert got["result_markdown"]
    assert got.get("created_at"), "落库才有时间戳"


def test_api_unknown_run_still_reports_unknown(client: TestClient) -> None:
    got = client.get("/api/skills/runs/does-not-exist").json()
    assert got["status"] == "unknown"
    assert got["error"]["code"] == "NotFound"


def test_api_list_runs_endpoint(client: TestClient) -> None:
    _run_card(client, project="alpha")
    _run_card(client, project="beta")

    body = client.get("/api/skills/runs").json()
    assert len(body["runs"]) == 2
    assert {r["project"] for r in body["runs"]} == {"alpha", "beta"}

    only = client.get("/api/skills/runs", params={"project": "alpha"}).json()
    assert len(only["runs"]) == 1 and only["runs"][0]["project"] == "alpha"

    by_skill = client.get("/api/skills/runs", params={"skill_id": "xhs-card"}).json()
    assert len(by_skill["runs"]) == 2
    assert client.get("/api/skills/runs", params={"limit": 1}).json()["runs"].__len__() == 1


def test_api_paid_cost_pending_is_recorded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """付费待确认也是一次「运行」，要留痕（否则用户点了取消就查不到发生了什么）。"""
    from atelier.server.api import capability

    monkeypatch.setenv("MINIMAX_API_KEY", "sk-fake-for-test")
    capability._RUNS.clear()

    resp = client.post("/api/skills/one-video/run",
                       json={"params": {"topic": "选题", "duration": 30},
                             "project": "paidproj", "wait": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cost_pending"

    capability._RUNS.clear()
    got = client.get(f"/api/skills/runs/{resp.json()['run_id']}").json()
    assert got["status"] == "cost_pending"
    assert got["cost_actual"] == 0.0, "未确认费用不得计费"
    assert got["cost_estimate"]["requires_confirm"] is True


def test_api_failed_run_is_recorded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """跑挂了也要留痕，否则失败原因随进程一起消失。

    走**异步分支**（``wait=False``，生产路径）：``_job`` 里 catch 住异常并回写 failed。
    同步分支（``wait=True``）是把异常抛给调用方的，属既有行为，不在这里断言。
    """
    import time

    from atelier.server.api import capability
    from atelier.server.skills import runner

    async def _boom(*_a, **_k):
        raise runner.SkillRunFailed("技能执行失败：故意炸的", detail={"returncode": 7})

    monkeypatch.setattr(runner, "run_skill", _boom)

    resp = client.post("/api/skills/de-ai/run",
                       json={"params": {"text": "一段话"}, "project": "failproj"})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "running"

    # 等后台任务落终态
    for _ in range(50):
        if store.get_run(run_id) and store.get_run(run_id)["status"] != "running":
            break
        time.sleep(0.02)

    capability._RUNS.clear()  # ← 模拟重启
    got = client.get(f"/api/skills/runs/{run_id}").json()
    assert got["status"] == "failed", got
    assert "故意炸的" in got["error"]["message"]
    assert got["error"]["code"] == "SkillRunFailed"


def test_store_failure_does_not_break_run(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """落库炸了不能把技能运行一起搞挂——产物已经落盘，用户的工作没丢。

    这是「写穿缓存 + 库是真源」的设计前提：库不可用时降级为纯内存行为。
    故障注入打在 **DB 层**（``db.get_conn``），不是替换掉自带 try/except 的 store 函数，
    否则等于把要验证的保护逻辑自己绕过去了。
    """
    from atelier.server.api import capability
    from atelier.server.core import db as db_mod

    def _explode():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db_mod, "get_conn", _explode)
    capability._RUNS.clear()

    data = _run_card(client, project="degraded")
    assert data["status"] == "done", data
    assert data["artifacts"], "落库失败时产物仍应产出"
    # 降级到纯内存：同一个进程内仍查得到
    got = client.get(f"/api/skills/runs/{data['run_id']}").json()
    assert got["status"] == "done"
    # 库不可用时列表端点要给出空列表而不是 500
    assert client.get("/api/skills/runs").json() == {"runs": []}
