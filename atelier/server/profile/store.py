"""SPEC-02 §3 · 画像双写存储（SQLite 为准 + ``profiles/<id>.md`` 人可读可手改）。

**双写策略**（spec 原文）：

- **SQLite 是准的**：查询、切换、完整性计算全走库，快且一致。
- **md 是给人看的**：可手改、可导出、可进版本库。**用户手改 md 后重启会被反向导入**——
  判据是 frontmatter 里的 ``updated_at`` 比库里的新。

导出格式严格按 SPEC-02 §3：

```markdown
---
id: ai-efficiency
name: AI 效率观察
platforms: [xhs, dy, gzh]
general_mode: false
updated_at: 2026-10-02T15:00:00Z
---

## identity
（正文）
## style
## audience
## platform_rules
## preferences

## memories
- [归因] 反常识 + 亲手实测组合，中位播放是均值 3.8 倍
```

**两处必要的补记（对 spec 的可解释扩展，报告里已登记）**：

1. frontmatter 多了 ``created_at``。少它的话从 md 反向导入会丢掉创建时间，
   列表排序与「最近更新」都会跟着失真。
2. 每条记忆在行尾挂一个 HTML 注释 ``<!-- id=… created=… adopted=… -->``。
   渲染出来看不见，手改仍然只改文字那一段；没有注释的手写行会被当成新记忆
   （新 id、当前时间），**不会**丢用户写的内容。
"""

from __future__ import annotations

import logging
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..core import db
from ..core.models import DIMENSION_LABELS, Memory, Profile, to_dict, utcnow
from ..errors import ProfileNotFound, ValidationError

log = logging.getLogger("atelier.profile.store")

__all__ = [
    "PROFILE_FIELDS",
    "TEXT_DIMS",
    "add_memory",
    "create_profile",
    "delete_memory",
    "delete_profile",
    "ensure_synced",
    "get_profile",
    "list_memories",
    "list_profiles",
    "new_profile_id",
    "parse_markdown",
    "profile_dict",
    "profile_md_path",
    "render_markdown",
    "sessions_using",
    "sync_from_disk",
    "to_dict",
    "update_profile",
    "utcnow",
    "wizard_marker",
]

#: 五个文本维度（``memories`` 是列表，单独处理）
TEXT_DIMS: tuple[str, ...] = ("identity", "style", "audience", "platform_rules", "preferences")

#: PATCH 允许改的字段（``id`` / ``created_at`` 不开放）
PROFILE_FIELDS: frozenset[str] = frozenset(
    {"name", "platforms", *TEXT_DIMS, "general_mode"}
)

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SEC_RE = re.compile(r"^##\s+([A-Za-z_][\w-]*)\s*$", re.MULTILINE)
_MEMO_META_RE = re.compile(r"\s*<!--\s*(?P<meta>[^>]*?)\s*-->\s*$")
_MEMO_SRC_RE = re.compile(r"^-\s*\[(?P<src>[^\]]*)\]\s*(?P<text>.*)$")

#: 进程内「已做过一次反向导入」的闸（只防重复 IO，不缓存任何画像内容）
_SYNCED = False


# ---------------------------------------------------------------------------
# 时间 / id
# ---------------------------------------------------------------------------


def _parse_ts(raw: str | None) -> datetime | None:
    """宽松解析 ISO8601（容忍 spec 示例里的 ``Z`` 后缀，py310 的 fromisoformat 不吃）。"""
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def new_profile_id(name: str) -> str:
    """新画像 id。名字里有 ASCII 就用 slug（人读得懂），否则退回随机 id。"""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
    if len(slug) >= 2:
        suffix = secrets.token_hex(2)
        candidate = f"{slug}-{suffix}"
        if get_profile_or_none(candidate) is None:
            return candidate
    while True:
        candidate = _new_id("profile")
        if get_profile_or_none(candidate) is None:
            return candidate


def _new_memory_id() -> str:
    return _new_id("mem")


# ---------------------------------------------------------------------------
# md 路径与渲染
# ---------------------------------------------------------------------------


def profile_md_path(profile_id: str) -> Path:
    """``profiles/<id>.md``。id 走白名单校验 + :func:`resolve_inside` 防穿越。"""
    paths.validate_id(profile_id, "profile_id")
    return paths.resolve_inside(paths.PROFILES, f"{profile_id}.md")


def _fmt_platforms(platforms: list[str]) -> str:
    return "[" + ", ".join(str(p).strip() for p in platforms if str(p).strip()) + "]"


def _parse_platforms(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text.strip():
        return []
    return [p.strip().strip("'\"") for p in text.split(",") if p.strip()]


def _fmt_ts(dt: datetime | None) -> str:
    """frontmatter 里统一写 UTC 的 ``Z`` 形式（与 spec 示例一致）。"""
    if dt is None:
        return ""
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def render_markdown(profile: Profile) -> str:
    """渲染成 spec §3 的 md。人可读、可手改、可直接进版本库。"""
    lines = [
        "---",
        f"id: {profile.id}",
        f"name: {profile.name}",
        f"platforms: {_fmt_platforms(profile.platforms)}",
        f"general_mode: {'true' if profile.general_mode else 'false'}",
        f"created_at: {_fmt_ts(profile.created_at)}",
        f"updated_at: {_fmt_ts(profile.updated_at)}",
        "---",
        "",
    ]
    for dim in TEXT_DIMS:
        lines += [f"## {dim}", "", (getattr(profile, dim) or "").strip(), ""]
    lines += ["## memories", ""]
    if profile.memories:
        for m in profile.memories:
            meta = f"id={m.id} created={_fmt_ts(m.created_at)} adopted={'1' if m.adopted else '0'}"
            lines.append(f"- [{m.source}] {m.text} <!-- {meta} -->")
    else:
        lines.append("（暂无）")
    lines.append("")
    return "\n".join(lines)


def parse_markdown(text: str) -> dict[str, Any]:
    """把 md 解析回「画像字段 + 记忆」。容错：坏行跳过，绝不抛裸异常。

    返回值可直接喂给 :func:`update_profile` / :func:`add_memory`。
    """
    raw = str(text or "")
    fm_match = _FM_RE.match(raw)
    body = raw[fm_match.end():] if fm_match else raw
    fm: dict[str, str] = {}
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ":" not in line or line.lstrip().startswith("#"):
                continue
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()

    sections: dict[str, str] = {}
    matches = list(_SEC_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[m.group(1).lower()] = body[m.end():end].strip()

    fields: dict[str, Any] = {}
    if fm.get("name"):
        fields["name"] = fm["name"].strip()
    if "platforms" in fm:
        fields["platforms"] = _parse_platforms(fm["platforms"])
    if "general_mode" in fm:
        fields["general_mode"] = fm["general_mode"].strip().lower() in ("1", "true", "yes", "on")
    for dim in TEXT_DIMS:
        if dim in sections and sections[dim] not in ("（暂无）",):
            fields[dim] = sections[dim]

    memories: list[dict[str, Any]] = []
    for line in sections.get("memories", "").splitlines():
        item = line.strip()
        if not item or item == "（暂无）" or not item.startswith("-"):
            continue
        parsed = _MEMO_SRC_RE.match(item)
        if not parsed:
            continue
        text_value = parsed.group("text").strip()
        meta_match = _MEMO_META_RE.search(text_value)
        meta: dict[str, str] = {}
        if meta_match:
            text_value = text_value[: meta_match.start()].strip()
            for kv in meta_match.group("meta").split():
                k, _, v = kv.partition("=")
                if k:
                    meta[k] = v
        if not text_value:
            continue
        memories.append(
            {
                "id": meta.get("id") or _new_memory_id(),
                "text": text_value,
                "source": (parsed.group("src").strip() or "手动"),
                "created_at": _iso(_parse_ts(meta.get("created"))) or db.utcnow(),
                "adopted": meta.get("adopted", "1") != "0",
            }
        )

    return {
        "fields": fields,
        "memories": memories,
        "updated_at": _iso(_parse_ts(fm.get("updated_at"))),
        "created_at": _iso(_parse_ts(fm.get("created_at"))),
        "id": (fm.get("id") or "").strip(),
    }


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------


def _load_memories(conn: sqlite3.Connection, profile_id: str) -> list[Memory]:
    rows = conn.execute(
        "SELECT id, text, source, adopted, created_at FROM memories "
        "WHERE profile_id=? ORDER BY created_at ASC, rowid ASC",
        (profile_id,),
    ).fetchall()
    out: list[Memory] = []
    for r in rows:
        try:
            out.append(
                Memory(
                    id=r["id"],
                    text=r["text"] or "",
                    source=r["source"] or "手动",
                    created_at=r["created_at"] or db.utcnow(),
                    adopted=bool(r["adopted"]),
                )
            )
        except ValueError as exc:  # pydantic 校验/时间解析失败：坏行跳过，但留痕
            log.warning("跳过一条坏记忆 %s: %s", r["id"], exc)
            continue
    return out


def _row_to_profile(conn: sqlite3.Connection, row: sqlite3.Row) -> Profile:
    return Profile(
        id=row["id"],
        name=row["name"] or row["id"],
        platforms=list(db.loads(row["platforms"], []) or []),
        identity=row["identity"] or "",
        style=row["style"] or "",
        audience=row["audience"] or "",
        platform_rules=row["platform_rules"] or "",
        preferences=row["preferences"] or "",
        general_mode=bool(row["general_mode"]),
        created_at=row["created_at"] or db.utcnow(),
        updated_at=row["updated_at"] or db.utcnow(),
        memories=_load_memories(conn, row["id"]),
    )


def get_profile_or_none(profile_id: str) -> Profile | None:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    return _row_to_profile(conn, row) if row is not None else None


def get_profile(profile_id: str) -> Profile:
    """取画像。不存在抛 :class:`ProfileNotFound`（404，前端据此切到通用模式）。"""
    p = get_profile_or_none(profile_id)
    if p is None:
        raise ProfileNotFound(
            "画像不存在或已删除",
            detail={"profile_id": profile_id},
            hint="到「画像」页新建一个，或切换到通用模式继续创作",
        )
    return p


def list_profiles() -> list[Profile]:
    """全部画像，按 ``updated_at`` 倒序（spec §5 列表要求）。"""
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM profiles").fetchall()
    items = [_row_to_profile(conn, r) for r in rows]
    items.sort(key=lambda p: (p.updated_at, p.created_at), reverse=True)
    return items


def sessions_using(profile_id: str) -> int:
    """有多少会话引用了这个画像。>0 时删画像要 409（spec §5）。"""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE profile_id=?", (profile_id,)
    ).fetchone()
    return int(row["n"] if row else 0)


# ---------------------------------------------------------------------------
# 写
# ---------------------------------------------------------------------------


def _write_md(profile: Profile) -> Path:
    """把画像写到 ``profiles/<id>.md``。写失败不静默：画像正文已经进库了，
    但导出/手改链路会断，因此这里抛 :class:`ValidationError` 让调用方知道。"""
    path = profile_md_path(profile.id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(profile), encoding="utf-8")
    except OSError as exc:
        raise ValidationError(
            "画像已保存到数据库，但写 profiles/<id>.md 失败",
            detail={"profile_id": profile.id, "error": f"{type(exc).__name__}: {exc}"},
            hint="检查 profiles/ 目录是否可写；导出功能此刻不可用",
        ) from exc
    return path


def _update_locked(profile: Profile) -> Profile:
    """把 :class:`Profile` 整体覆盖进库，并**把新时间戳同步回对象**。

    同步回对象是必须的：``_write_md`` 紧接着要用 ``profile.updated_at`` 写 frontmatter。
    不同步的话 md 会一直带着旧时间戳，反向导入的「md 更新才导入」判据就废了。
    """
    now = db.utcnow()
    conn = db.get_conn()
    with db.db_session():
        conn.execute(
            """UPDATE profiles SET name=?, platforms=?, identity=?, style=?, audience=?,
                 platform_rules=?, preferences=?, general_mode=?, updated_at=? WHERE id=?""",
            (
                profile.name,
                db.dumps(profile.platforms),
                profile.identity,
                profile.style,
                profile.audience,
                profile.platform_rules,
                profile.preferences,
                1 if profile.general_mode else 0,
                now,
                profile.id,
            ),
        )
    profile.updated_at = _parse_ts(now) or profile.updated_at
    return profile


def _sync_memories(profile: Profile) -> None:
    """按 ``profile.memories`` 全量重写该画像的记忆（顺序即展示顺序）。"""
    conn = db.get_conn()
    with db.db_session():
        conn.execute("DELETE FROM memories WHERE profile_id=?", (profile.id,))
        for m in profile.memories:
            conn.execute(
                "INSERT INTO memories (id, profile_id, text, source, adopted, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (m.id, profile.id, m.text, m.source, 1 if m.adopted else 0,
                 _iso(m.created_at) or db.utcnow()),
            )


def create_profile(
    name: str,
    platforms: list[str] | None = None,
    *,
    fields: dict[str, Any] | None = None,
    write_md: bool = True,
) -> Profile:
    """新建画像。**只有名字也能建**（spec §5 / §8 test_create_minimal_profile）。"""
    clean = (name or "").strip()
    if not clean:
        raise ValidationError("账号名不能为空", detail={"name": name}, hint="至少给账号起个名字，之后随时能改")

    now = db.utcnow()
    pid = new_profile_id(clean)
    plat = [str(p).strip() for p in (platforms or []) if str(p).strip()]
    profile = Profile(
        id=pid,
        name=clean,
        platforms=plat,
        general_mode=False,
        created_at=now,
        updated_at=now,
    )
    for key, val in (fields or {}).items():
        if key in TEXT_DIMS:
            setattr(profile, key, str(val or ""))
        elif key == "platforms" and val:
            profile.platforms = [str(p).strip() for p in val if str(p).strip()]

    conn = db.get_conn()
    with db.db_session():
        conn.execute(
            """INSERT INTO profiles (id, name, platforms, identity, style, audience,
                 platform_rules, preferences, general_mode, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            # 时间统一存 ISO 字符串（不直接塞 datetime：py3.12 起 sqlite3 的
            # 默认 datetime adapter 已废弃）
            (profile.id, profile.name, db.dumps(profile.platforms), "", "", "", "", "",
             0, _iso(profile.created_at) or now, _iso(profile.updated_at) or now),
        )
    _update_locked(profile)
    if write_md:
        _write_md(profile)
    return profile


def update_profile(profile_id: str, changes: dict[str, Any], *, touch: bool = True) -> Profile:
    """局部更新任一维，自动重算 completeness（由 :meth:`Profile.completeness` 负责）。

    ``touch=False`` 用于反向导入：不刷新 ``updated_at``，避免导入后又盖掉用户的 md。
    """
    profile = get_profile(profile_id)
    unknown = set(changes) - PROFILE_FIELDS
    if unknown:
        raise ValidationError(
            "有字段不能改",
            detail={"unknown": sorted(unknown), "allowed": sorted(PROFILE_FIELDS)},
            hint="id 与 created_at 是冻结字段；只能改 name / platforms / 五个文本维度 / general_mode",
        )
    for key, val in changes.items():
        if val is None:
            continue
        if key == "platforms":
            profile.platforms = [str(p).strip() for p in val if str(p).strip()]
        elif key == "general_mode":
            profile.general_mode = bool(val)
        elif key == "name":
            text = str(val).strip()
            if not text:
                raise ValidationError("账号名不能为空", detail={"name": val}, hint="名字只允许改，不能删空")
            profile.name = text
        else:
            setattr(profile, key, str(val))

    if touch:
        _update_locked(profile)
    else:
        conn = db.get_conn()
        with db.db_session():
            conn.execute(
                """UPDATE profiles SET name=?, platforms=?, identity=?, style=?, audience=?,
                     platform_rules=?, preferences=?, general_mode=? WHERE id=?""",
                (profile.name, db.dumps(profile.platforms), profile.identity, profile.style,
                 profile.audience, profile.platform_rules, profile.preferences,
                 1 if profile.general_mode else 0, profile.id),
            )
    _write_md(profile)
    return profile


def set_general_mode(profile_id: str, enabled: bool) -> Profile:
    return update_profile(profile_id, {"general_mode": bool(enabled)})


def delete_profile(profile_id: str, *, confirm: str | None = None) -> None:
    """删画像。**有会话引用 → 409**；``confirm`` 不对 → 422。

    md 文件一并删掉：双写没了下界，留着孤儿文件比不留更坏。
    """
    get_profile(profile_id)  # 不存在 → ProfileNotFound(404)
    if (confirm or "").strip() != profile_id:
        raise ValidationError(
            "删除画像需要二次确认",
            detail={"profile_id": profile_id, "confirm_got": confirm},
            hint=f"确认 token 就是画像 id：把 ?confirm={profile_id} 原样带上（UI-SPEC 规则 19）",
        )
    used = sessions_using(profile_id)
    if used:
        raise _sessions_conflict(profile_id, used)

    conn = db.get_conn()
    with db.db_session():
        conn.execute("DELETE FROM memories WHERE profile_id=?", (profile_id,))
        conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        _drop_wizard_states(conn, profile_id)
    try:
        profile_md_path(profile_id).unlink(missing_ok=True)
    except OSError as exc:  # 文件删不掉不该让库已删的操作看起来失败，但要留痕
        log.warning("画像已删但 md 未删: %s: %s", profile_id, exc)


def _drop_wizard_states(conn: sqlite3.Connection, profile_id: str) -> None:
    """连带清掉这个画像的向导进度。

    向导进度存在 ``settings`` 表（见 :mod:`.wizard`），没有外键兜着；
    画像删了而进度还在，就是一条永远取不到的孤儿数据。
    """
    for key, value in conn.execute("SELECT k, v FROM settings WHERE k LIKE 'wizard:%'").fetchall():
        if profile_id in (value or ""):
            conn.execute("DELETE FROM settings WHERE k=?", (key,))


def _sessions_conflict(profile_id: str, count: int) -> Exception:
    """有会话引用时构造 409。抽成函数是为了让 409 带上可执行的下一步。"""
    from ..errors import SessionBusy

    return SessionBusy(
        f"还有 {count} 个会话在用这个画像，不能直接删",
        detail={"profile_id": profile_id, "sessions": count},
        hint="先把这些会话切到别的画像或通用模式，再回来删；画像正文本身不会丢",
    )


# ---------------------------------------------------------------------------
# 记忆 CRUD
# ---------------------------------------------------------------------------


def list_memories(profile_id: str) -> list[Memory]:
    return get_profile(profile_id).memories


def add_memory(
    profile_id: str,
    text: str,
    *,
    source: str = "手动",
    adopted: bool = True,
) -> Memory:
    """手动加一条长期记忆。**下一轮对话立即生效**（进 :func:`prompt.build_profile_prefix`）。"""
    profile = get_profile(profile_id)
    clean = (text or "").strip()
    if not clean:
        raise ValidationError("记忆内容不能为空", detail={"text": text}, hint="写一句下次别再犯的话即可")
    memory = Memory(
        id=_new_memory_id(),
        text=clean,
        source=source or "手动",
        created_at=utcnow(),
        adopted=bool(adopted),
    )
    profile.memories = [*profile.memories, memory]
    _sync_memories(profile)
    _update_locked(profile)
    _write_md(profile)
    return memory


def delete_memory(profile_id: str, memory_id: str) -> None:
    profile = get_profile(profile_id)
    remaining = [m for m in profile.memories if m.id != memory_id]
    if len(remaining) == len(profile.memories):
        raise ProfileNotFound(
            "这条记忆不存在或已被删除",
            detail={"profile_id": profile_id, "memory_id": memory_id},
            hint="刷新一下页面看看是不是已经删过了",
        )
    profile.memories = remaining
    _sync_memories(profile)
    _update_locked(profile)
    _write_md(profile)


# ---------------------------------------------------------------------------
# 反向导入（支持用户手改 md）
# ---------------------------------------------------------------------------


def sync_from_disk() -> list[str]:
    """扫描 ``profiles/*.md``，md 的 ``updated_at`` 比库里新就导进去。

    返回实际导入的 id 列表。**SQLite 仍然是准的**——只有时间戳明确更新才覆盖。
    """
    imported: list[str] = []
    if not paths.PROFILES.exists():
        return imported
    for path in sorted(paths.PROFILES.glob("*.md")):
        try:
            parsed = parse_markdown(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        pid = parsed.get("id") or path.stem
        db_updated = _parse_ts(_row_updated_at(pid))
        md_updated = _parse_ts(parsed.get("updated_at"))
        if db_updated is None and md_updated is None:
            continue
        if db_updated is not None and (md_updated is None or md_updated <= db_updated):
            continue  # 库里更新（或 md 没写时间）→ 保持 SQLite 为准
        if not paths.PROJECT_NAME_RE.match(pid):
            continue  # 文件名/id 不合法就不导，避免脏数据进库
        if db_updated is None:
            _import_new(pid, parsed)
        else:
            _import_over(pid, parsed)
        imported.append(pid)
    return imported


def _row_updated_at(profile_id: str) -> str | None:
    row = db.get_conn().execute("SELECT updated_at FROM profiles WHERE id=?", (profile_id,)).fetchone()
    return row["updated_at"] if row is not None else None


def _import_new(pid: str, parsed: dict[str, Any]) -> None:
    """md 里有、库里没有 → 当新画像建。``id``/``created_at`` 沿用 md。"""
    fields = dict(parsed.get("fields") or {})
    now = db.utcnow()
    name = fields.pop("name", None) or pid
    platforms = fields.pop("platforms", None) or []
    general = bool(fields.pop("general_mode", False))
    conn = db.get_conn()
    with db.db_session():
        conn.execute(
            """INSERT INTO profiles (id, name, platforms, identity, style, audience,
                 platform_rules, preferences, general_mode, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, name, db.dumps(list(platforms)),
             fields.get("identity", ""), fields.get("style", ""), fields.get("audience", ""),
             fields.get("platform_rules", ""), fields.get("preferences", ""),
             1 if general else 0, parsed.get("created_at") or now, parsed.get("updated_at") or now),
        )
    _import_memories(pid, parsed.get("memories") or [])
    profile = get_profile(pid)
    _write_md(profile)


def _import_over(pid: str, parsed: dict[str, Any]) -> None:
    """两边都有、md 更新 → 用 md 覆盖（``updated_at`` 保留 md 的，之后不再重复导入）。"""
    fields = dict(parsed.get("fields") or {})
    profile = get_profile(pid)
    for key, val in fields.items():
        if key in PROFILE_FIELDS:
            setattr(profile, key, val)
    profile.updated_at = _parse_ts(parsed.get("updated_at")) or profile.updated_at
    conn = db.get_conn()
    with db.db_session():
        conn.execute(
            """UPDATE profiles SET name=?, platforms=?, identity=?, style=?, audience=?,
                 platform_rules=?, preferences=?, general_mode=?, updated_at=? WHERE id=?""",
            (profile.name, db.dumps(profile.platforms), profile.identity, profile.style,
             profile.audience, profile.platform_rules, profile.preferences,
             1 if profile.general_mode else 0, _iso(profile.updated_at), pid),
        )
    _import_memories(pid, parsed.get("memories") or [])
    _write_md(profile)


def _import_memories(pid: str, memories: list[dict[str, Any]]) -> None:
    rows = []
    for m in memories:
        rows.append((m["id"], pid, m["text"], m["source"], 1 if m.get("adopted") else 0, m["created_at"]))
    if not rows:
        return
    conn = db.get_conn()
    with db.db_session():
        for row in rows:
            conn.execute(
                "INSERT INTO memories (id, profile_id, text, source, adopted, created_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "text=excluded.text, source=excluded.source, adopted=excluded.adopted, "
                "created_at=excluded.created_at",
                row,
            )


def ensure_synced() -> list[str]:
    """进程内跑一次反向导入（等价于「启动时」）。

    刻意做成**惰性**而不是 app startup 钩子：``main.py`` 是地基层的文件，本域不改它；
    而惰性只依赖「本进程第一次碰画像时自动对齐」，对服务端与测试行为一致。
    """
    global _SYNCED
    if _SYNCED:
        return []
    _SYNCED = True
    try:
        return sync_from_disk()
    except Exception:  # noqa: BLE001 - 导入失败不该让整个 API 不可用
        return []


# ---------------------------------------------------------------------------
# 序列化（API 侧统一口径）
# ---------------------------------------------------------------------------


def wizard_marker(profile: Profile) -> dict[str, Any]:
    """列表页用的极简摘要（不含六维正文，避免 N+1 的响应体积）。"""
    scores = profile.completeness()
    return {
        "id": profile.id,
        "name": profile.name,
        "platforms": profile.platforms,
        "general_mode": profile.general_mode,
        "completeness": scores,
        "completeness_overall": round(sum(scores.values()) / len(scores)),
        "memory_count": len(profile.memories),
        "updated_at": _iso(profile.updated_at),
        "created_at": _iso(profile.created_at),
    }


def profile_dict(profile: Profile) -> dict[str, Any]:
    """详情响应：模型全字段 + ``completeness`` 六维 + 中文标签。"""
    data = to_dict(profile)
    data["completeness"] = profile.completeness()
    data["completeness_overall"] = round(
        sum(data["completeness"].values()) / len(data["completeness"])
    )
    data["dimension_labels"] = dict(DIMENSION_LABELS)
    data["md_path"] = paths.rel_to_root(profile_md_path(profile.id))
    return data
