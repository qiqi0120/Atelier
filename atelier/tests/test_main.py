"""SPEC-01 §8 · app factory 测试。

重点两条：

1. **路由自动发现**：域 agent 新增 ``api/<域>.py``（模块级 ``router``）能自动挂上，
   不用改 ``main.py``——这是并行开发的命门，必须有测试守住。
2. **跨站写拦截**：CORS 之外再加一层，不依赖浏览器配合。
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atelier.server import main as main_mod
from atelier.server.config import Settings, reload_settings
from atelier.server.main import API_PREFIX, CrossSiteWriteMiddleware, create_app

JSON = {"Content-Type": "application/json"}
GOOD_ORIGIN = {"Origin": "http://localhost:5173"}
BAD_ORIGIN = {"Origin": "https://evil.example.com"}


@pytest.fixture
def client(atelier_root: Path) -> Iterator[TestClient]:
    """每个测试一个干净 app（不缓存，避免路由状态互相污染）。"""
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def temp_api_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """造一个临时的 ``api/`` 风格包，用来验证自动发现。

    **用临时包而不是真仓库目录**：不能为了测试去改 ``atelier/server/api/``
    （那是别的 agent 的地盘，测试往里塞文件就是并行写冲突）。
    """
    pkg_name = "atelier_test_api"
    pkg = tmp_path / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield pkg_name
    for mod in [m for m in sys.modules if m.startswith(pkg_name)]:
        del sys.modules[mod]


class TestAppFactory:
    def test_module_level_app_exists(self) -> None:
        """验收项：`from atelier.server.main import app`。"""
        assert main_mod.app.title == "Atelier"
        assert main_mod.app.version

    def test_openapi_under_api_prefix(self, atelier_root: Path) -> None:
        app = create_app()
        paths_ = {getattr(r, "path", "") for r in app.routes}
        assert f"{API_PREFIX}/health" in paths_
        assert f"{API_PREFIX}/meta" in paths_
        assert f"{API_PREFIX}/openapi.json" in paths_

    def test_create_app_is_idempotent(self, atelier_root: Path) -> None:
        assert create_app() is not create_app(), "每次调用都该造新 app（测试隔离）"

    def test_cors_locks_to_local(self, atelier_root: Path) -> None:
        st = reload_settings()
        assert st.is_cors_locked is True
        assert set(st.cors_origins) == {
            "http://localhost:5173", "http://127.0.0.1:5173"
        }

    def test_health(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "routers" in body
        assert body["config"]["anthropic_api_key"] is None  # 密钥不回传

    def test_health_masks_secrets(self, atelier_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value-1234")
        app = create_app(settings=reload_settings())
        body = TestClient(app).get(f"{API_PREFIX}/health").json()
        shown = body["config"]["anthropic_api_key"]
        assert shown and "secret-value" not in shown
        assert "…" in shown

    def test_meta_lists_four_gates(self, client: TestClient) -> None:
        body = client.get(f"{API_PREFIX}/meta").json()
        assert {g["id"] for g in body["gates"]} == {
            "ai_flavor", "compliance", "secret_scan", "wordcount"
        }
        assert body["gate_errors"] == {}

    def test_root_placeholder_when_no_frontend(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "atelier" in r.json()


class TestRouterAutoload:
    def test_missing_api_dir_is_skipped(self, atelier_root: Path) -> None:
        """api/ 目录可能还没建，不能因此起不来。"""
        assert main_mod._autoload_routers(FastAPI(), package="atelier.server.does_not_exist") == []

    def test_discovers_module_level_router(self, temp_api_package: str) -> None:
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "chat.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/chat')\n"
            "async def chat():\n"
            "    return {'ok': True}\n",
            encoding="utf-8",
        )
        app = FastAPI()
        loaded = main_mod._autoload_routers(app, package=temp_api_package)
        assert loaded == [f"{temp_api_package}.chat"]
        # 注意：FastAPI 0.142 的 include_router 存的是惰性 _IncludedRouter 包装，
        # 不会把路径摊平进 app.routes —— 所以断言真实行为（能不能打通）而不是 introspect。
        assert TestClient(app).get(f"{API_PREFIX}/chat").json() == {"ok": True}

    def test_loaded_router_actually_serves(
        self, atelier_root: Path, temp_api_package: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """端到端：create_app() 启动时就该把新域挂上，前端能直接打到。"""
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "library.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/library/items')\n"
            "async def items():\n"
            "    return {'items': []}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(main_mod, "API_PACKAGE", temp_api_package)
        app = create_app(settings=reload_settings())
        client = TestClient(app)
        assert client.get(f"{API_PREFIX}/library/items").json() == {"items": []}
        assert f"{temp_api_package}.library" in client.get(f"{API_PREFIX}/health").json()["routers"]

    def test_underscore_modules_skipped(self, temp_api_package: str) -> None:
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "_shared.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n", encoding="utf-8"
        )
        assert main_mod._autoload_routers(FastAPI(), package=temp_api_package) == []

    def test_module_without_router_is_recorded_not_fatal(self, temp_api_package: str) -> None:
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        app = FastAPI()
        main_mod.ROUTER_ERRORS.clear()
        assert main_mod._autoload_routers(app, package=temp_api_package) == []
        assert any("helper" in k for k in main_mod.ROUTER_ERRORS)

    def test_broken_module_does_not_crash_startup(self, temp_api_package: str) -> None:
        """一个域写坏了，服务要能起来并把原因报出来（PRD 原则四：不静默）。"""
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "broken.py").write_text("import 不存在的模块\n", encoding="utf-8")
        (Path(pkg.__file__).parent / "good.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n", encoding="utf-8"
        )
        app = FastAPI()
        main_mod.ROUTER_ERRORS.clear()
        loaded = main_mod._autoload_routers(app, package=temp_api_package)
        assert loaded == [f"{temp_api_package}.good"], "好模块仍要挂上"
        assert any("broken" in k for k in main_mod.ROUTER_ERRORS)

    def test_router_prefix_override(self, temp_api_package: str) -> None:
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "own.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "ROUTER_PREFIX = ''\n"
            "@router.get('/custom')\n"
            "async def custom():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        app = FastAPI()
        main_mod._autoload_routers(app, package=temp_api_package)
        assert TestClient(app).get("/custom").status_code == 200

    def test_non_router_object_ignored(self, temp_api_package: str) -> None:
        pkg = importlib.import_module(temp_api_package)
        (Path(pkg.__file__).parent / "fake.py").write_text(
            "router = '我只是个字符串'\n", encoding="utf-8"
        )
        app = FastAPI()
        main_mod.ROUTER_ERRORS.clear()
        assert main_mod._autoload_routers(app, package=temp_api_package) == []


class TestCrossSiteWriteMiddleware:
    def _app(self) -> FastAPI:
        app = FastAPI()
        app.add_middleware(
            CrossSiteWriteMiddleware,
            allowed_content_types=("application/json", "multipart/form-data"),
            allowed_origins=("http://localhost:5173",),
            trusted_fetch_sites=("same-origin", "same-site", "none"),
        )

        @app.post("/write")
        async def write() -> dict[str, bool]:
            return {"ok": True}

        @app.get("/read")
        async def read() -> dict[str, bool]:
            return {"ok": True}

        return app

    def test_json_write_from_local_origin_allowed(self) -> None:
        c = TestClient(self._app())
        assert c.post("/write", json={"a": 1}, headers=GOOD_ORIGIN).status_code == 200

    def test_json_write_without_origin_allowed(self) -> None:
        """curl / CLI 不发 Origin，别把本地工具挡在外面。"""
        assert TestClient(self._app()).post("/write", json={"a": 1}).status_code == 200

    def test_form_content_type_blocked(self) -> None:
        """form-urlencoded 是经典 CSRF 载体，必须拦。"""
        c = TestClient(self._app())
        r = c.post("/write", content="a=1", headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "CrossSiteWriteBlocked"
        assert r.json()["error"]["detail"]["reason"] == "content_type_not_allowed"

    def test_multipart_allowed_for_uploads(self) -> None:
        """素材上传用 multipart（PRD F-B2），不能被拦。"""
        r = TestClient(self._app()).post("/write", files={"f": ("a.png", b"x", "image/png")})
        assert r.status_code == 200

    def test_missing_content_type_blocked(self) -> None:
        c = TestClient(self._app())
        r = c.post("/write", content=b"{}", headers={"Content-Type": ""})
        assert r.status_code == 403

    def test_bad_origin_blocked(self) -> None:
        r = TestClient(self._app()).post("/write", json={}, headers=BAD_ORIGIN)
        assert r.status_code == 403
        assert r.json()["error"]["detail"]["reason"] == "origin_not_allowed"

    def test_null_origin_blocked(self) -> None:
        r = TestClient(self._app()).post("/write", json={}, headers={"Origin": "null"})
        assert r.status_code == 403

    def test_own_origin_write_allowed(self) -> None:
        """回归：`atelier web` 自带 SPA 时，**同源**写请求必须放行。

        ``cors_origins`` 默认只列了 Vite dev server 的 :5173，那是「前端另起 dev server、
        跨源调后端」的形态。但 `atelier web` 更常见的用法是**自己 serve 构建好的 SPA**，
        页面与 API 同源 —— 此时所有写请求都带 ``Origin: http://<host>:<port>``，
        撞白名单 → 全 403：对话发不出去、技能跑不了、画像存不进去。

        TestClient 默认发 ``Host: testserver``，用同值构造 Origin 即为同源。
        """
        c = TestClient(self._app())
        r = c.post("/write", json={}, headers={"Origin": "http://testserver"})
        assert r.status_code == 200, r.text

    def test_same_host_other_port_still_blocked(self) -> None:
        """同 host 但**不同端口**是跨源，仍须拦——不能把同源判定放宽成「同 host」。"""
        c = TestClient(self._app())
        r = c.post("/write", json={}, headers={"Origin": "http://testserver:9999"})
        assert r.status_code == 403
        assert r.json()["error"]["detail"]["reason"] == "origin_not_allowed"

    def test_cross_origin_fetch_site_blocked(self) -> None:
        r = TestClient(self._app()).post(
            "/write", json={}, headers=GOOD_ORIGIN | {"Sec-Fetch-Site": "cross-site"}
        )
        assert r.status_code == 403
        assert r.json()["error"]["detail"]["reason"] == "fetch_site_not_allowed"

    def test_same_origin_fetch_site_allowed(self) -> None:
        r = TestClient(self._app()).post(
            "/write", json={}, headers=GOOD_ORIGIN | {"Sec-Fetch-Site": "same-origin"}
        )
        assert r.status_code == 200

    @pytest.mark.parametrize("method", ["get", "head", "options"])
    def test_safe_methods_never_blocked(self, method: str) -> None:
        r = getattr(TestClient(self._app()), method)("/read", headers=BAD_ORIGIN)
        assert r.status_code != 403, f"{method.upper()} 属于安全方法，不该被跨站拦截"

    def test_error_body_is_unified(self) -> None:
        r = TestClient(self._app()).post("/write", json={}, headers=BAD_ORIGIN)
        err = r.json()["error"]
        assert set(err) >= {"code", "message", "detail", "hint"}
        assert err["hint"], "403 也要告诉用户怎么办"

    def test_can_be_disabled_for_tests(self) -> None:
        app = FastAPI()
        app.add_middleware(
            CrossSiteWriteMiddleware,
            allowed_content_types=("application/json",),
            allowed_origins=("http://localhost:5173",),
            trusted_fetch_sites=("same-origin",),
            enabled=False,
        )

        @app.post("/write")
        async def write() -> dict[str, bool]:
            return {"ok": True}

        assert TestClient(app).post("/write", content=b"x", headers={"Content-Type": "text/plain"}).status_code == 200


class TestErrorHandlers:
    def test_unknown_path_returns_json_not_html(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/not-a-real-endpoint")
        assert r.status_code == 404
        assert "error" in r.json(), "404 也要是统一响应体"

    def test_atelier_error_becomes_json(self, atelier_root: Path) -> None:
        from atelier.server.errors import GateBlocked

        app = create_app()

        from atelier.server.gates.base import GateItem, Severity

        report = type("R", (), {"items": [
            GateItem("wordcount", "抖音标题字数", Severity.BLOCK, False, 61, 55, "超了", "删 6 个字")
        ]})()

        @app.get(f"{API_PREFIX}/boom")
        async def boom() -> None:
            raise GateBlocked.from_report(report, hint="改一下")

        body = TestClient(app).get(f"{API_PREFIX}/boom").json()
        assert body["error"]["code"] == "GateBlocked"
        assert body["error"]["hint"] == "改一下"

    def test_internal_error_is_logged_not_leaked(self, atelier_root: Path) -> None:
        from atelier.server import paths as p

        app = create_app()

        @app.get(f"{API_PREFIX}/crash")
        async def crash() -> None:
            raise RuntimeError("内部机密细节")

        r = TestClient(app, raise_server_exceptions=False).get(f"{API_PREFIX}/crash")
        assert r.status_code == 500
        body = r.json()["error"]
        assert body["code"] == "Internal"
        assert "内部机密细节" not in r.text, "内部细节不能回给浏览器"
        log = p.VAR / "atelier-error.log"
        assert log.exists(), "但必须留痕（PRD 原则四）"
        assert "内部机密细节" in log.read_text("utf-8")
        assert "atelier-error.log" in body["hint"]


class TestSettings:
    def test_defaults(self, atelier_root: Path) -> None:
        st = Settings.from_env()
        assert st.host == "127.0.0.1", "SPEC-01 §9：只监听本地"
        assert st.harness_timeout == 120.0
        assert st.task_timeout == 7200.0

    def test_cors_unlocked_flag(self) -> None:
        st = Settings(cors_origins=("https://evil.example.com",))
        assert st.is_cors_locked is False

    def test_mock_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATELIER_MOCK", "1")
        assert Settings.from_env().mock is True
        assert Settings.from_env().harness_name != "mock"

    def test_missing_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        assert "MINIMAX_API_KEY" in Settings().missing_keys(["MINIMAX_API_KEY", "TTS_API_KEY"])
