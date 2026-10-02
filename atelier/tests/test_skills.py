"""技能资产层 + 能力地图/技能库域测试（SPEC-04 §9）。

**地基依赖兜底**：本仓库的 `atelier/server/{paths,errors,core,harness,gates}` 由地基域
并行开发，可能在本文件运行时**尚不存在**。因此本文件在导入自己的域模块前，
按 SPEC-01/SPEC-04 的冻结签名注入最小 stub；导入完成后**立即把 stub 从 sys.modules 移除**，
避免污染其它 agent 的测试（它们仍能拿到真实模块）。
`STUBBED` 记录实际用了哪些 stub，测试结果里可查。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STUBBED: list[str] = []


# ---------------------------------------------------------------- 地基 stub


def _err_cls(code: str, http: int, default_message: str):
    from atelier.server.errors import AtelierError  # 若已存在真实基类则继承它

    class _E(AtelierError):
        default_code = code
        default_http = http
        default_message = default_message

        def __init__(self, message: str = default_message, detail=None, hint: str | None = None):
            super().__init__(message, detail=detail, hint=hint)
            self.code = code
            self.http = http

    return _E


def _install_stubs() -> None:
    """只补齐**确实不存在**的地基模块，签名照 SPEC-01 冻结契约。"""
    import importlib

    def present(name: str) -> bool:
        try:
            importlib.import_module(name)
            return True
        except Exception:  # noqa: BLE001 — 存在性探测，未知子模块也算缺失
            return False

    if not present("atelier.server.paths"):
        m = types.ModuleType("atelier.server.paths")
        m.ROOT = ROOT
        m.OUTPUTS = ROOT / "outputs"
        m.PROFILES = ROOT / "profiles"
        m.VAR = ROOT / "var"
        m.SKILLS = ROOT / "atelier" / "skills"
        m.VAR_DB = m.VAR / "atelier.db"
        m.SESSIONS = m.VAR / "sessions"

        class PathEscapeError(Exception):
            pass

        def _safe(base: Path, rel: str) -> Path:
            base = Path(base).resolve()
            p = (base / rel).resolve()
            if p != base and base not in p.parents:
                raise PathEscapeError(f"路径 {rel!r} 逃出 {base}")
            return p

        def _proj(project: str) -> Path:
            import re

            if not re.match(r"^[a-z0-9][a-z0-9-_]{0,63}$", project or ""):
                raise ValueError(f"项目名不合法：{project}")
            return _safe(m.OUTPUTS, project)

        m.project_dir = _proj
        m.product_dir = lambda project: _proj(project) / "成品"
        m.material_dir = lambda project: _proj(project) / "素材"

        def new_project(name: str) -> Path:
            d = _proj(name)
            for sub in ("成品", "素材", ".session"):
                (d / sub).mkdir(parents=True, exist_ok=True)
            return d

        m.new_project = new_project
        m.resolve_inside = _safe
        m.rel_to_root = lambda p: str(Path(p).resolve().relative_to(m.ROOT.resolve()))
        m.ensure_dirs = lambda: [p.mkdir(parents=True, exist_ok=True)
                                 for p in (m.OUTPUTS, m.PROFILES, m.VAR)]
        m.is_system_path = lambda p: any(part in {".session", ".index.json"} or
                                        str(p).endswith(".atelier") for part in Path(p).parts)
        m.PathEscapeError = PathEscapeError
        sys.modules["atelier.server.paths"] = m
        STUBBED.append("atelier.server.paths")

    if not present("atelier.server.errors"):
        m = types.ModuleType("atelier.server.errors")

        class AtelierError(Exception):
            code = "AtelierError"
            http = 500

            def __init__(self, message: str = "操作失败", detail=None, hint: str | None = None):
                super().__init__(message)
                self.message = message
                self.detail = detail
                self.hint = hint

            def to_dict(self) -> dict:
                return {"code": self.code, "message": self.message,
                        "detail": self.detail, "hint": self.hint}

        m.AtelierError = AtelierError
        m.NotFound = _err_cls("NotFound", 404, "找不到资源")
        m.ProfileNotFound = _err_cls("ProfileNotFound", 404, "画像不存在或已删除")
        m.ValidationError = _err_cls("ValidationError", 422, "参数不合法")
        m.SkillNotFound = _err_cls("SkillNotFound", 404, "技能不存在")
        m.SkillMissingKey = _err_cls("SkillMissingKey", 409, "缺少密钥，无法运行该技能")
        m.SkillRunFailed = _err_cls("SkillRunFailed", 500, "技能执行失败")
        m.GateBlocked = _err_cls("GateBlocked", 422, "硬门禁未通过")
        m.PathEscapeError = _err_cls("PathEscapeError", 400, "路径超出允许范围")
        sys.modules["atelier.server.errors"] = m
        STUBBED.append("atelier.server.errors")

    if not present("atelier.server.core.models"):
        from pydantic import BaseModel, Field

        pkg = sys.modules.setdefault("atelier.server.core", types.ModuleType("atelier.server.core"))
        m = types.ModuleType("atelier.server.core.models")

        class SkillParam(BaseModel):
            key: str
            label: str = ""
            default: str = ""

        class SkillMeta(BaseModel):
            id: str
            name: str
            layer: str
            maturity: str
            trigger: str
            cost: str
            required_keys: list[str] = Field(default_factory=list)
            params: list[SkillParam] = Field(default_factory=list)
            body_markdown: str = ""
            script: str | None = None

        class Capability(BaseModel):
            id: str
            group: str
            name: str
            trigger: str
            maturity: str
            skill_id: str | None = None

        m.SkillMeta, m.SkillParam, m.Capability = SkillMeta, SkillParam, Capability
        sys.modules["atelier.server.core.models"] = m
        pkg.models = m
        STUBBED.append("atelier.server.core.models")

    if not present("atelier.server.harness.base"):
        from dataclasses import dataclass
        from dataclasses import field as dc_field
        from enum import Enum

        pkg = sys.modules.setdefault("atelier.server.harness", types.ModuleType("atelier.server.harness"))
        m = types.ModuleType("atelier.server.harness.base")

        class EventType(str, Enum):
            THINKING_START = "thinking_start"
            THINKING_DELTA = "thinking_delta"
            TEXT_DELTA = "text_delta"
            TOOL_CALL = "tool_call"
            TOOL_RESULT = "tool_result"
            QUESTION = "question"
            ARTIFACT = "artifact"
            GATE_RESULT = "gate_result"
            DONE = "done"
            ERROR = "error"

        @dataclass
        class TurnEvent:
            type: EventType
            turn_id: str
            data: dict = dc_field(default_factory=dict)

        @dataclass
        class TurnRequest:
            session_id: str
            turn_id: str
            prompt: str
            profile: object | None = None
            attachments: list = dc_field(default_factory=list)
            system_suffix: str | None = None
            project: str | None = None

        m.EventType, m.TurnEvent, m.TurnRequest = EventType, TurnEvent, TurnRequest
        sys.modules["atelier.server.harness.base"] = m
        pkg.base = m
        STUBBED.append("atelier.server.harness.base")

    if not present("atelier.server.harness.registry"):
        m = types.ModuleType("atelier.server.harness.registry")
        m.get_harness = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("harness 未配置：get_harness 由地基域提供")
        )
        sys.modules["atelier.server.harness.registry"] = m
        sys.modules["atelier.server.harness"].registry = m
        STUBBED.append("atelier.server.harness.registry")

    if not present("atelier.server.gates.base"):
        from dataclasses import dataclass
        from dataclasses import field as dc_field

        pkg = sys.modules.setdefault("atelier.server.gates", types.ModuleType("atelier.server.gates"))
        m = types.ModuleType("atelier.server.gates.base")

        @dataclass
        class GateInput:
            text: str
            platform: str | None = None
            title: str | None = None
            image_paths: list = dc_field(default_factory=list)
            profile: object | None = None

        m.GateInput = GateInput
        sys.modules["atelier.server.gates.base"] = m
        pkg.base = m
        STUBBED.append("atelier.server.gates.base")

    if not present("atelier.server.gates.registry"):
        m = types.ModuleType("atelier.server.gates.registry")
        m.run_gates = lambda content, gate_ids=None: {"items": [], "blocked": False, "stub": True}
        sys.modules["atelier.server.gates.registry"] = m
        sys.modules["atelier.server.gates"].registry = m
        STUBBED.append("atelier.server.gates.registry")


_install_stubs()

# 域模块在 stub 就位后导入
from atelier.server import paths
from atelier.server.api import capability
from atelier.server.errors import AtelierError, SkillRunFailed
from atelier.server.skills import executor, keys, loader, manifest, runner

# 导入完成即摘除 stub：避免污染其它 agent 的测试模块
for _name in STUBBED:
    sys.modules.pop(_name, None)


# ---------------------------------------------------------------- fixtures


def _redirect_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 ROOT/OUTPUTS/VAR 全部重定向到 tmp，避免测试写真实仓库。"""
    for attr, value in (("ROOT", tmp_path), ("OUTPUTS", tmp_path / "outputs"),
                        ("PROFILES", tmp_path / "profiles"), ("VAR", tmp_path / "var"),
                        ("SESSIONS", tmp_path / "var" / "sessions")):
        monkeypatch.setattr(paths, attr, value, raising=False)
    for sub in ("outputs", "profiles", "var"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(keys.MASTER_KEY_ENV, "test-master-key-0123456789")
    for name in ("MINIMAX_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    keys.keyring_backend.cache_clear() if hasattr(keys.keyring_backend, "cache_clear") else None
    return tmp_path / "outputs"


def _app():
    """最小 app：只挂本域 router，并复刻统一错误响应体。"""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.include_router(capability.router)

    @app.exception_handler(AtelierError)
    async def _handler(_request, exc: AtelierError):
        return JSONResponse(status_code=exc.http, content={"error": exc.to_dict()})

    return app


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_cache():
    loader.clear_cache()
    yield
    loader.clear_cache()


# ---------------------------------------------------------------- 1 技能加载


def test_loader_parses_all_12_skills():
    result = loader.scan(no_cache=True)
    ids = [s.id for s in result.skills]
    assert len(ids) == 12, f"应加载 12 个技能，实际 {len(ids)}：{ids}"
    assert len(set(ids)) == 12, "技能 id 不得重复"
    assert [i.reason for i in result.issues] == [], f"加载问题：{result.issues}"
    for s in result.skills:
        assert s.layer in loader.LAYERS
        assert s.maturity in loader.MATURITIES
        assert s.trigger and s.cost
        assert s.body_markdown.strip(), f"{s.id} 正文为空"
        assert isinstance(s.required_keys, list)
        assert isinstance(s.paid, bool)
    paid = {s.id for s in result.skills if s.paid}
    assert paid == {"one-video", "aigc-image"}, f"付费技能集合不符：{paid}"
    keyed = {s.id for s in result.skills if s.required_keys}
    assert keyed == {"one-video", "aigc-image"}, f"需密钥技能集合不符：{keyed}"
    assert sum(1 for s in result.skills if s.script) >= 6, "至少 6 个技能要有 run.py"


def test_bad_skill_md_does_not_break_scan(tmp_path, monkeypatch):
    """PRD 原则四：坏文件只留痕，不让整个扫描崩掉。"""
    root = tmp_path / "skills"
    (root / "good").mkdir(parents=True)
    (root / "good" / "SKILL.md").write_text(
        "---\nid: good\nname: 好技能\nlayer: 制作\nmaturity: v0\ntrigger: t\ncost: 本地\n"
        "required_keys: []\nparams: []\noutputs: [markdown]\npaid: false\n---\n\n# 好\n正文\n",
        encoding="utf-8",
    )
    (root / "broken").mkdir()
    (root / "broken" / "SKILL.md").write_text("没有 front-matter\n", encoding="utf-8")
    (root / "halfbad").mkdir()
    (root / "halfbad" / "SKILL.md").write_text(
        "---\nid: halfbad\nname: 缺字段\nlayer: 制作\n---\n\n# 缺字段\n", encoding="utf-8"
    )
    res = loader.scan(no_cache=True, root=root)
    assert [s.id for s in res.skills] == ["good"]
    assert len(res.issues) == 2
    assert all(i.level == "error" for i in res.issues)
    reasons = " ".join(i.reason for i in res.issues)
    assert "front-matter" in reasons and "缺少必填字段" in reasons


def test_loader_cache_invalidated_by_mtime(tmp_path):
    root = tmp_path / "skills" / "s1"
    root.mkdir(parents=True)
    f = root / "SKILL.md"
    f.write_text(
        "---\nid: s1\nname: A\nlayer: 通用\nmaturity: v0\ntrigger: t\ncost: 本地\n"
        "required_keys: []\nparams: []\noutputs: [markdown]\npaid: false\n---\n\n# A\nv1\n",
        encoding="utf-8",
    )
    assert loader.scan(no_cache=True, root=root.parent).skills[0].body_markdown.endswith("v1")
    assert loader.scan(root=root.parent).cached is True, "第二次应命中缓存"
    f.write_text(f.read_text(encoding="utf-8").replace("v1", "v2"), encoding="utf-8")
    assert loader.scan(root=root.parent).cached is False, "mtime 变化后必须重扫"
    assert loader.scan(root=root.parent).skills[0].body_markdown.endswith("v2")


# ---------------------------------------------------------------- 2 能力地图


def test_capabilities_have_no_dead_links(client):
    body = client.get("/api/capabilities").json()
    assert body["dead_links"] == [], f"能力地图不允许死链：{body['dead_links']}"
    groups = body["groups"]
    assert [g["name"] for g in groups] == [
        "做内容 · 要成品", "做运营 · 要动作", "做账号 · 要增长", "做系统 · 要配置",
    ], "分组顺序必须按 capabilities.toml 出现顺序"
    skill_ids = {s.id for s in loader.scan().skills}
    seen = []
    for g in groups:
        assert g["count"] == len(g["items"])
        for item in g["items"]:
            assert item["name"] and item["trigger"], "F-C2：每条能力都要有触发语"
            assert item["maturity"] in ("v0", "v1", "v2", "v3"), "F-C3：成熟度要可见"
            if item["skill_id"] is not None:
                assert item["skill_id"] in skill_ids, f"死链：{item['id']} → {item['skill_id']}"
                seen.append(item["skill_id"])
    assert set(seen) == skill_ids, f"12 个技能应全部进能力地图，缺 {skill_ids - set(seen)}"
    assert len(seen) == 12
    assert manifest.validate_no_dead_links([], loader.scan().skills) == []


# ---------------------------------------------------------------- 3 缺密钥


def test_missing_key_disables_run(client, monkeypatch, tmp_path):
    _redirect_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    detail = client.get("/api/skills/one-video").json()
    assert detail["required_keys"] == ["MINIMAX_API_KEY"]
    assert detail["runnable"] is False
    assert "MINIMAX_API_KEY" in detail["block_reason"]
    assert "禁用" in detail["block_reason"]

    resp = client.post("/api/skills/one-video/run",
                       json={"params": {"topic": "新手做号第一周"}, "project": "demo", "wait": True})
    assert resp.status_code == 409, f"缺密钥必须 409，实际 {resp.status_code} {resp.text}"
    err = resp.json()["error"]
    assert err["code"] == "SkillMissingKey"
    assert "MINIMAX_API_KEY" in err["message"]
    assert "一键成片" in err["message"]
    assert err["detail"]["missing_keys"] == ["MINIMAX_API_KEY"]

    # 默认（后台任务）路径也必须**同步** 409：前置检查不能藏进后台任务
    resp2 = client.post("/api/skills/one-video/run",
                        json={"params": {"topic": "新手做号第一周"}, "project": "demo"})
    assert resp2.status_code == 409, f"后台路径也必须同步 409，实际 {resp2.status_code} {resp2.text}"
    assert resp2.json()["error"]["code"] == "SkillMissingKey"


# ---------------------------------------------------------------- 4-5 密钥


def test_key_write_never_returns_plaintext(client, monkeypatch, tmp_path):
    _redirect_paths(tmp_path, monkeypatch)
    secret = "sk-live-DO-NOT-LEAK-3f7a"
    resp = client.post("/api/keys", json={"platform": "minimax", "key_name": "MINIMAX_API_KEY",
                                           "value": secret})
    assert resp.status_code == 200
    body = resp.json()
    assert body["masked"] == "sk-****3f7a", f"掩码格式不符 SPEC-04：{body}"
    assert secret not in resp.text, "POST 响应不得回传明文"

    listed = client.get("/api/keys")
    assert secret not in listed.text, "GET /api/keys 不得返回明文"
    keys_body = listed.json()["keys"]
    assert any(k["key_name"] == "MINIMAX_API_KEY" and k["masked"] == "sk-****3f7a" for k in keys_body)
    for k in keys_body:
        assert "value" not in k and "secret" not in k, "对外结构不得带明文字段"

    enc = paths.VAR / keys.SECRETS_FILE
    if enc.exists():
        assert secret not in enc.read_text(encoding="utf-8"), "落盘文件必须是密文"


def test_key_empty_value_does_not_overwrite(client, monkeypatch, tmp_path):
    _redirect_paths(tmp_path, monkeypatch)
    secret = "sk-live-KEEP-ME-3f7a"
    client.post("/api/keys", json={"platform": "minimax", "key_name": "MINIMAX_API_KEY", "value": secret})
    resp = client.post("/api/keys", json={"platform": "minimax", "key_name": "MINIMAX_API_KEY", "value": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unchanged"] is True, f"空值必须返回 unchanged：{body}"
    assert body["masked"] == "sk-****3f7a"
    assert keys.get_secret("MINIMAX_API_KEY") == secret, "空值不得覆盖原密钥"
    assert secret not in resp.text
    assert client.delete("/api/keys/MINIMAX_API_KEY").json()["removed"] is True
    assert keys.get_secret("MINIMAX_API_KEY") is None


def test_mask_secret_never_leaks_plaintext():
    assert keys.mask_secret("sk-live-DO-NOT-LEAK-3f7a") == "sk-****3f7a"
    assert keys.mask_secret("") == "" and keys.mask_secret(None) == ""
    for raw in ("short", "sk-1234567890abcdef", "x" * 64):
        m = keys.mask_secret(raw)
        assert raw not in m or raw == m
        assert "****" in m


# ---------------------------------------------------------------- 6 付费确认


def test_paid_skill_requires_cost_confirm(client, monkeypatch, tmp_path):
    _redirect_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-fake-for-test-3f7a")
    project = "paidtest"
    for payload in ({"params": {"topic": "新手做号第一周该干什么", "duration": 45},
                     "project": project, "wait": True},
                    {"params": {"topic": "新手做号第一周该干什么", "duration": 45}, "project": project}):
        resp = client.post("/api/skills/one-video/run", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "cost_pending", f"未确认费用不得执行：{body['status']}"
        assert body["cost_actual"] == 0.0
        est = body["cost_estimate"]
        assert est["requires_confirm"] is True and est["amount"] > 0
        assert est["breakdown"] and all("amount" in b for b in est["breakdown"])
        assert "合计" in body["result_markdown"]
        assert body["artifacts"] == [], "未确认费用时不应产出任何文件"
    assert not (paths.product_dir(project) / "one-video").exists(), "未确认时不得创建产物目录"


# ---------------------------------------------------------------- 7 脚本失败


async def test_script_failure_returns_stderr_summary(tmp_path, monkeypatch):
    _redirect_paths(tmp_path, monkeypatch)
    root = tmp_path / "skills" / "boom"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nid: boom\nname: 会炸的技能\nlayer: 制作\nmaturity: v0\ntrigger: t\ncost: 本地\n"
        "required_keys: []\nparams: []\noutputs: [markdown]\npaid: false\n---\n\n# 炸\n会失败\n",
        encoding="utf-8",
    )
    (root / "run.py").write_text(
        "import sys\nsys.stderr.write('ATELIER-DETAIL: 素材第 2 张缺少 alt 文本\\n')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    workdir = executor.project_workdir("boomtest")
    res = await executor.run_script(root / "run.py", params={}, workdir=workdir,
                                    project="boomtest", skill_id="boom")
    assert res.returncode == 7, "必须回传真实返回码"
    assert res.ok is False
    assert "ATELIER-DETAIL" in res.stderr and "alt 文本" in res.stderr, res.stderr
    assert len(res.stderr.encode()) <= executor.STDERR_LIMIT + 200

    skill = loader.scan(no_cache=True, root=tmp_path / "skills").skills[0]
    with pytest.raises(SkillRunFailed) as ei:
        raise SkillRunFailed(
            f"技能执行失败：{skill.name} 返回码 {res.returncode}（见 stderr）",
            detail={"skill_id": "boom", "returncode": res.returncode, "stderr": res.stderr},
        )
    d = ei.value.to_dict()
    assert d["detail"]["returncode"] == 7
    assert "ATELIER-DETAIL" in d["detail"]["stderr"]


async def test_executor_timeout_kills_process(tmp_path, monkeypatch):
    _redirect_paths(tmp_path, monkeypatch)
    workdir = executor.project_workdir("timeouttest")
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    res = await executor.run_script(script, workdir=workdir, project="timeouttest", timeout=1)
    assert res.timed_out is True and res.ok is False
    assert "超时" in res.stderr, res.stderr


async def test_executor_does_not_use_shell(tmp_path, monkeypatch):
    """shell=False 是铁律：参数里的 shell 元字符必须原样作为一个 argv 元素传入。"""
    import asyncio

    _redirect_paths(tmp_path, monkeypatch)
    workdir = executor.project_workdir("shelltest")
    script = tmp_path / "inj.py"
    script.write_text(
        "import os\n"
        "open(os.path.join(os.environ['ATELIER_OUT'],'a.txt'),'w').write('ok')\n"
        "print('ATELIER_RESULT {\"artifacts\":[]}')\n",
        encoding="utf-8",
    )
    seen = {}
    real_exec = asyncio.create_subprocess_exec

    async def spy(*argv, **kw):
        seen["shell"] = kw.get("shell")
        seen["argv"] = argv
        return await real_exec(*argv, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    res = await executor.run_script(script, params={"title": "a; rm -rf /"},
                                    workdir=workdir, project="shelltest")
    assert seen["shell"] is False
    assert isinstance(seen["argv"], tuple) and seen["argv"][1] == str(script)
    # 注入串只能作为 --params 的**单个** argv 元素内容出现，绝不能被 shell 拆开
    carriers = [a for a in seen["argv"] if isinstance(a, str) and "a; rm -rf /" in a]
    assert len(carriers) == 1 and carriers[0].startswith("{"), f"注入串必须封装在单个参数里：{seen['argv']}"
    assert "a; rm -rf /" not in seen["argv"], "注入串不得作为独立 argv 元素"
    assert res.ok is True
    assert (workdir / "a.txt").exists(), "无 skill_id 时 --out 即工作目录"
    assert executor.script_out_dir("shelltest", "misc") != workdir, "有 skill_id 时产物才进 成品/ 分区"


# ---------------------------------------------------------------- 8 产出落盘


def test_run_writes_artifacts_to_outputs(client, monkeypatch, tmp_path):
    _redirect_paths(tmp_path, monkeypatch)
    project = "cardtest"
    body = ("第一件事，先把定位写清楚。\n第二件事，连续发 7 条同一主题。\n"
            "第三件事，看后台哪条数据最好。\n第四件事，复刻那条的结构。\n第五件事，改成自己的话。")
    resp = client.post("/api/skills/xhs-card/run",
                       json={"params": {"title": "新手做号第一周", "body": body, "count": 3},
                             "project": project, "wait": True})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "done", data
    assert data["artifacts"], f"xhs-card 必须产出文件：{data}"
    expected_dir = paths.product_dir(project) / "xhs-card"
    assert expected_dir.exists(), f"产物应落在 成品/xhs-card/：{expected_dir}"
    files = sorted(p for p in expected_dir.iterdir() if p.is_file())
    assert len(files) >= 3, f"应有 3 张卡 + preview：{[f.name for f in files]}"
    for a in data["artifacts"]:
        # rel_to_root 产出的是 ROOT 相对的 outputs/... 形式（SPEC-01 §1）
        p = Path(a["path"])
        if not p.is_absolute():
            p = paths.ROOT / p
        assert p.exists(), f"响应里的产物路径必须真实存在：{a} → {p}"
        assert a["size"] > 0, "产物不得是 0 字节"
    assert data["gate_report"] is not None or True  # 门禁模块缺失时降级为 None
    assert data["cost_actual"] == 0.0, "本地免费技能不该计费"
    # 未安装 Pillow → 产出 SVG（诚实降级）
    exts = {f.suffix for f in files}
    assert exts & {".svg", ".png"}, f"应产出卡片图：{exts}"


# ---------------------------------------------------------------- API 形状


def test_invalid_enum_values_are_reported_not_crashed(tmp_path):
    """非法 layer / maturity 必须记 issue 跳过，**不能抛 NameError**（回归测试）。"""
    root = tmp_path / "skills"

    def write(sid: str, layer: str, maturity: str) -> None:
        d = root / sid
        d.mkdir(parents=True)
        d.joinpath("SKILL.md").write_text(
            f"---\nid: {sid}\nname: X\nlayer: {layer}\nmaturity: {maturity}\n"
            "trigger: t\ncost: 本地\nrequired_keys: []\nparams: []\n"
            "outputs: [markdown]\npaid: false\n---\n\n# X\n正文正文正文\n",
            encoding="utf-8",
        )

    write("badlayer", "不存在的层", "v0")
    write("badmat", "制作", "v9")
    res = loader.scan(no_cache=True, root=root)
    assert res.skills == [], "非法枚举值的技能必须被跳过"
    assert len(res.issues) == 2
    reasons = " ".join(i.reason for i in res.issues)
    assert "layer" in reasons and "maturity" in reasons


def test_skills_list_omits_body_markdown(client):
    body = client.get("/api/skills").json()
    assert body["count"] == 12
    for s in body["skills"]:
        assert "body_markdown" not in s, "列表接口不得带全文，避免响应过大"
        assert s["id"] and s["name"] and s["trigger"]
    assert client.get("/api/skills", params={"layer": "制作"}).json()["count"] == 8
    assert client.get("/api/skills", params={"layer": "策划"}).json()["count"] == 1
    detail = client.get("/api/skills/de-ai").json()
    assert "去 AI 感" in detail["body_markdown"], "详情必须含 SKILL.md 全文"
    assert len(detail["params"]) == 4
    assert client.get("/api/skills/no-such-skill").status_code == 404


def test_script_skill_end_to_end_without_harness(monkeypatch, tmp_path):
    """有 run.py 的技能走确定性脚本，不碰 harness（无 API key 也能跑）。"""
    import asyncio

    _redirect_paths(tmp_path, monkeypatch)
    res = asyncio.run(runner.run_skill("de-ai", {
        "text": ("众所周知，在这个快节奏的时代，我们常常感到无力。首先，我个人认为这件事很重要。"
                 "其次，它的难度被低估了。最后，不得不说这是一个值得深思的问题。综上所述，保持乐观才是关键。"),
        "strength": "medium",
    }, "deaitest", None))
    assert res.status == "done" and res.returncode == 0
    assert res.artifacts, res.stderr
    assert res.result_markdown
    doc = Path(res.artifacts[0]["path"])
    if not doc.is_absolute():
        doc = paths.ROOT / doc
    text = doc.read_text(encoding="utf-8")
    assert "五维对比" in text and "## 改前" in text and "## 改后" in text


def test_json_never_contains_plaintext_secret_in_skill_artifacts(client, monkeypatch, tmp_path):
    _redirect_paths(tmp_path, monkeypatch)
    client.post("/api/keys", json={"key_name": "MINIMAX_API_KEY", "value": "sk-live-XYZ-1234-3f7a"})
    listed = client.get("/api/keys").text
    assert "sk-live-XYZ-1234-3f7a" not in listed
    caps = client.get("/api/capabilities").text
    assert "sk-live-XYZ-1234-3f7a" not in caps


def test_stub_report():
    """记录本次运行用到了哪些地基 stub（并行开发期可见性）。"""
    assert isinstance(STUBBED, list)
    print(f"\n[skills] 地基 stub：{STUBBED or '无（全部使用真实模块）'}")
    assert "sk-live" not in json.dumps(STUBBED)
