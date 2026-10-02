"""SPEC-01 §10 / §9 · 运行时配置。

只从环境变量读，不引入配置文件，避免「配置从哪来」变成第二个真相源。
所有开关都带默认值，空项目 clone 下来直接能跑。

环境变量清单：

===========================  ============================================
``ATELIER_ROOT``             仓库根（paths 唯一入口，见 SPEC-01 §1）
``ATELIER_MOCK``             =1 时启用 :class:`MockHarness`（无密钥可跑全链路）
``ATELIER_HOST`` / ``PORT``  服务监听，**只允许 127.0.0.1**
``ATELIER_CORS_ORIGINS``     逗号分隔，默认仅 Vite dev server 两个源
``ATELIER_LOG_DIR``          未捕获异常落点，默认 ``var/``
``ANTHROPIC_API_KEY``        AI 运行时凭证（只读不回传）
``ANTHROPIC_MODEL``          覆盖默认模型
``ATELIER_MASTER_KEY``       ``var/secrets.enc`` 的 AES-GCM 密钥
``ATELIER_HARNESS_TIMEOUT``  单轮生成超时秒数，默认 120（PRD 13 → 504）
``ATELIER_TASK_TIMEOUT``     长任务上限秒数，默认 7200（PRD 13 允许 2 小时）
``ATELIER_DISABLE_CSRF``     =1 时**关掉**跨站写拦截（只给自动化测试用）
===========================  ============================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

__all__ = [
    "DEFAULT_CORS_ORIGINS",
    "TRUTHY",
    "Settings",
    "get_settings",
    "reload_settings",
]

#: PRD 13「CORS 收紧到本地来源」——只放 Vite dev server。
DEFAULT_CORS_ORIGINS: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

#: 允许的跨站来源 scheme。SPEC-01 §8 跨站写拦截只信这三个。
TRUSTED_ORIGIN_SCHEMES: tuple[str, ...] = ("http", "https")

#: 写请求允许的 Content-Type：JSON + 素材上传用的 multipart。
#: 刻意**不允许** ``application/x-www-form-urlencoded``（经典 CSRF 载体，SPEC-01 §8）。
ALLOWED_WRITE_CONTENT_TYPES: tuple[str, ...] = ("application/json", "multipart/form-data")

#: ``Sec-Fetch-Site`` 出现时的放行值（SPEC-01 §9 安全基线）。
TRUSTED_FETCH_SITES: tuple[str, ...] = ("same-origin", "same-site", "none")

TRUTHY = {"1", "true", "yes", "on"}


def _env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v is None:
        return default
    v = v.strip()
    return v or default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in TRUTHY


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """运行期配置快照（不可变；改用 :func:`replace` 或 :func:`reload_settings`）。"""

    # —— 服务 ——
    host: str = "127.0.0.1"  # SPEC-01 §9：只监听本地
    port: int = 8000
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    allowed_write_content_types: tuple[str, ...] = ALLOWED_WRITE_CONTENT_TYPES
    trusted_fetch_sites: tuple[str, ...] = TRUSTED_FETCH_SITES
    disable_csrf: bool = False
    static_dir: Path = field(default_factory=lambda: Path("web") / "dist")

    # —— 运行时选择 ——
    mock: bool = False
    harness_name: str = "claude_sdk"
    harness_timeout: float = 120.0
    task_timeout: float = 7200.0

    # —— 凭证（只读不回传；不进 API 响应）——
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    master_key: str | None = None
    minimax_api_key: str | None = None
    tts_api_key: str | None = None

    # —— 诊断 ——
    log_dir_name: str = "var"
    min_free_mb: int = 2048

    @property
    def is_cors_locked(self) -> bool:
        """CORS 是否只剩本地来源（doctor 第 9 项要显示具体值）。"""
        return set(self.cors_origins) <= set(DEFAULT_CORS_ORIGINS)

    @property
    def has_harness_auth(self) -> bool:
        return bool(self.anthropic_api_key)

    def cors_origin_list(self) -> list[str]:
        return list(self.cors_origins)

    def effective_cors_origins(self) -> tuple[str, ...]:
        """**实际生效**的来源白名单 = 配置值 + 服务自己的地址。

        ``cors_origins`` 默认只列了 Vite dev server 的 :5173，那是「前端另起 dev server、
        跨源调后端」的形态。但 ``atelier web`` 另一种主流用法是**自己 serve 构建好的 SPA**
        （默认 :8000），此时页面与 API 同源，那个来源必须也在白名单里，否则所有写请求 403。

        放在 Settings 上而不是散在 ``main.py`` 里，是为了让**实际生效值只有一处来源**——
        CORS 中间件、跨站写中间件、``/api/health``、``atelier doctor`` 都读它，
        不会出现「中间件放行但 health 报的是另一套」。
        """
        own = tuple(f"http://{h}:{self.port}" for h in (self.host, "127.0.0.1", "localhost"))
        return tuple(dict.fromkeys(self.cors_origins + own))

    def missing_keys(self, names: list[str]) -> list[str]:
        """检查一组环境变量名里哪些没配（技能 required_keys 用）。"""
        return [n for n in names if not _env(n)]

    @classmethod
    def from_env(cls) -> Settings:
        raw_cors = _env("ATELIER_CORS_ORIGINS")
        origins = (
            tuple(o.strip() for o in raw_cors.split(",") if o.strip())
            if raw_cors is not None
            else DEFAULT_CORS_ORIGINS
        )
        static = _env("ATELIER_STATIC_DIR")
        return cls(
            host=_env("ATELIER_HOST", "127.0.0.1") or "127.0.0.1",
            port=int(_env("ATELIER_PORT", "8000") or "8000"),
            cors_origins=origins,
            disable_csrf=_env_bool("ATELIER_DISABLE_CSRF", False),
            static_dir=Path(static) if static else Path("web") / "dist",
            mock=_env_bool("ATELIER_MOCK", False),
            harness_name=_env("ATELIER_HARNESS", "claude_sdk") or "claude_sdk",
            harness_timeout=_env_float("ATELIER_HARNESS_TIMEOUT", 120.0),
            task_timeout=_env_float("ATELIER_TASK_TIMEOUT", 7200.0),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=_env("ANTHROPIC_MODEL"),
            master_key=_env("ATELIER_MASTER_KEY"),
            minimax_api_key=_env("MINIMAX_API_KEY"),
            tts_api_key=_env("TTS_API_KEY") or _env("MINIMAX_API_KEY"),
        )

    def redacted(self) -> dict[str, object]:
        """给 ``/api/health`` 与 doctor 用的掩码视图（PRD §9：密钥只写不回传）。"""
        return {
            "host": self.host,
            "port": self.port,
            "cors_origins": list(self.effective_cors_origins()),
            "cors_locked": self.is_cors_locked,
            "mock": self.mock,
            "harness_name": "mock" if self.mock else self.harness_name,
            "harness_timeout_s": self.harness_timeout,
            "task_timeout_s": self.task_timeout,
            "csrf_enabled": not self.disable_csrf,
            "anthropic_api_key": _mask(self.anthropic_api_key),
            "minimax_api_key": _mask(self.minimax_api_key),
            "tts_api_key": _mask(self.tts_api_key),
            "master_key": _mask(self.master_key),
        }


def _mask(secret: str | None) -> str | None:
    """``sk-ant-xxx…9f2a`` 形式；未配置返回 ``None``（区分「没配」和「配了」）。"""
    if not secret:
        return None
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:6]}…{secret[-4:]}（{len(secret)} 位）"


_cached: Settings | None = None


def get_settings() -> Settings:
    """进程内单例。测试用 :func:`reload_settings` 或 ``monkeypatch`` 后重载。"""
    global _cached
    if _cached is None:
        _cached = Settings.from_env()
    return _cached


def reload_settings(**overrides: object) -> Settings:
    """重新读环境变量并缓存（可传 overrides 强制覆盖，主要给测试用）。"""
    global _cached
    _cached = replace(Settings.from_env(), **overrides) if overrides else Settings.from_env()
    return _cached
