"""SPEC-01 §2 · 错误码 → 人话。

PRD 原则四：失败要留痕，不许只显示「失败」。所以每个错误都必须同时给出：

- ``code``    机器可读，前端分支判断用
- ``message`` 人话，直接可展示
- ``detail``  结构化上下文（如 ``gate_items``、stderr 摘要）
- ``hint``    下一步怎么做

统一响应体：``{"error": {code, message, detail, hint}}``。
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

__all__ = [
    "ERRORS",
    "AtelierError",
    "CrossSiteWriteBlocked",
    "GateBlocked",
    "HarnessAuthError",
    "HarnessError",
    "HarnessTimeout",
    "NotFound",
    "PathEscapeError",
    "PlatformAuthExpired",
    "PlatformSmsWall",
    "ProfileNotFound",
    "PublishFailed",
    "SecretScanFailed",
    "SessionBusy",
    "SkillMissingKey",
    "SkillNotFound",
    "SkillRunFailed",
    "SnapshotStale",
    "SystemFileProtected",
    "ValidationError",
    "error_response",
    "http_exception_response",
    "register_exception_handlers",
    "to_body",
]


class AtelierError(Exception):
    """Atelier 错误基类。

    子类通过类属性覆盖 ``code`` / ``http`` / ``default_message`` / ``default_hint``，
    构造时可逐条覆盖 message / detail / hint。
    """

    code: str = "AtelierError"
    http: int = 500
    default_message: str = "出错了"
    default_hint: str | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
        hint: str | None | object = ...,  # type: ignore[assignment]
    ) -> None:
        self.message = message if message is not None else self.default_message
        self.detail: dict[str, Any] = dict(detail or {})
        self.hint: str | None = self.default_hint if hint is ... else hint  # type: ignore[assignment]
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """SPEC-01 §2 冻结形状：``{code, message, detail, hint}``。"""
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "hint": self.hint,
        }

    def to_body(self) -> dict[str, Any]:
        """统一响应体外壳。"""
        return {"error": self.to_dict()}

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"{type(self).__name__}(code={self.code!r}, http={self.http}, message={self.message!r})"


class PathEscapeError(AtelierError):
    """外部传入路径逃出了允许的 base 目录（含 symlink 逃逸）。"""

    code = "PathEscapeError"
    http = 400
    default_message = "路径超出允许范围"
    default_hint = "只能访问工作台自己的目录（outputs / profiles），不能用 .. 或绝对路径"


class ValidationError(AtelierError):
    code = "ValidationError"
    http = 422
    default_message = "参数不合法"
    default_hint = "按提示修正后重试"


class NotFound(AtelierError):
    code = "NotFound"
    http = 404
    default_message = "找不到该项目"
    default_hint = "检查项目名是否拼错，或在内容库里重新选择一个项目"


class ProfileNotFound(AtelierError):
    code = "ProfileNotFound"
    http = 404
    default_message = "画像不存在或已删除"
    default_hint = "到「画像」页新建一个，或切换到通用模式"


class SessionBusy(AtelierError):
    """PRD F-B12：同一 session 同时只允许一个活跃 turn。"""

    code = "SessionBusy"
    http = 409
    default_message = "该会话正在被另一个窗口生成"
    default_hint = "先在另一个窗口点「停止生成」，或等那一轮跑完"


class HarnessError(AtelierError):
    code = "HarnessError"
    http = 502
    default_message = "AI 运行时连接失败"
    default_hint = "跑 `atelier doctor` 看环境诊断；已生成部分不会丢"


class HarnessAuthError(AtelierError):
    code = "HarnessAuthError"
    http = 502
    default_message = "ANTHROPIC_API_KEY 未配置或无效"
    default_hint = "到「设置」页填入 ANTHROPIC_API_KEY（只写不回传）"


class HarnessTimeout(AtelierError):
    """PRD 13：AI 生成 > 120s → 504。"""

    code = "HarnessTimeout"
    http = 504
    default_message = "AI 生成超时（> 120s）"
    default_hint = "把需求拆小一点再试；已生成内容在会话里不会丢"


class GateBlocked(AtelierError):
    """硬门禁未通过。**必须**带 ``detail.gate_items``（SPEC-01 §2）。"""

    code = "GateBlocked"
    http = 422
    default_message = "硬门禁未通过"
    default_hint = "按每项的 fix_hint 改后重发"

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
        hint: str | None | object = ...,  # type: ignore[assignment]
    ) -> None:
        super().__init__(message, detail=detail, hint=hint)
        if not self.detail.get("gate_items"):
            raise ValueError("GateBlocked 必须带 detail.gate_items（SPEC-01 §2）")

    @classmethod
    def from_report(cls, report: Any, *, message: str | None = None, hint: str | None = None) -> GateBlocked:
        """从 ``gates.base.GateReport`` 构造，保留逐项结果。"""
        items = [i.to_dict() for i in getattr(report, "items", [])]
        failed = [i for i in items if not i.get("passed")]
        text = message or f"硬门禁未通过：{len(failed)} 项"
        if failed:
            first = failed[0]
            text = f"硬门禁未通过：{first.get('label')} {first.get('actual')}/{first.get('limit')}"
        return cls(
            text,
            detail={"gate_items": items, "failed": [i.get("gate") for i in failed]},
            hint=hint or (failed[0].get("fix_hint") if failed else None) or cls.default_hint,
        )


class SkillMissingKey(AtelierError):
    code = "SkillMissingKey"
    http = 409
    default_message = "缺少密钥，无法运行该技能"
    default_hint = "到「设置」页补齐密钥后重试（密钥只写不回传）"


class SkillNotFound(AtelierError):
    code = "SkillNotFound"
    http = 404
    default_message = "找不到该技能"
    default_hint = "在技能库里搜一下触发语，或看能力地图里标灰的接入中技能"


class SkillRunFailed(AtelierError):
    code = "SkillRunFailed"
    http = 500
    default_message = "技能执行失败"
    default_hint = "看 detail.stderr 摘要；也可跑 `atelier doctor` 确认依赖齐全"


class PlatformAuthExpired(AtelierError):
    code = "PlatformAuthExpired"
    http = 409
    default_message = "登录态已过期，需重新扫码"
    default_hint = "到「设置 → 平台账号」重新登录后重发"


class PlatformSmsWall(AtelierError):
    code = "PlatformSmsWall"
    http = 202
    default_message = "平台要求短信验证码，等待中"
    default_hint = "需要在 5 分钟内填入收到的验证码"


class PublishFailed(AtelierError):
    code = "PublishFailed"
    http = 502
    default_message = "发布失败"
    default_hint = "看 detail.error_code 判断是登录态还是内容问题；草稿已保留，可重发"


class SystemFileProtected(AtelierError):
    """PRD F-G7：``.session/`` / ``.index.json`` / ``.atelier*`` 禁止删除。"""

    code = "SystemFileProtected"
    http = 403
    default_message = "系统文件，禁止删除"
    default_hint = "只删成品/素材里的内容；系统文件由工作台自己维护"


class SnapshotStale(AtelierError):
    """非错误：http 200，body 带 ``stale: true``，回落旧值。"""

    code = "SnapshotStale"
    http = 200
    default_message = "刷新失败，已保留上次快照"
    default_hint = "稍后再点一次刷新"

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["stale"] = True
        return d


class SecretScanFailed(AtelierError):
    """``secret_scan`` 门禁 fail-closed 命中时抛出。"""

    code = "GateBlocked"
    http = 422
    default_message = "内容里检测到疑似密钥，已阻断"
    default_hint = "把密钥移到环境变量/设置页，正文里只留占位符"


class CrossSiteWriteBlocked(AtelierError):
    """跨站写请求被拦截（SPEC-01 §8）。

    **spec 扩展（§11 冻结清单外的新增错误码，待确认）**：SPEC-01 §8 要求跨站写拦截，
    但 §2 的错误码表里没有对应条目。这里补一个机器可读的 code，前端才能区分
    「这是安全拦截，不是业务报错」并给出正确提示。
    """

    code = "CrossSiteWriteBlocked"
    http = 403
    default_message = "跨站写请求被拦截"
    default_hint = "本工作台只接受来自本地前端的写请求（Content-Type: application/json + 可信 Origin）"


#: code → 异常类。给 doctor 与前端文档用；``SecretScanFailed`` 与 ``GateBlocked``
#: 共用 code（它就是 GateBlocked 的一种命中原因），故不进本表。
ERRORS: dict[str, type[AtelierError]] = {
    cls.code: cls
    for cls in (
        PathEscapeError,
        ValidationError,
        NotFound,
        ProfileNotFound,
        SessionBusy,
        HarnessError,
        HarnessAuthError,
        HarnessTimeout,
        GateBlocked,
        SkillMissingKey,
        SkillNotFound,
        SkillRunFailed,
        PlatformAuthExpired,
        PlatformSmsWall,
        PublishFailed,
        SystemFileProtected,
        SnapshotStale,
        SecretScanFailed,
        CrossSiteWriteBlocked,
    )
}


def to_body(exc: AtelierError) -> dict[str, Any]:
    return exc.to_body()


def error_response(exc: AtelierError) -> JSONResponse:
    return JSONResponse(status_code=exc.http, content=exc.to_body())


def http_exception_response(status_code: int, detail: Any, *, hint: str | None = None) -> JSONResponse:
    """把 Starlette/FastAPI 的 HTTPException 也裹进统一响应体。"""
    if isinstance(detail, dict) and "code" in detail:
        return JSONResponse(status_code=status_code, content={"error": detail})
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": f"HTTP{status_code}",
                "message": str(detail),
                "detail": {},
                "hint": hint,
            }
        },
    )


def register_exception_handlers(app: Any, *, on_internal: Any = None) -> None:
    """把统一错误体挂到 FastAPI app 上。

    ``on_internal(exc) -> str | None`` 用于把未捕获异常的细节落盘并返回落点，
    满足 PRD 原则四「失败要留痕」——但绝不把内部细节回给浏览器。
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException
    from starlette.requests import Request

    @app.exception_handler(AtelierError)
    async def _atelier_error(_req: Request, exc: AtelierError) -> JSONResponse:  # pragma: no cover - 框架路径
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _req_validation(_req: Request, exc: RequestValidationError) -> JSONResponse:  # pragma: no cover
        return error_response(
            ValidationError(
                "请求参数不合法",
                detail={"errors": _jsonable_errors(exc.errors())},
                hint="对照接口文档检查字段名与类型",
            )
        )

    @app.exception_handler(HTTPException)
    async def _http_error(_req: Request, exc: HTTPException) -> JSONResponse:  # pragma: no cover
        return http_exception_response(exc.status_code, exc.detail)

    @app.exception_handler(Exception)
    async def _unhandled(req: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        where = on_internal(exc) if on_internal else None
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "Internal",
                    "message": f"服务内部错误：{type(exc).__name__}",
                    "detail": {"path": str(req.url.path), "type": type(exc).__name__},
                    "hint": f"细节已留痕：{where}" if where else "查看后端日志",
                }
            },
        )


def _jsonable_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """pydantic v2 的 errors() 里可能带 ctx 里的异常对象，转成可 JSON 化形状。"""
    out: list[dict[str, Any]] = []
    for e in errors:
        item = {k: v for k, v in e.items() if k != "ctx"}
        loc = item.get("loc")
        if isinstance(loc, tuple):
            item["loc"] = [str(x) for x in loc]
        out.append(item)
    return out
