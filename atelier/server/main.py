"""SPEC-01 §8 · app factory（CORS / 跨站写拦截 / 路由自动发现 / 静态挂载）。

**路由自动发现是本文件存在的关键设计**（并行开发的硬需求）：领域 agent 新增
``atelier/server/api/<域>.py`` 时，只要模块里有模块级 ``router: APIRouter``，
启动时就会被自动挂上，**不需要改本文件**。否则每个域都要动 ``main.py``，
并行写必然冲突。

约定给写 ``api/`` 的 agent：

- 域路由只写自己的子路径（``@router.get("/chat")``），``/api`` 前缀由这里统一加
- 确实要自己控制前缀的模块，写个模块级 ``ROUTER_PREFIX = ""`` 即可
- 挂不上的模块不会让整个服务起不来，原因记在 :data:`ROUTER_ERRORS`，
  并出现在 ``GET /api/meta`` 与 ``atelier doctor`` 里（PRD 原则四：不静默）
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

log = logging.getLogger("atelier.main")

from .. import __version__
from . import paths
from .config import get_settings
from .core import db
from .errors import CrossSiteWriteBlocked, error_response, register_exception_handlers

__all__ = [
    "API_PACKAGE",
    "API_PREFIX",
    "ROUTER_ERRORS",
    "SAFE_METHODS",
    "app",
    "create_app",
]

#: API 前缀（SPEC-01 §8 冻结）
API_PREFIX = "/api"

#: 领域路由包。目录可能还不存在（并行开发中），装载失败要能优雅跳过。
API_PACKAGE = "atelier.server.api"

#: 只读方法，不做跨站写检查
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: 浏览器能不经预检就发出的**危险**方法集合。
#: 注意：HTML 表单只支持 GET/POST，所以真正需要靠 Content-Type 兜底的只有 POST
#: （form-urlencoded / multipart / text/plain 都是 CORS simple request，不预检）。
#: PUT/PATCH/DELETE 无法由表单发出，必然触发 CORS 预检，不该因为「没带 Content-Type」
#: 就把 curl / 第三方客户端的正常删除误伤成 403。
FORM_CAPABLE_METHODS = frozenset({"POST"})

#: 模块名 → 装载失败原因。给 /api/meta 与 doctor 看。
ROUTER_ERRORS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# 跨站写拦截（SPEC-01 §8 / §9）
# ---------------------------------------------------------------------------


class CrossSiteWriteMiddleware(BaseHTTPMiddleware):
    """写请求（非 GET/HEAD/OPTIONS）必须同时满足三条，缺一即 403：

    1. ``Content-Type`` 在白名单里（默认只允许 ``application/json`` 与
       ``multipart/form-data``——后者是素材上传 PRD F-B2 必需；刻意**不允许**
       ``application/x-www-form-urlencoded``，那是经典 CSRF 载体）
    2. ``Origin`` 存在时必须在 CORS 白名单里，**或是本次请求自己的来源**（同源，见
       :meth:`_is_same_origin`——``atelier web`` 自带 SPA 时页面与 API 同源）
    3. ``Sec-Fetch-Site`` 存在时必须在可信集合里（现代浏览器自带这层）

    没有 ``Origin`` 头时放行：本地工具（curl / CLI）不发送它，而真正的浏览器
    跨站写一定会发。
    """

    def __init__(self, app: Any, *, allowed_content_types: tuple[str, ...], allowed_origins: tuple[str, ...],
                 trusted_fetch_sites: tuple[str, ...], enabled: bool = True) -> None:
        super().__init__(app)
        self.allowed_content_types = tuple(c.lower() for c in allowed_content_types)
        self.allowed_origins = set(allowed_origins)
        self.trusted_fetch_sites = set(trusted_fetch_sites)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self.enabled or request.method in SAFE_METHODS:
            return await call_next(request)

        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()

        # 跨站伪造的真实风险只在「浏览器不预检就能发出去的请求」上：
        #   - HTML 表单只能发 GET/POST
        #   - 表单能发的 Content-Type 属于 CORS simple request（不预检）
        #     → form-urlencoded / multipart / text/plain，一律必须拦
        # DELETE/PUT/PATCH 无法由表单发出，必然触发 CORS 预检，
        # 因此无 body 的 DELETE（内容落在 query 上）不该被误伤，
        # 否则 curl / 第三方客户端的正常删除会莫名 403。
        if request.method in FORM_CAPABLE_METHODS:
            if ctype not in self.allowed_content_types:
                return self._reject(
                    request,
                    reason="content_type_not_allowed",
                    got=ctype or "(空)",
                    expect=" / ".join(self.allowed_content_types),
                )
        else:
            # PUT/PATCH/DELETE：无法由表单发出（必然预检），因此无 body 时放行；
            # 有 body 则仍必须是 JSON，防止后续有人给它加 simple-request 语义。
            if ctype and ctype not in self.allowed_content_types:
                return self._reject(
                    request,
                    reason="content_type_not_allowed",
                    got=ctype,
                    expect=" / ".join(self.allowed_content_types) + "（无 body 可省略）",
                )

        origin = (request.headers.get("origin") or "").strip()
        if origin and origin not in self.allowed_origins and not self._is_same_origin(request, origin):
            return self._reject(request, reason="origin_not_allowed", got=origin, expect="见 CORS 白名单")

        site = (request.headers.get("sec-fetch-site") or "").strip().lower()
        if site and site not in self.trusted_fetch_sites:
            return self._reject(request, reason="fetch_site_not_allowed", got=site,
                                expect=" / ".join(self.trusted_fetch_sites))

        return await call_next(request)

    @staticmethod
    def _is_same_origin(request: Request, origin: str) -> bool:
        """``Origin`` 与本次请求自己的 ``host:port`` 相同 → **同源**，不是跨站写。

        为什么要这条：``cors_origins`` 默认只列了 Vite 开发服务器
        （``localhost:5173`` / ``127.0.0.1:5173``），那是「前端另起 dev server、
        跨源调后端」的形态。但 ``atelier web`` 另一种主流用法是**自己 serve 构建好的
        SPA**（默认 :8000 / 实跑 :7300），此时页面与 API 同源，所有写请求都会带着
        ``Origin: http://127.0.0.1:7300`` 撞上白名单 → 全部 403
        （对话发不出、技能跑不了、改画像存不进去）。

        这条不放宽安全性：同源请求本来就**不可能**是别的网站发起的跨站写
        （浏览器对跨源写会强制带目标站 Origin，且表单无法伪造），
        且此时 ``Sec-Fetch-Site`` 本就是 ``same-origin``——已在可信集合里。
        """
        host = (request.headers.get("host") or "").strip()
        if not host:
            return False
        return origin == f"{request.url.scheme}://{host}"

    def _reject(self, request: Request, *, reason: str, got: str, expect: str) -> JSONResponse:
        err = CrossSiteWriteBlocked(
            "跨站写请求被拦截",
            detail={
                "reason": reason,
                "path": request.url.path,
                "method": request.method,
                "got": got,
                "expect": expect,
            },
        )
        return error_response(err)


# ---------------------------------------------------------------------------
# 路由自动发现
# ---------------------------------------------------------------------------


def _autoload_routers(app: FastAPI, *, package: str | None = None, prefix: str = API_PREFIX) -> list[str]:
    """扫描 ``api/`` 下所有模块，把模块级 ``router`` 挂到 app 上。

    返回成功挂载的模块名列表。单个模块装载失败**不影响服务启动**，原因进
    :data:`ROUTER_ERRORS`。

    ``package=None`` 时读模块级 :data:`API_PACKAGE`（在调用时读，不是定义时，
    这样测试可以把它指到临时包上，不必往真实 ``api/`` 目录里塞文件）。
    """
    loaded: list[str] = []
    target_package = package or API_PACKAGE
    try:
        pkg = importlib.import_module(target_package)
    except ModuleNotFoundError:
        return loaded  # api/ 目录还没建（并行开发中），优雅跳过

    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue  # _shared / __init__ 不算域路由
        mod_name = f"{target_package}.{info.name}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 - 一个域坏了不能拖垮整个服务
            ROUTER_ERRORS[mod_name] = f"{type(exc).__name__}: {exc}"
            continue

        router = getattr(mod, "router", None)
        if not isinstance(router, APIRouter):
            ROUTER_ERRORS[mod_name] = "模块里没有模块级 router: APIRouter，已跳过"
            continue
        mod_prefix = getattr(mod, "ROUTER_PREFIX", prefix)
        app.include_router(router, prefix=mod_prefix)
        loaded.append(mod_name)
    return loaded


# ---------------------------------------------------------------------------
# app factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> Any:
    """启动：确保目录 + 迁移 schema；关闭：释放已创建的 harness。"""
    paths.ensure_dirs()
    try:
        db.init_db()
    except Exception as exc:  # noqa: BLE001 - 库起不来要说清，而不是让整个服务挂掉
        ROUTER_ERRORS["core.db"] = f"{type(exc).__name__}: {exc}"
    try:
        yield
    finally:
        from .harness import registry as harness_registry

        h = harness_registry.current_harness()
        if h is not None:
            await h.aclose()


def create_app(*, settings: Any = None) -> FastAPI:
    """构造 app。``settings=None`` 时读环境变量。"""
    st = settings or get_settings()

    app = FastAPI(
        title="Atelier",
        version=__version__,
        summary="面向社交媒体创作者的私有内容工作台",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,  # 全部文档端点都收在 /api 下
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=_lifespan,
    )

    # 1) 统一错误体（PRD 原则四：失败要留痕）
    def _log_internal(exc: Exception) -> str | None:
        """未捕获异常落盘，返回落点路径（不把内部细节回给浏览器）。"""
        import traceback

        try:
            paths.VAR.mkdir(parents=True, exist_ok=True)
            log = paths.VAR / "atelier-error.log"
            with log.open("a", encoding="utf-8") as f:
                f.write(f"--- {db.utcnow()} {type(exc).__name__}: {exc}\n")
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
            return paths.rel_to_root(log)
        except OSError:
            return None

    register_exception_handlers(app, on_internal=_log_internal)

    # 2) CORS：只放本地来源（PRD 13）
    #    白名单带上**服务自己的地址**（见 Settings.effective_cors_origins）：
    #    `atelier web` 会 serve 构建好的 SPA，页面与 API 同源，而默认 cors_origins
    #    只有 Vite dev server 的 :5173。真正兜底的是
    #    CrossSiteWriteMiddleware._is_same_origin（按请求实际 Host 判同源），
    #    但配置本身也要如实，且三处（CORS / 跨站写 / health）必须是同一份值。
    cors_origins = st.effective_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Confirm-Token"],
        expose_headers=["Content-Range", "Accept-Ranges"],
    )

    # 3) 跨站写拦截（CORS 之外再加一层，不依赖浏览器配合）
    app.add_middleware(
        CrossSiteWriteMiddleware,
        allowed_content_types=st.allowed_write_content_types,
        allowed_origins=cors_origins,
        trusted_fetch_sites=st.trusted_fetch_sites,
        enabled=not st.disable_csrf,
    )

    # 4) 领域路由自动发现（并行开发关键：新增域不需要改本文件）
    loaded = _autoload_routers(app)

    # 5) 地基层自己的两个端点（域路由之外的最小契约）
    @app.get(f"{API_PREFIX}/health", tags=["meta"], summary="健康检查（atelier ping 用）")
    async def health() -> dict[str, Any]:
        info: dict[str, Any] = {
            "ok": True,
            "version": __version__,
            "root": paths.rel_to_root(paths.ROOT),
            "routers": loaded,
            "config": st.redacted(),
        }
        if ROUTER_ERRORS:
            info["router_errors"] = dict(ROUTER_ERRORS)
        try:
            from .harness import registry as hr

            h = hr.current_harness()
            if h is not None:
                report = await h.health()
                info["harness"] = report.to_dict()
            else:
                info["harness"] = {
                    "name": "mock" if st.mock else st.harness_name,
                    "ok": None,
                    "message": "尚未创建（首次对话时才实例化）",
                }
        except Exception as exc:  # noqa: BLE001 - 健康检查不能因为 provider 坏掉就 500
            info["harness"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            info["ok"] = False
        return info

    @app.get(f"{API_PREFIX}/meta", tags=["meta"], summary="门禁清单 + 已挂路由")
    async def meta() -> dict[str, Any]:
        from .gates.registry import list_gates, registry_errors

        return {
            "version": __version__,
            "gates": list_gates(),
            "gate_errors": registry_errors(),
            "routers": loaded,
            "router_errors": dict(ROUTER_ERRORS),
            "config": st.redacted(),
        }

    # 6) 静态前端：必须最后挂，否则会把 /api 路由盖掉
    dist = st.static_dir if st.static_dir.is_absolute() else paths.ROOT / st.static_dir
    if dist.is_dir():
        # SPA fallback：深链（/library、/publish…）直接刷新必须回 index.html，
        # 否则 StaticFiles 会对所有前端路由返 404。API 与 /api/docs 已在前面注册，
        # 不会落到这里。


        class SPAStaticFiles(StaticFiles):
            async def get_response(self, path: str, scope: Any) -> Response:
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if exc.status_code != 404 or path.startswith("api"):
                        raise
                    # 只对「页面导航」回 index.html。子资源（<img>/<script>/<link>，
                    # 即 Accept 里不要 text/html）必须保持 404，否则缺失的图片会
                    # 悄悄返回一份 HTML，浏览器报出一堆看不懂的解析错误。
                    headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                               for k, v in scope.get("headers", [])}
                    accept = headers.get("accept", "")
                    if "text/html" not in accept:
                        raise
                    return await super().get_response("index.html", scope)

        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="web")
        log.info("静态前端已挂载：%s（SPA fallback 开启，深链不 404）", dist)
    else:
        @app.get("/", include_in_schema=False)
        async def _no_frontend() -> dict[str, Any]:
            return {
                "atelier": __version__,
                "note": f"前端未构建（没找到 {paths.rel_to_root(dist)}）；开发时用 Vite dev server（默认 5173）",
                "api": f"{API_PREFIX}/docs",
            }

    return app


#: uvicorn 入口：``uvicorn atelier.server.main:app``
app = create_app()
