"""SPEC-02 §8 · 账号画像域测试。

覆盖 8 条 spec 测试清单 + 双写/向导/预览三条链路。所有测试都跑在
``atelier_root`` 夹具给的临时根下（conftest 已存在，本文件不新建）。

**并发不污染**用两个真实画像对比前缀，而不是靠 mock 断言——spec 验收 4 的要害是
「A 的正文一个字都不能出现在 B 的前缀里」，这句话必须用字符串比对来验。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atelier.server import paths
from atelier.server.core import db
from atelier.server.core.models import DIMENSION_LABELS, Memory, Profile, utcnow
from atelier.server.errors import ProfileNotFound, SessionBusy, ValidationError
from atelier.server.main import create_app
from atelier.server.profile import prompt as prompt_mod
from atelier.server.profile import store, wizard

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db(atelier_root: Path) -> None:
    """每个用例一个干净库 + 反向导入闸归零。"""
    db.init_db()
    store._SYNCED = False


@pytest.fixture
def client(atelier_root: Path):
    with TestClient(create_app()) as c:
        yield c


#: 无 body 的 DELETE 必须显式带 Content-Type，否则被地基层的跨站写拦截挡成 403
#: （CrossSiteWriteMiddleware 只看 Content-Type / Origin / Sec-Fetch-Site）。
#: 地基文件不在本域所有权内，故在调用侧带上——前端同样这么发。
DEL = {"headers": {"Content-Type": "application/json"}}


def make_profile(name: str = "AI 效率观察", **fields) -> Profile:
    """直写 store 造画像，绕开 HTTP，专测 store/prompt 本身。"""
    dims = {d: "" for d in store.TEXT_DIMS}
    dims.update(fields)
    return store.create_profile(name, platforms=fields.pop("platforms", ["xhs"]), fields=dims)


def full_profile(name: str, marker: str) -> Profile:
    """造一个「每一维都有独特标记词」的画像——用于比对不污染。"""
    return make_profile(
        name,
        identity=f"{marker}定位：独立创作者，主力做 AI 效率",
        style=f"{marker}风格：短句，先给结论",
        audience=f"{marker}受众：22-32 岁内容从业者",
        platform_rules=f"{marker}平台：小红书图文 1000 字",
        preferences=f"{marker}红线：不写极限词",
    )


# ---------------------------------------------------------------------------
# 1. CRUD
# ---------------------------------------------------------------------------


def test_create_minimal_profile(atelier_root: Path) -> None:
    """spec §8：只有名字也能建。"""
    p = store.create_profile("AI 效率观察")
    assert p.name == "AI 效率观察"
    assert p.platforms == []
    assert p.memories == []
    # 完整度全 0，但**画像存在且可用**
    assert set(p.completeness().values()) == {0}
    assert (paths.PROFILES / f"{p.id}.md").exists()


def test_computation_scores(atelier_root: Path) -> None:
    """六维完整度：纯长度启发式，记忆按条数（25 分/条）。"""
    p = make_profile(
        "评分",
        identity="x" * 40,        # 40/80 → 50
        style="y" * 80,            # 满分
        audience="",               # 0
        platform_rules="z" * 16,   # 20
        preferences="",
    )
    scores = p.completeness()
    assert scores["identity"] == 50
    assert scores["style"] == 100
    assert scores["audience"] == 0
    assert scores["platform_rules"] == 20
    assert scores["preferences"] == 0
    assert scores["memories"] == 0
    # 每个维度都有中文标签，前端不用自己翻译
    assert DIMENSION_LABELS["platform_rules"] == "平台约束"

    for i in range(4):
        store.add_memory(p.id, f"第 {i} 条记忆")
    assert store.get_profile(p.id).completeness()["memories"] == 100


def test_update_and_delete_roundtrip(atelier_root: Path) -> None:
    p = make_profile("改一改")
    p = store.update_profile(p.id, {"style": "极简：只写结论", "platforms": ["xhs", "gzh"]})
    assert p.style == "极简：只写结论"
    assert p.platforms == ["xhs", "gzh"]
    # 双写：md 跟着更新，且带的是**本次**的时间戳
    md = (paths.PROFILES / f"{p.id}.md").read_text("utf-8")
    assert "极简：只写结论" in md
    assert f"updated_at: {_zulu(p.updated_at)}" in md

    token = wizard.create_token(p.id)
    store.delete_profile(p.id, confirm=p.id)
    assert store.get_profile_or_none(p.id) is None
    assert not (paths.PROFILES / f"{p.id}.md").exists()
    # 向导进度跟着清掉，不留孤儿行
    assert wizard.load_state(token) is None


def test_update_rejects_unknown_field(atelier_root: Path) -> None:
    p = make_profile("冻结字段")
    with pytest.raises(ValidationError) as ei:
        store.update_profile(p.id, {"id": "hacked"})
    assert "id" in ei.value.detail["unknown"]


# ---------------------------------------------------------------------------
# 2. ★ 画像注入（spec §4，本域地基）
# ---------------------------------------------------------------------------


def test_profile_prefix_contains_all_dims(atelier_root: Path) -> None:
    """六个标题 + 五维正文 + 记忆条目，一个都不能少。"""
    p = full_profile("注入检查", "ZZMARK")
    store.add_memory(p.id, "ZZMARK 记忆：反常识 + 亲手实测")

    prefix = prompt_mod.build_profile_prefix(store.get_profile(p.id))
    assert prefix.startswith("<account_profile>")
    assert prefix.endswith("</account_profile>")
    for label in ("## 定位", "## 风格", "## 受众", "## 平台约束", "## 偏好红线（禁止违反）", "## 长期记忆"):
        assert label in prefix, label
    for dim in store.TEXT_DIMS:
        assert getattr(p, dim) in prefix
    assert "- ZZMARK 记忆：反常识 + 亲手实测" in prefix


def test_profile_prefix_empty_in_general_mode(atelier_root: Path) -> None:
    """spec 验收 3：通用模式 / 无画像 → 返回空串，一个字都不注入。"""
    p = full_profile("通用模式", "GEN")
    assert prompt_mod.build_profile_prefix(None) == ""

    store.set_general_mode(p.id, True)
    gp = store.get_profile(p.id)
    assert gp.general_mode is True
    assert prompt_mod.build_profile_prefix(gp) == ""

    # 整个 system_prompt 里也不能有画像正文
    system_prompt = prompt_mod.build_system_prompt(gp)
    for dim in store.TEXT_DIMS:
        assert getattr(gp, dim) not in system_prompt


def test_no_undopted_memory_in_prefix(atelier_root: Path) -> None:
    """未采纳的记忆不进 prompt（用户能留但可以不生效）。"""
    p = make_profile("采纳与否", identity="a")
    store.add_memory(p.id, "adopted-good")
    keep = store.get_profile(p.id)
    keep.memories = [
        *keep.memories,
        Memory(id="mem-off", text="rejected-secret", source="手动", created_at=utcnow(), adopted=False),
    ]
    store._sync_memories(keep)
    store._write_md(keep)
    prefix = prompt_mod.build_profile_prefix(store.get_profile(p.id))
    assert "adopted-good" in prefix
    assert "rejected-secret" not in prefix


def test_turn_suffix_reminds_skill_lookup(atelier_root: Path) -> None:
    """spec 验收 6：每轮末尾重申「先查技能库」。"""
    suffix = prompt_mod.build_turn_suffix()
    assert "先查技能库" in suffix
    assert "atelier_gate_run" in suffix
    # 调用方的后缀在前，提醒固定在末尾
    combined = prompt_mod.build_turn_suffix("我这轮特别要求：用中文")
    assert combined.index("用中文") < combined.index("先查技能库")
    assert combined.endswith("atelier_artifact_write 写入。")


# ---------------------------------------------------------------------------
# 3. ★ 并发不污染（spec 验收 4、5）
# ---------------------------------------------------------------------------


def test_two_profiles_no_pollution(atelier_root: Path) -> None:
    """两个画像并发各拼一次前缀：**互不包含**，且都不落全局文件。"""
    a = full_profile("甲号", "AAA")
    b = full_profile("乙号", "BBB")
    store.add_memory(a.id, "AAA 记忆甲")
    store.add_memory(b.id, "BBB 记忆乙")

    async def build(pid: str) -> str:
        # 故意交错 await：模拟两个会话同时发消息
        await asyncio.sleep(0)
        return prompt_mod.build_profile_prefix(store.get_profile(pid))

    prefix_a, prefix_b = asyncio.run(_gather(build(a.id), build(b.id)))

    assert "AAA" in prefix_a and "BBB" not in prefix_a
    assert "BBB" in prefix_b and "AAA" not in prefix_b
    assert prefix_a != prefix_b
    # 记忆同样隔离
    assert "AAA 记忆甲" in prefix_a and "BBB 记忆乙" not in prefix_a

    # 落全局文件检查：var/ 下不许有画像正文的**明文文件**（PRD 4.2 验收 5）。
    # `atelier.db` 及其 WAL 是 SQLite 本体——spec §3 明确「双写：SQLite 为准」，
    # 画像文本理应在库里；验收 5 禁的是「被无条件加载进每次会话的全局提示文件」，
    # 所以这里排除 db 本体，只查文本落盘文件。
    leaked = [
        f for f in paths.VAR.rglob("*")
        if f.is_file()
        and f.suffix not in (".db", ".db-wal", ".db-shm")
        and any(m in f.read_text("utf-8", errors="ignore") for m in ("AAA定位", "BBB定位"))
    ]
    assert leaked == [], f"画像正文漏进了全局文件：{leaked}"


async def _gather(*coros):  # 测试辅助：真并发 gather
    return await asyncio.gather(*coros)


def test_two_profiles_preview_differs(atelier_root: Path) -> None:
    """spec 验收 4 的 API 口径：两个画像的 /preview 内容不同。"""
    client = TestClient(create_app())
    a = full_profile("甲号", "AAA")
    b = full_profile("乙号", "BBB")
    pa = client.get(f"/api/profiles/{a.id}/preview").json()
    pb = client.get(f"/api/profiles/{b.id}/preview").json()
    assert pa["system_prompt"] != pb["system_prompt"]
    assert "AAA定位" in pa["system_prompt"] and "BBB定位" not in pa["system_prompt"]
    assert pa["leaked_dims"] == [] and pb["leaked_dims"] == []


# ---------------------------------------------------------------------------
# 4. 双写与反向导入（spec §3）
# ---------------------------------------------------------------------------


def test_markdown_roundtrip_and_reverse_import(atelier_root: Path) -> None:
    """md 可手改 → updated_at 更新后反向导入回 SQLite；反之 SQLite 为准。"""
    p = full_profile("手改测试", "EDIT")
    path = paths.PROFILES / f"{p.id}.md"

    # 1) 模拟用户手改 md（并把 updated_at 推到未来 → 比库新）
    text = path.read_text("utf-8")
    text = text.replace("EDIT风格：短句，先给结论", "手改过的风格：一句话说完")
    text = text.replace(f"updated_at: {_zulu(p.updated_at)}", "updated_at: 2099-01-01T00:00:00Z")
    path.write_text(text, encoding="utf-8")

    imported = store.sync_from_disk()
    assert imported == [p.id]
    reloaded = store.get_profile(p.id)
    assert "手改过的风格" in reloaded.style
    # 反向导入后 md 被规范化重写，updated_at 保留 md 的值
    assert reloaded.updated_at.year == 2099

    # 2) md 比库**旧**时不导入——SQLite 是准的（spec §3）
    stale = store.update_profile(p.id, {"audience": "库里的更新"})
    older = (stale.updated_at - timedelta(days=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    path.write_text(
        path.read_text("utf-8").replace(f"updated_at: {_zulu(stale.updated_at)}", f"updated_at: {older}"),
        encoding="utf-8",
    )
    assert store.sync_from_disk() == []
    assert store.get_profile(p.id).audience == "库里的更新"


def _zulu(dt) -> str:
    """和 :func:`store._fmt_ts` 同一个写法（UTC + ``Z``），否则 replace 匹配不上。"""
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_markdown_export_is_human_readable(atelier_root: Path) -> None:
    p = full_profile("导出检查", "EXP")
    store.add_memory(p.id, "导出记忆", source="归因")
    md = store.render_markdown(store.get_profile(p.id))
    # frontmatter + 五维 + 记忆，且是 spec §3 的形状
    assert md.startswith("---\n")
    for key in ("id:", "name:", "platforms:", "general_mode:", "updated_at:"):
        assert key in md
    for dim in store.TEXT_DIMS:
        assert f"## {dim}" in md
    assert "## memories" in md
    assert "- [归因] 导出记忆" in md
    # 能原样解析回来
    parsed = store.parse_markdown(md)
    assert parsed["fields"]["name"] == "导出检查"
    assert parsed["memories"][0]["text"] == "导出记忆"


# ---------------------------------------------------------------------------
# 5. 创建向导（spec §5）
# ---------------------------------------------------------------------------


def test_wizard_skip_all_steps(atelier_root: Path) -> None:
    """第 1 步填名字，其余全跳过 → progress 到 4/4，next_step=done。"""
    p = store.create_profile("向导全跳过")
    token = wizard.create_token(p.id, profile_name=p.name)

    state = wizard.advance(token, "basic", {"name": "向导全跳过"})
    assert state.next_step == "social"
    assert state.progress_label == "1/4"

    for step in ("social", "intent", "redlines"):
        state = wizard.advance(token, step, {}, skip=True)
    assert state.progress == 4
    assert state.progress_label == "4/4"
    assert state.next_step == "done"
    assert state.skipped == ["social", "intent", "redlines"]
    # 跳过的步没写进画像（不留垃圾占位）
    assert store.get_profile(p.id).preferences == ""


def test_wizard_step1_requires_name(atelier_root: Path) -> None:
    """第 1 步不可跳过：spec §5「最少要账号名」。"""
    p = store.create_profile("需要名字")
    token = wizard.create_token(p.id)
    with pytest.raises(ValidationError) as ei:
        wizard.advance(token, "basic", {}, skip=True)
    assert "name" in ei.value.detail["need"]


def test_wizard_collects_into_dims(atelier_root: Path) -> None:
    """4 步的输入分别落进对应维度。"""
    p = store.create_profile("向导收集")
    token = wizard.create_token(p.id)
    wizard.advance(token, "basic", {"name": "向导收集", "platform": "gzh", "direction": "做 AI 工具测评"})
    wizard.advance(token, "social", {"urls": {"公众号": "https://example.com/a"}})
    wizard.advance(token, "intent", {"goals": ["涨粉", "接商单"]})
    wizard.advance(token, "redlines", {"bans": ["不写极限词", "不做未实测的对比"]})

    done = store.get_profile(p.id)
    assert done.name == "向导收集"
    assert "gzh" in done.platforms
    assert "做 AI 工具测评" in done.identity
    assert "运营意图" in done.identity and "涨粉" in done.identity
    assert "https://example.com/a" in done.platform_rules
    assert "不写极限词" in done.preferences
    assert done.completeness()["preferences"] > 0


def test_wizard_resume_from_token(atelier_root: Path) -> None:
    """中途退出 → 带 token 回来接着走（spec §5）。"""
    p = store.create_profile("断点续传")
    token = wizard.create_token(p.id)
    wizard.advance(token, "basic", {"name": "断点续传", "direction": "长期主义"})

    # 模拟换个进程读回进度
    reloaded = wizard.get_state(token)
    assert reloaded.completed == 1
    assert reloaded.next_step == "social"
    assert "长期主义" in store.get_profile(p.id).identity

    reloaded = wizard.advance(token, "social", {}, skip=True)
    assert reloaded.next_step == "intent"


def test_wizard_abandon_keeps_content(atelier_root: Path) -> None:
    """中途放弃：清进度、留内容。"""
    p = store.create_profile("放弃向导")
    token = wizard.create_token(p.id)
    wizard.advance(token, "basic", {"name": "放弃向导", "direction": "先写着"})

    result = wizard.abandon(token)
    assert result["kept"] is True
    assert wizard.load_state(token) is None
    assert "先写着" in store.get_profile(p.id).identity


# ---------------------------------------------------------------------------
# 6. 记忆 CRUD
# ---------------------------------------------------------------------------


def test_memory_add_and_inject(atelier_root: Path) -> None:
    """spec 验收 7：加一条记忆 → 下一轮 prompt 里就有。"""
    p = make_profile("记忆生效", identity="底稿")
    before = prompt_mod.build_profile_prefix(p)
    assert "不用 emoji" not in before

    store.add_memory(p.id, "不用 emoji")
    after = prompt_mod.build_profile_prefix(store.get_profile(p.id))
    assert "- 不用 emoji" in after
    # 双写
    assert "不用 emoji" in (paths.PROFILES / f"{p.id}.md").read_text("utf-8")

    mem = store.get_profile(p.id).memories[0]
    store.delete_memory(p.id, mem.id)
    assert "- 不用 emoji" not in prompt_mod.build_profile_prefix(store.get_profile(p.id))
    with pytest.raises(ProfileNotFound):
        store.delete_memory(p.id, mem.id)


def test_memory_rejects_empty(atelier_root: Path) -> None:
    p = make_profile("空记忆")
    with pytest.raises(ValidationError):
        store.add_memory(p.id, "   ")


# ---------------------------------------------------------------------------
# 7. 通用模式
# ---------------------------------------------------------------------------


def test_general_mode_toggle_roundtrip(atelier_root: Path) -> None:
    p = full_profile("开关", "TOG")
    assert prompt_mod.build_profile_prefix(store.set_general_mode(p.id, True)) == ""
    assert prompt_mod.build_profile_prefix(store.set_general_mode(p.id, False)) != ""


# ---------------------------------------------------------------------------
# 8. 删画像 409
# ---------------------------------------------------------------------------


def test_delete_profile_with_sessions_409(atelier_root: Path) -> None:
    """spec §5：有会话引用 → 409；清掉引用后才能删。"""
    p = make_profile("被占用")
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, profile_id, archived, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            ("s-1", "还在用", p.id, 0, db.utcnow(), db.utcnow()),
        )
    assert store.sessions_using(p.id) == 1

    with pytest.raises(SessionBusy) as ei:
        store.delete_profile(p.id, confirm=p.id)
    assert ei.value.http == 409
    assert ei.value.detail["sessions"] == 1

    with db.db_session() as conn:
        conn.execute("UPDATE sessions SET profile_id=NULL WHERE id=?", ("s-1",))
    store.delete_profile(p.id, confirm=p.id)
    assert store.get_profile_or_none(p.id) is None


def test_delete_requires_confirm_token(atelier_root: Path) -> None:
    p = make_profile("要确认")
    with pytest.raises(ValidationError):
        store.delete_profile(p.id, confirm="wrong")
    with pytest.raises(ValidationError):
        store.delete_profile(p.id)


# ---------------------------------------------------------------------------
# 9. API 层（13 端点冒烟）
# ---------------------------------------------------------------------------


def test_api_endpoints_smoke(client: TestClient) -> None:
    """spec §5 的 13 个端点逐个过一遍。"""
    # 1) GET 列表（空）
    assert client.get("/api/profiles").json()["count"] == 0

    # 2) POST 新建 → 带 wizard_token
    created = client.post("/api/profiles", json={"name": "AI 效率观察", "platforms": ["xhs"]})
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["wizard_token"]
    assert created.json()["wizard"]["progress_label"] == "0/4"

    # 3) GET 详情
    assert client.get(f"/api/profiles/{pid}").json()["name"] == "AI 效率观察"

    # 4) PATCH 单维 → completeness 重算
    patched = client.patch(f"/api/profiles/{pid}", json={"identity": "独立创作者，主力做 AI 效率"})
    assert patched.json()["identity"].startswith("独立创作者")
    assert patched.json()["completeness"]["identity"] > 0
    assert patched.json()["completeness"]["style"] == 0

    # 5) 向导走 4 步（含跳过）
    token = created.json()["wizard_token"]
    s1 = client.post(f"/api/profiles/{pid}/wizard/step", json={"step": "basic", "data": {"name": "AI 效率观察"}, "token": token})
    assert s1.json()["progress_label"] == "1/4"
    for step in ("social", "intent", "redlines"):
        s = client.post(f"/api/profiles/{pid}/wizard/step", json={"step": step, "skip": True, "token": token})
    assert s.json()["progress_label"] == "4/4"
    assert s.json()["next_step"] == "done"

    # 6) 记忆 CRUD
    mem = client.post(f"/api/profiles/{pid}/memories", json={"text": "不用 emoji"})
    mid = mem.json()["memory"]["id"]
    assert client.get(f"/api/profiles/{pid}/memories").json()["count"] == 1
    assert client.delete(f"/api/profiles/{pid}/memories/{mid}", **DEL).json()["ok"] is True

    # 7) 通用模式 → preview 干净
    client.post(f"/api/profiles/{pid}/general-mode", json={"enabled": True})
    pv = client.get(f"/api/profiles/{pid}/preview").json()
    assert pv["injected"] is False
    assert pv["leaked_dims"] == []
    assert "不用 emoji" not in pv["system_prompt"]
    client.post(f"/api/profiles/{pid}/general-mode", json={"enabled": False})
    pv = client.get(f"/api/profiles/{pid}/preview").json()
    assert pv["injected"] is True
    assert "独立创作者" in pv["system_prompt"]
    assert "先查技能库" in pv["system_prompt"]

    # 8) 导出
    exp = client.get(f"/api/profiles/{pid}/export")
    assert exp.status_code == 200
    assert "attachment" in exp.headers["content-disposition"]
    assert "## identity" in exp.text

    # 9) 列表含完整度，按 updated_at 倒序
    listing = client.get("/api/profiles").json()
    assert listing["count"] == 1
    assert listing["profiles"][0]["completeness_overall"] >= 0

    # 10) 删
    assert client.delete(f"/api/profiles/{pid}?confirm={pid}", **DEL).json()["ok"] is True
    assert client.get(f"/api/profiles/{pid}").status_code == 404


def test_api_error_bodies_follow_contract(client: TestClient) -> None:
    """错误响应体固定 ``{error:{code,message,detail,hint}}``（SPEC-01 §2）。"""
    r = client.get("/api/profiles/no-such-profile")
    assert r.status_code == 404
    body = r.json()["error"]
    assert set(body) == {"code", "message", "detail", "hint"}
    assert body["code"] == "ProfileNotFound"

    created = client.post("/api/profiles", json={"name": "无名字也能建"})
    pid = created.json()["id"]
    bad = client.patch(f"/api/profiles/{pid}", json={"preferences": "不用 emoji"}).json()
    assert bad["completeness"]["preferences"] > 0
    r = client.post("/api/profiles", json={"name": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ValidationError"


def test_api_route_mounted_without_double_prefix(client: TestClient) -> None:
    """``/api/profiles`` 而不是 ``/api/api/profiles``（main.py 统一加前缀）。"""
    mounted = set(client.app.openapi()["paths"])
    assert "/api/profiles" in mounted
    assert "/api/profiles/{profile_id}" in mounted
    assert "/api/profiles/{profile_id}/preview" in mounted
    assert "/api/profiles/{profile_id}/wizard/step" in mounted
    assert "/api/profiles/{profile_id}/export" in mounted
    assert not any(p.startswith("/api/api/") for p in mounted)
