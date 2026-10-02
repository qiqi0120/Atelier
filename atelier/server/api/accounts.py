"""M4 · 账号中心路由（SPEC-14 §1.1 / F-G22~G28）。

诚实边界（D6）：凭证登录真做（密钥经 ``skills.keys`` 加密、状态入
``platform_creds``）；登录态真校验 = adapter.check_auth（读 DB state，
不是标记文件）+ 本地凭证校验，真实有效性以发布时平台反馈为准；
**扫码登录诚实不可用**——需要真实账号环境与风控验证，固定 422。
登录态缓存 60s（F-G27，``?force=1`` 绕过）。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .. import errors
from ..publish.platforms import ADAPTERS, get_adapter
from ..publish.platforms.base import BaseAdapter
from ..skills import keys

router = APIRouter(tags=["accounts"])

__all__ = ["router"]

#: 登录态缓存秒数（F-G27）
CACHE_TTL = 60
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

#: 扫码登录的固定诚实回话
QR_NOTICE = (
    "扫码登录需要本机浏览器自动化与真实账号环境（平台风控限制），"
    "当前支持凭证登录 + 登录态标记；真实扫码按路线图待真实账号环境验证后接入"
)


def _adapter(platform: str) -> BaseAdapter:
    try:
        return get_adapter(platform)
    except errors.ValidationError as exc:
        raise errors.NotFound(
            f"没有这个平台：{platform}",
            detail={"platform": platform, "supported": sorted(ADAPTERS)},
            hint=f"支持的平台：{' / '.join(sorted(ADAPTERS))}",
        ) from exc


def _cred_row(platform: str) -> dict[str, Any] | None:
    from ..core.db import get_conn

    row = get_conn().execute(
        "SELECT * FROM platform_creds WHERE platform = ? ORDER BY created_at DESC LIMIT 1",
        (platform,),
    ).fetchone()
    if row is None:
        return None
    return {
        "account": row["account"] or "",
        "state": row["state"] or "unknown",
        "verified_at": row["verified_at"] or "",
        "created_at": row["created_at"] or "",
        "secret_masked": keys.mask_secret(keys.get_secret(f"PLATFORM_CRED_{platform}") or ""),
    }


@router.get("/accounts", summary="F-G22 平台登录中心（7 平台卡片）")
async def list_accounts(force: str = "") -> dict[str, Any]:

    items: list[dict[str, Any]] = []
    now = time.monotonic()
    for pid in sorted(ADAPTERS):
        adapter = ADAPTERS[pid]
        cred = _cred_row(pid)
        has_cred = cred is not None
        cached = _cache.get(pid)
        if cached and force != "1" and now - cached[0] < CACHE_TTL:
            auth = cached[1]
        else:
            auth = (await adapter.check_auth()).to_dict()
            _cache[pid] = (now, auth)
        # 补机器可读 state 与掩码（前端按 state 上色；掩码只在录入过时返回）
        auth = {**auth, "state": (cred or {}).get("state", "unknown")}
        items.append(
            {
                "platform": pid,
                "display_name": adapter.display_name,
                "forms": list(adapter.forms),
                "title_max": adapter.title_max,
                "body_max": adapter.body_max,
                "has_credential": has_cred,
                "secret_masked": (cred or {}).get("secret_masked", ""),
                "auth": auth,
                "notice": "上限按公开资料设定" if pid in ("ks", "zhihu", "bilibili", "wcs") else "",
            }
        )
    return {
        "items": items,
        "total": len(items),
        "qr_login": {"supported": False, "notice": QR_NOTICE},
        "verify_notice": "登录态校验读取本地凭证状态；真实有效性以发布时平台反馈为准（当前发布为 dry-run）",
    }


class CredentialBody(BaseModel):
    account: str = ""
    secret: str | None = None  # 留空/缺省 = 不覆盖


@router.post("/accounts/{platform}/credential", summary="F-G25 录入凭证（密钥加密存储，掩码回显）")
def post_credential(platform: str, body: CredentialBody) -> dict[str, Any]:
    _adapter(platform)  # 未知平台 404
    existing = _cred_row(platform)
    if (body.secret is None or not body.secret.strip()) and existing is not None:
        return {"ok": True, "unchanged": True, "credential": {k: v for k, v in existing.items()}}
    secret = (body.secret or "").strip()
    if not secret:
        raise errors.ValidationError(
            "secret 不能为空（首次录入）",
            detail={"platform": platform},
            hint="填该平台的登录凭证（cookie/token/密钥），保存后点「验证」",
        )
    if len(secret) > 8000:
        raise errors.ValidationError("secret 过长（>8000 字符）", detail={"max": 8000})
    info = keys.set_secret(f"PLATFORM_CRED_{platform}", secret, platform=platform)
    from ..core.db import db_session, utcnow

    now = utcnow()
    with db_session() as conn:
        conn.execute("DELETE FROM platform_creds WHERE platform = ?", (platform,))
        conn.execute(
            "INSERT INTO platform_creds (id, platform, account, secret_ref, state, verified_at, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (f"cred-{platform}", platform, body.account.strip()[:80],
             f"PLATFORM_CRED_{platform}", "unknown", "", now),
        )
    cred = _cred_row(platform)
    assert cred is not None
    cred["secret_masked"] = info.masked
    return {"ok": True, "unchanged": False, "credential": cred}


@router.post("/accounts/{platform}/verify", summary="F-G24 登录态真校验（本地凭证校验，如实标注）")
async def post_verify(platform: str) -> dict[str, Any]:
    adapter = _adapter(platform)
    cred = _cred_row(platform)
    if cred is None:
        raise errors.ValidationError(
            f"{adapter.display_name}还没有录入凭证，无法校验",
            detail={"platform": platform},
            hint="先点「录入凭证」，再回来验证",
        )
    secret = keys.get_secret(f"PLATFORM_CRED_{platform}")
    ok = bool(secret)
    state = "valid" if ok else "expired"
    from ..core.db import db_session, utcnow

    now = utcnow()
    with db_session() as conn:
        conn.execute(
            "UPDATE platform_creds SET state = ?, verified_at = ? WHERE platform = ?",
            (state, now, platform),
        )
    _cache.pop(platform, None)  # 失效缓存，下次读新状态
    auth = (await adapter.check_auth()).to_dict()
    return {
        "ok": ok,
        "state": state,
        "verified_at": now,
        "auth": auth,
        "message": (
            f"{adapter.display_name}凭证本地校验通过（存在且可解密）；"
            "真实有效性以发布时平台反馈为准"
            if ok
            else f"{adapter.display_name}凭证无法读取（可能已清密钥），标记为过期"
        ),
    }


@router.delete("/accounts/{platform}", summary="F-G26 登出：清除凭证与登录态")
def delete_account(platform: str) -> dict[str, Any]:
    _adapter(platform)
    from ..core.db import db_session

    removed_key = keys.delete_secret(f"PLATFORM_CRED_{platform}")
    with db_session() as conn:
        cur = conn.execute("DELETE FROM platform_creds WHERE platform = ?", (platform,))
    _cache.pop(platform, None)
    if cur.rowcount == 0 and not removed_key:
        raise errors.NotFound(
            f"{_adapter(platform).display_name}本来就没有登录记录",
            detail={"platform": platform},
        )
    return {"ok": True, "platform": platform, "logged_out": True}


@router.post("/accounts/{platform}/qr-login", summary="F-G23 扫码登录（当前诚实不可用）")
async def post_qr_login(platform: str) -> dict[str, Any]:
    _adapter(platform)
    raise errors.ValidationError(
        QR_NOTICE,
        detail={"platform": platform, "supported": False},
        hint="先用「录入凭证」+「验证」把登录态配起来；真实扫码待真实账号环境验证",
    )
