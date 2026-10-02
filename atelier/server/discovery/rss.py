"""SPEC-12 §2 · RSS 抓取与解析（RSS 2.0 + Atom，标准库 ``xml.etree``）。

诚实边界：只支持 RSS 2.0 与 Atom 两种格式；解析失败/超时/非 2xx 抛
``DiscoveryFetchFailed`` 附明确原因（SPEC-12 §0 D2），不做静默空结果。
深度加载（F-D6）对 RSS 源就是「再抓一轮并如实报告」，对无 RSS 的源不支持。
"""

from __future__ import annotations

import hashlib
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from atelier.server.core import db

from . import service
from .service import TITLE_MAX, DiscoveryFetchFailed

__all__ = ["FETCH_TIMEOUT", "fetch_all", "fetch_subscription", "parse_feed"]

FETCH_TIMEOUT = 15.0
#: 时间窗（SPEC-12 §0 D4）：无关键词/时间过滤需求时可放宽，抓取窗口固定 7 天
FETCH_WINDOW_DAYS = 7
_UA = "Atelier/1.0 (local content workbench; +http://127.0.0.1)"

_ATOM = "{http://www.w3.org/2005/Atom}"


def _fetch_xml(url: str) -> bytes:
    """GET 拉原始字节（交给 XML 声明自己声明编码）。任何失败都翻成明确原因。"""
    try:
        resp = httpx.get(
            url, timeout=FETCH_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": _UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
        )
    except httpx.TimeoutException as exc:
        raise DiscoveryFetchFailed(
            f"订阅源超时（>{FETCH_TIMEOUT:.0f}s）：{url}",
            detail={"url": url, "reason": "timeout"},
            hint="源站可能慢或不可达；稍后重试或换源",
        ) from exc
    except httpx.HTTPError as exc:
        raise DiscoveryFetchFailed(
            f"订阅源网络错误：{type(exc).__name__}",
            detail={"url": url, "reason": str(exc)[:200]},
            hint="检查 URL 是否可访问；本机需要能直连该地址",
        ) from exc
    if resp.status_code >= 400:
        raise DiscoveryFetchFailed(
            f"订阅源返回 HTTP {resp.status_code}",
            detail={"url": url, "status": resp.status_code},
            hint="确认 URL 还有有效；被墙/限流的源考虑换镜像",
        )
    if not resp.content.strip():
        raise DiscoveryFetchFailed("订阅源返回空内容", detail={"url": url}, hint="确认这是 RSS/Atom 地址")
    return resp.content


def _parse_date(raw: str | None) -> str:
    """RFC822（RSS pubDate）与 ISO8601（Atom updated）都试；解析不了返回 ``""``。"""
    if not raw:
        return ""
    raw = raw.strip()
    try:
        return parsedate_to_datetime(raw).astimezone(UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC).isoformat(timespec="seconds")
    except ValueError:
        return ""


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.itertext()).strip()


def parse_feed(content: bytes) -> list[dict[str, Any]]:
    """解析 RSS 2.0 / Atom → ``[{title, link, summary, published_at, dedup_key}]``。"""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise DiscoveryFetchFailed(
            f"内容不是合法 XML：{exc}",
            detail={"reason": "parse_error"},
            hint="确认这是 RSS 2.0 或 Atom 源；网页 HTML 地址不能当订阅用",
        ) from exc
    tag = root.tag.rsplit("}", 1)[-1].lower()
    items: list[dict[str, Any]] = []
    if tag == "rss":
        for item in root.iter("item"):
            title = _text(item.find("title"))
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "link": _text(item.find("link")),
                    "summary": _text(item.find("description"))[:2000],
                    "published_at": _parse_date(_text(item.find("pubDate"))),
                    "dedup_key": _text(item.find("guid")) or _text(item.find("link"))
                    or hashlib.sha1(title.encode("utf-8")).hexdigest(),
                }
            )
    elif tag == "feed":  # Atom
        for entry in root.iter(f"{_ATOM}entry"):
            title = _text(entry.find(f"{_ATOM}title"))
            if not title:
                continue
            link = ""
            link_el = entry.find(f"{_ATOM}link")
            if link_el is not None:
                link = link_el.get("href", "") or _text(link_el)
            items.append(
                {
                    "title": title,
                    "link": link,
                    "summary": _text(entry.find(f"{_ATOM}summary")) or _text(entry.find(f"{_ATOM}content")),
                    "published_at": _parse_date(
                        _text(entry.find(f"{_ATOM}published")) or _text(entry.find(f"{_ATOM}updated"))
                    ),
                    "dedup_key": _text(entry.find(f"{_ATOM}id")) or link
                    or hashlib.sha1(title.encode("utf-8")).hexdigest(),
                }
            )
    else:
        raise DiscoveryFetchFailed(
            f"不支持的订阅格式：<{root.tag}>",
            detail={"root_tag": root.tag[:120]},
            hint="只支持 RSS 2.0 与 Atom；其他格式请手填条目",
        )
    items = items[:200]  # 单次抓取上限，防异常巨型源
    if not items:
        raise DiscoveryFetchFailed(
            "源里没有可解析的条目", detail={"root_tag": root.tag[:120]}, hint="确认源仍在更新，或改用手填订阅"
        )
    return items


def fetch_subscription(sub: dict[str, Any], *, window_days: int = FETCH_WINDOW_DAYS) -> dict[str, Any]:
    """拉取单个 rss 订阅：抓 → 解析 → 关键词/时间窗过滤 → 去重入库。

    返回 ``{fetched(入池), inserted(新增), filtered(被过滤), parsed(源提供), subscription_id}``。
    """
    if sub["source"] != "rss":
        raise DiscoveryFetchFailed(
            "该订阅是手填类型，没有可抓取的 URL",
            detail={"subscription_id": sub["id"], "source": sub["source"]},
            hint="手填订阅用「添加条目」录入内容；要自动抓取请换成带 RSS 地址的订阅",
        )
    items = parse_feed(_fetch_xml(sub["url"]))
    keywords = service.parse_keywords(",".join(sub["keywords"]) if isinstance(sub["keywords"], list) else sub["keywords"])
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat(timespec="seconds")
    inserted = filtered = 0
    with db.db_session() as conn:
        for it in items:
            haystack = f"{it['title']}\n{it['summary']}"
            if keywords and not any(k in haystack for k in keywords):
                filtered += 1
                continue
            if it["published_at"] and it["published_at"] < cutoff:
                filtered += 1
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO feed_items (id, subscription_id, title, url, summary,"
                " published_at, fetched_at, dedup_key) VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"feed-{uuid.uuid4().hex[:16]}",
                    sub["id"],
                    it["title"][:TITLE_MAX],
                    it["link"][:2000],
                    it["summary"],
                    it["published_at"],
                    db.utcnow(),
                    it["dedup_key"][:256],
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
    service.touch_fetched(sub["id"])
    return {
        "subscription_id": sub["id"],
        "name": sub["name"],
        "parsed": len(items),
        "filtered": filtered,
        "inserted": inserted,
    }


def fetch_all() -> dict[str, Any]:
    """逐个拉 enabled 的 rss 订阅；单个失败不整批失败，逐条如实回报。"""
    subs = service.list_subscriptions(enabled=True, source="rss")["items"]
    results: list[dict[str, Any]] = []
    for sub in subs:
        try:
            results.append({"ok": True, **fetch_subscription(sub)})
        except DiscoveryFetchFailed as exc:
            results.append(
                {"ok": False, "subscription_id": sub["id"], "name": sub["name"],
                 "error": exc.message, "hint": exc.hint}
            )
        except (RuntimeError, OSError, ValueError) as exc:  # 单源异常不拖垮整批，但如实留痕
            results.append(
                {"ok": False, "subscription_id": sub["id"], "name": sub["name"],
                 "error": f"抓取时出现意外错误：{type(exc).__name__}: {exc}"[:200],
                 "hint": "重试一次；持续失败跑 `atelier doctor` 并看服务日志"}
            )
    return {
        "results": results,
        "total": len(results),
        "ok_count": sum(1 for r in results if r["ok"]),
        "inserted": sum(r.get("inserted", 0) for r in results if r["ok"]),
    }
