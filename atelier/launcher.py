"""启动器：把「起服务」这件事从 CLI 里剥出来，便于单测与复用。

职责很窄，就三件事：

1. 确保目录/建表（:func:`prepare`）——先于一切，保证起服务时 ``var/`` 就在
2. 检查端口（:func:`is_port_free`）——doctor 第 16 项要用
3. 拉起 uvicorn（:func:`launch_web`）
"""

from __future__ import annotations

import socket
import sys
from typing import Any

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "is_port_free", "launch_web", "prepare"]

#: SPEC-01 §9：只监听 127.0.0.1，不对公网暴露
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def prepare() -> None:
    """建目录 + 迁移 schema。可以重复跑。"""
    from .server import paths
    from .server.core import db

    paths.ensure_dirs()
    db.init_db()


def is_port_free(port: int, host: str = DEFAULT_HOST) -> bool:
    """端口能否绑定。用于 doctor 报「端口被占」并给出占用方建议。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def launch_web(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    reload: bool = False,
    log_level: str = "info",
    extra: dict[str, Any] | None = None,
) -> None:
    """起服务。``reload=True`` 需要传字符串形式的 import 路径（uvicorn 的要求）。"""
    import uvicorn

    # CLI 的 --host/--port 必须**同步回运行期配置**，否则：
    #   - main.py 组装 CORS 白名单时用的是 settings.port，会写成错端口
    #   - /api/health 与 `atelier doctor` 报出来的端口是假的
    # 真正兜底的是 CrossSiteWriteMiddleware._is_same_origin（按请求实际 Host 判同源），
    # 但配置本身也得如实。
    from .server.config import reload_settings

    reload_settings(host=host, port=port)

    prepare()
    if reload:
        target = "atelier.server.main:app"
        uvicorn.run(target, host=host, port=port, reload=True, log_level=log_level)
        return

    from .server.main import app

    kwargs: dict[str, Any] = {"host": host, "port": port, "log_level": log_level, **(extra or {})}
    print(
        f"Atelier 已启动 → http://{host}:{port}/  （API 文档 {host}:{port}/api/docs，Ctrl-C 停止）",
        file=sys.stderr,
    )
    uvicorn.run(app, **kwargs)
