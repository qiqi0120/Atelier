"""SPEC-05 §1–§3 · 内容库服务层。

四条硬约束（对应 PRD F-G6 / F-G7 与 SPEC-01 §1 铁律）：

1. **路径唯一收口**：所有外部传入的 ``path`` 都过 :func:`resolve_library_path`
   （内部调用 :func:`atelier.server.paths.resolve_inside`），逃逸 → ``PathEscapeError``。
   本文件**不出现任何 f-string 拼路径**，目录一律用 ``paths`` 的函数。
2. **文件系统是唯一真相源**：``artifacts`` 表只是索引。文件被手动删了，
   列表扫描时自动剔除孤儿行并记日志（:func:`clean_orphan_index`），不静默。
3. **Range 必须正确**：合法 → 206 + ``Content-Range``；非法 → 416；无 Range → 200。
   任何大小都走分块迭代器，**永不整文件 ``read()`` 进内存**（F-G6）。
4. **删除保护**：系统文件 403；普通文件/项目必须带一次性 ``confirm`` token，
   且文案显式声明「及其全部内容」（UI-SPEC §5 规则 19 / SPEC-05 §3.2）。

⚠️ 关于常量的一个坑：本模块**不** ``from ..paths import OUTPUTS``。``paths.configure()``
（测试夹具、``ATELIER_ROOT``）会**重新绑定** ``paths.OUTPUTS``，``from`` 导入拿到的是
导入那一刻的旧值，测试切根后就会指向真实仓库的 ``outputs/``。因此一律 ``paths.XXX``
在调用时取。
"""

from __future__ import annotations

import logging
import mimetypes
import re
import secrets
import shutil
import sqlite3
import struct
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import paths
from ..core import db
from ..errors import AtelierError, NotFound, SystemFileProtected, ValidationError

log = logging.getLogger("atelier.library")

__all__ = [
    "CHUNK_SIZE",
    "KINDS",
    "LARGE_FILE",
    "PREVIEWABLE",
    "ZONES",
    "RangeNotSatisfiable",
    "clean_orphan_index",
    "create_project",
    "delete_file",
    "delete_project",
    "file_item",
    "file_meta",
    "human_size",
    "issue_confirm_token",
    "iter_file_bytes",
    "list_files",
    "list_projects",
    "parse_range",
    "preview_text",
    "project_stats",
    "resolve_library_path",
    "stream_plan",
    "unlock_system",
]

#: 流式分块。1MB 足够大又不至于让客户端长时间无数据。
CHUNK_SIZE = 1024 * 1024

#: SPEC-05 §3.1：大文件阈值（超过必须真流式）。本实现**所有**大小都流式。
LARGE_FILE = 50 * 1024 * 1024

#: F-G3 类型过滤的四档 + 兜底
KINDS: tuple[str, ...] = ("image", "video", "audio", "doc")

_EXT_KIND: dict[str, str] = {
    # 图片
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image", ".svg": "image", ".heic": "image",
    # 视频
    ".mp4": "video", ".mov": "video", ".m4v": "video", ".webm": "video",
    ".mkv": "video", ".avi": "video",
    # 音频
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".aac": "audio",
    ".ogg": "audio", ".flac": "audio",
    # 文档（可预览的都在 PREVIEWABLE 里）
    ".md": "doc", ".markdown": "doc", ".html": "doc", ".htm": "doc",
    ".srt": "doc", ".vtt": "doc", ".json": "doc", ".txt": "doc",
    ".csv": "doc", ".pdf": "doc", ".docx": "doc",
}

#: 列表排序：图片 → 视频 → 音频 → 文档 → 其它（网格视图先给看得到的产物）
_KIND_ORDER: dict[str, int] = {"image": 0, "video": 1, "audio": 2, "doc": 3, "file": 4}

#: 预览端点支持的文本类后缀（SPEC-05 §3 ``/preview``）
PREVIEWABLE: frozenset[str] = frozenset(
    {".md", ".markdown", ".html", ".htm", ".srt", ".vtt", ".json", ".txt", ".csv", ".log"}
)

#: 分区：成品 / 素材 / 系统会话目录
ZONES: tuple[str, ...] = (paths.PRODUCT_ZONE, paths.MATERIAL_ZONE, ".session")

#: 预览文本上限，避免把 200MB 的日志读进内存
PREVIEW_MAX_BYTES = 512 * 1024

_CONFIRM_TTL = 300  # 秒
_TOKENS: dict[str, dict[str, Any]] = {}


class RangeNotSatisfiable(AtelierError):
    """SPEC-05 §3.1：非法 Range → **416**。

    **spec 扩展（§11 冻结清单外）**：SPEC-01 §2 的错误码表里没有 416 条目，
    这里补一个机器可读的 code，前端才能区分「拖动进度条越界」与「文件真的坏了」。
    响应体仍是统一的 ``{"error": {code, message, detail, hint}}``，
    并额外带 ``Content-Range: bytes */<size>``（RFC 9110 §14.4 要求）。
    """

    code = "RangeNotSatisfiable"
    http = 416
    default_message = "请求的字节范围超出文件大小"
    default_hint = "刷新一下预览重新拉取；如果视频卡住，多半是文件被替换了，重新打开即可"


# ---------------------------------------------------------------------------
# 路径解析（SPEC-01 §1 铁律的唯一出口）
# ---------------------------------------------------------------------------


def _strip_outputs_prefix(raw: str) -> str:
    """兼容 ``outputs/a/成品/b.png`` 与 ``a/成品/b.png`` 两种写法。

    SPEC-05 §3.1 的示例用 ``path=outputs/...``，而 ``Attachment.path`` 约定是
    「相对 ``outputs/``」（SPEC-01 §6）。两种都收，剥完前缀再交给
    :func:`paths.resolve_inside`——逃逸保护不受影响。
    """
    text = str(raw).replace("\\", "/").strip()
    if text == "outputs":
        return ""
    if text.startswith("outputs/"):
        return text[len("outputs/") :]
    return text


def resolve_library_path(raw: str) -> Path:
    """``path`` 查询参数 → ``outputs/`` 内的绝对路径。逃逸直接 400。"""
    rel = _strip_outputs_prefix(raw)
    if not rel:
        raise ValidationError(
            "请给出要访问的文件路径",
            detail={"path": raw},
            hint="例如 path=outputs/png-check/成品/xhs-card/01-ai.png",
        )
    return paths.resolve_inside(paths.OUTPUTS, rel)


def _abs_from_rel_path(raw: str) -> Path | None:
    """把索引里的 ``rel_path`` 变回绝对路径；不合法 / 指向库外返回 ``None``。"""
    try:
        return resolve_library_path(raw)
    except AtelierError:
        return None


def _rel_outputs(p: Path) -> str:
    """``outputs/`` 内的 posix 相对路径（前端 ``path`` 参数的标准形式）。"""
    return Path(p).resolve().relative_to(paths.OUTPUTS.resolve()).as_posix()


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def human_size(n: int | None) -> str:
    """412 KB / 18.2 MB。给 UI 直接用，避免前端再抄一份单位换算。"""
    v = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"  # pragma: no cover - 上面的循环已覆盖


def guess_kind(p: Path | str) -> str:
    """扩展名 → ``image``/``video``/``audio``/``doc``/``file``。"""
    return _EXT_KIND.get(Path(p).suffix.lower(), "file")


def guess_mime(p: Path | str) -> str:
    ext = Path(p).suffix.lower()
    if ext in (".md", ".markdown"):
        return "text/markdown; charset=utf-8"
    if ext in (".srt", ".vtt", ".txt", ".csv", ".log"):
        return "text/plain; charset=utf-8"
    if ext == ".json":
        return "application/json; charset=utf-8"
    guessed, _ = mimetypes.guess_type(str(p))
    return guessed or "application/octet-stream"


def _zone_of(rel_outputs: str) -> str:
    """``<project>/<zone>/...`` → 第二个路径段；不是分区目录则空串。"""
    parts = Path(rel_outputs).parts
    if len(parts) >= 2 and parts[1] in ZONES:
        return parts[1]
    return ""


def _image_size(p: Path) -> tuple[int | None, int | None]:
    """图片宽高。Pillow 不可用或文件坏了就返回 ``(None, None)``，不抛。"""
    try:
        from PIL import Image  # 依赖已在 pyproject；坏文件不应让预览整页挂掉

        with Image.open(p) as im:
            return int(im.width), int(im.height)
    except Exception as exc:  # noqa: BLE001 - 元信息是尽力而为
        log.debug("image size probe failed: %s (%s)", p, exc)
        return None, None


def _mp4_duration(p: Path) -> float | None:
    """从 MP4/MOV 的 ``mvhd`` box 读时长（秒）。不引 ffprobe；失败返回 None。"""
    try:
        with p.open("rb") as f:
            head = f.read(64 * 1024)
        i = head.find(b"mvhd")
        if i < 0:
            return None
        ver = head[i + 4]
        if ver == 1:
            timescale, duration = struct.unpack(">IQ", head[i + 20 : i + 32])
        else:
            timescale, duration = struct.unpack(">II", head[i + 16 : i + 24])
        if timescale <= 0:
            return None
        return round(duration / timescale, 1)
    except Exception as exc:  # noqa: BLE001
        log.debug("mp4 duration probe failed: %s (%s)", p, exc)
        return None


def _human_duration(seconds: float | None) -> str | None:
    if not seconds or seconds <= 0:
        return None
    m, s = divmod(round(seconds), 60)
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# 条目构造
# ---------------------------------------------------------------------------


def file_item(p: Path, *, with_size: bool = True) -> dict[str, Any]:
    """统一形状的文件条目。``path`` 是 ``outputs/`` 内相对路径（可直接喂给前端）。"""
    p = Path(p)
    rel = _rel_outputs(p)
    try:
        st = p.stat()
        size, mtime = int(st.st_size), st.st_mtime
    except OSError:  # pragma: no cover - 扫描与 stat 之间被删
        size, mtime = 0, 0.0
    kind = guess_kind(p)
    width = height = None
    duration = duration_human = None
    if with_size and size:
        if kind == "image":
            width, height = _image_size(p)
        elif kind in ("video", "audio") and p.suffix.lower() in (".mp4", ".mov", ".m4v"):
            duration = _mp4_duration(p)
            duration_human = _human_duration(duration)
    ext = p.suffix.lower().lstrip(".")
    return {
        "name": p.name,
        "path": rel,
        "rel_to_root": paths.rel_to_root(p),
        "zone": _zone_of(rel),
        "kind": kind,
        "ext": ext,
        "mime": guess_mime(p),
        "size": size,
        "size_human": human_size(size),
        "width": width,
        "height": height,
        "duration": duration,
        "duration_human": duration_human,
        "modified_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else None,
        "is_system": paths.is_system_path(p),
        "previewable": p.suffix.lower() in PREVIEWABLE,
        "download_url": f"/api/library/stream?path={rel}",
    }


def _dir_item(p: Path) -> dict[str, Any]:
    rel = _rel_outputs(p)
    return {
        "name": p.name,
        "path": rel,
        "rel_to_root": paths.rel_to_root(p),
        "kind": "dir",
        "is_system": paths.is_system_path(p),
    }


def _require_project(name: str) -> Path:
    d = paths.project_dir(name)  # 名字非法 → ValidationError
    if not d.is_dir():
        raise NotFound(
            f"找不到项目「{name}」",
            detail={"project": name, "path": paths.rel_to_root(d)},
            hint="项目可能已被删除；先刷新左侧目录，或新建一个项目",
        )
    return d


def _require_zone_dir(project: str, zone: str) -> Path:
    d = _require_project(project)
    if zone not in ZONES:
        raise ValidationError(
            f"没有这个分区：{zone}",
            detail={"project": project, "zone": zone, "allowed": list(ZONES)},
            hint=f"可用分区：{' / '.join(ZONES)}",
        )
    return d / zone


# ---------------------------------------------------------------------------
# 项目（SPEC-05 §3 第 1、2 个端点）
# ---------------------------------------------------------------------------


def _count_files(d: Path) -> tuple[int, int]:
    """(文件数, 总字节)。目录不存在算 0。"""
    n = total = 0
    if not d.is_dir():
        return 0, 0
    for f in d.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                n += 1
                total += f.stat().st_size
        except OSError:  # pragma: no cover - 权限/竞态
            continue
    return n, total


def project_stats(name: str) -> dict[str, Any]:
    """项目统计：分区计数 + 文件数 + 总大小（删项目确认弹窗要用）。"""
    d = _require_project(name)
    zones: list[dict[str, Any]] = []
    total_files = total_bytes = 0
    for z in ZONES:
        zd = d / z
        n, b = _count_files(zd)
        total_files += n
        total_bytes += b
        zones.append(
            {
                "name": z,
                "path": _rel_outputs(zd),
                "count": n,
                "bytes": b,
                "size_human": human_size(b),
                "is_system": z in paths.SYSTEM_DIR_NAMES,
            }
        )
    extra = [f for f in d.iterdir() if f.is_file()]
    return {
        "project": name,
        "path": _rel_outputs(d),
        "rel_to_root": paths.rel_to_root(d),
        "zones": zones,
        "file_count": total_files,
        "total_bytes": total_bytes,
        "total_size_human": human_size(total_bytes),
        "other_files": [f.name for f in extra],
        "exists": True,
    }


def list_projects() -> dict[str, Any]:
    """项目列表 + 每个项目 成品/素材 计数（SPEC-05 §3）。"""
    projects = []
    for name in paths.list_projects():
        d = paths.OUTPUTS / name
        counts: dict[str, int] = {z: _count_files(d / z)[0] for z in ZONES}
        n, b = _count_files(d)
        projects.append(
            {
                "name": name,
                "path": _rel_outputs(d),
                "rel_to_root": paths.rel_to_root(d),
                "product_count": counts[paths.PRODUCT_ZONE],
                "material_count": counts[paths.MATERIAL_ZONE],
                "system_count": counts[".session"],
                "counts": counts,
                "file_count": n,
                "total_bytes": b,
                "total_size_human": human_size(b),
                "updated_at": _updated_at(d),
            }
        )
    projects.sort(key=lambda x: (x["updated_at"] or "", x["name"]), reverse=True)
    return {
        "projects": projects,
        "count": len(projects),
        "root": paths.rel_to_root(paths.OUTPUTS),
        "zones": list(ZONES),
    }


def _updated_at(d: Path) -> str | None:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime))
    except OSError:  # pragma: no cover
        return None


def create_project(name: str) -> dict[str, Any]:
    """建项目（SPEC-05 §3 第 2 个端点）。目录创建全部委托 ``paths.new_project``。"""
    before = paths.project_dir(name).exists()
    d = paths.new_project(name)
    log.info("library: project %s (created=%s)", name, not before)
    return {
        "ok": True,
        "created": not before,
        "name": name,
        "path": _rel_outputs(d),
        "rel_to_root": paths.rel_to_root(d),
        "zones": [{"name": z, "path": _rel_outputs(d / z)} for z in ZONES],
    }


# ---------------------------------------------------------------------------
# 目录树 / 文件列表（SPEC-05 §3 第 3、4 个端点）
# ---------------------------------------------------------------------------


def _listdir(d: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    if not d.is_dir():
        return dirs, files
    for child in sorted(d.iterdir(), key=lambda p: p.name):
        if child.name == ".DS_Store":
            continue
        try:
            if child.is_dir():
                dirs.append(_dir_item(child))
            elif child.is_file():
                files.append(file_item(child))
        except OSError:  # pragma: no cover - 竞态删除
            continue
    dirs.sort(key=lambda x: x["name"])
    files.sort(key=lambda x: x["name"])
    return dirs, files


def tree(project: str, zone: str = paths.PRODUCT_ZONE, sub: str = "") -> dict[str, Any]:
    """面包屑逐级下钻（SPEC-05 §3 第 3 个端点）。

    ``sub`` 是 zone 之下的相对子目录（SPEC-05 未列该参数，为满足验收 2「面包屑
    逐级下钻」补的扩展参数，默认空 = zone 根）。
    """
    base = _require_zone_dir(project, zone)
    cur = base
    crumbs: list[dict[str, Any]] = [
        {"label": project, "project": project, "zone": "", "sub": "", "path": _rel_outputs(paths.project_dir(project))}
    ]
    if zone:
        crumbs.append(
            {"label": zone, "project": project, "zone": zone, "sub": "", "path": _rel_outputs(base),
             "is_system": zone in paths.SYSTEM_DIR_NAMES}
        )
    if sub.strip():
        cur = paths.resolve_inside(base, sub)
        if not cur.is_dir():
            raise NotFound(
                "这个子目录不存在",
                detail={"project": project, "zone": zone, "sub": sub},
                hint="面包屑里点上一级回到上一目录",
            )
        for part in Path(sub).parts:
            if not part or part == ".":
                continue
            crumbs.append(
                {"label": part, "project": project, "zone": zone,
                 "sub": str(Path(crumbs[-1]["sub"]) / part) if crumbs[-1]["sub"] else part,
                 "path": _rel_outputs(cur)}
            )
    dirs, files = _listdir(cur)
    return {
        "project": project,
        "zone": zone,
        "sub": sub,
        "path": _rel_outputs(cur),
        "rel_to_root": paths.rel_to_root(cur),
        "breadcrumb": crumbs,
        "dirs": dirs,
        "files": files,
        "count": len(files),
        "is_system": paths.is_system_path(cur),
        "orphan_removed": len(clean_orphan_index(project)),
    }


def list_files(
    project: str,
    zone: str = "",
    kind: str = "",
    q: str = "",
    sub: str = "",
    recursive: bool = True,
) -> dict[str, Any]:
    """文件列表（类型过滤 + 名称搜索，F-G3）。

    ``zone`` 空 = 整个项目；``kind`` 空 = 全部；``q`` 对文件名做子串匹配（忽略大小写）。
    """
    root = _require_project(project)
    if zone:
        root = _require_zone_dir(project, zone)
    elif sub.strip():
        raise ValidationError(
            "带 sub 时必须同时给 zone",
            detail={"project": project, "sub": sub},
            hint="例如 project=x&zone=成品&sub=子目录",
        )
    if sub.strip():
        root = paths.resolve_inside(root, sub)
    if not root.is_dir():
        raise NotFound("目录不存在", detail={"project": project, "zone": zone, "sub": sub},
                       hint="回到上一级目录看看")

    want = (kind or "").strip().lower()
    if want and want not in (*KINDS, "file", "all"):
        raise ValidationError(
            f"未知的类型过滤：{kind}",
            detail={"kind": kind, "allowed": [*KINDS, "file", "all"]},
            hint=f"可用：{' / '.join(KINDS)} / 全部",
        )
    needle = (q or "").strip().lower()

    found: list[dict[str, Any]] = []
    walker = root.rglob("*") if recursive else root.iterdir()
    for f in sorted(walker):
        if f.name == ".DS_Store":
            continue
        try:
            if not f.is_file():
                continue
        except OSError:  # pragma: no cover
            continue
        if want not in ("", "all", "file") and guess_kind(f) != want:
            continue
        if want == "file" and guess_kind(f) in KINDS:
            continue
        if needle and needle not in f.name.lower():
            continue
        found.append(file_item(f))

    found.sort(key=lambda x: (_KIND_ORDER.get(x["kind"], 9), x["name"]))
    return {
        "project": project,
        "zone": zone,
        "sub": sub,
        "path": _rel_outputs(root),
        "kind": want or "all",
        "q": q or "",
        "files": found,
        "count": len(found),
        "counts_by_kind": {k: sum(1 for x in found if x["kind"] == k) for k in KINDS},
        "orphan_removed": len(clean_orphan_index(project)),
    }


# ---------------------------------------------------------------------------
# 元信息 / 文本预览（SPEC-05 §3 第 6、7 个端点）
# ---------------------------------------------------------------------------


def file_meta(raw: str) -> dict[str, Any]:
    p = _require_file(raw)
    item = file_item(p)
    item["stream_url"] = f"/api/library/stream?path={item['path']}"
    item["preview_url"] = (
        f"/api/library/preview?path={item['path']}" if item["previewable"] else None
    )
    item["etag"] = _etag(p)
    item["system_notice"] = (
        ".session/ 与 .index.json 为系统文件，受保护、禁止删除" if item["is_system"] else None
    )
    return item


def _require_file(raw: str) -> Path:
    p = resolve_library_path(raw)
    if not p.exists():
        raise NotFound(
            "文件不存在（或已被移动/删除）",
            detail={"path": _strip_outputs_prefix(raw)},
            hint="回到上一级目录刷新一下；文件系统的内容永远以磁盘为准",
        )
    if p.is_dir():
        raise ValidationError(
            "这是一个目录，不能当文件预览",
            detail={"path": _strip_outputs_prefix(raw)},
            hint="用目录树逐级下钻，或去掉末尾的目录名只选文件",
        )
    return p


def preview_text(raw: str) -> dict[str, Any]:
    """文本类预览内容（md / html / srt / json …）。超限截断并显式标记。"""
    p = _require_file(raw)
    ext = p.suffix.lower()
    if ext not in PREVIEWABLE:
        raise ValidationError(
            f"{ext or '这个文件'} 不支持文本预览",
            detail={"path": _strip_outputs_prefix(raw), "ext": ext,
                    "previewable": sorted(PREVIEWABLE)},
            hint="图片/视频/音频走 /api/library/stream（Range 分段），这里只服务文本类",
        )
    size = p.stat().st_size
    with p.open("rb") as f:
        raw_bytes = f.read(PREVIEW_MAX_BYTES)
    truncated = size > PREVIEW_MAX_BYTES
    text = raw_bytes.decode("utf-8", errors="replace")
    if ext in (".md", ".markdown"):
        fmt = "markdown"
    elif ext in (".html", ".htm"):
        fmt = "html"
    elif ext == ".json":
        fmt = "json"
    else:
        fmt = "text"
    return {
        "path": _rel_outputs(p),
        "rel_to_root": paths.rel_to_root(p),
        "name": p.name,
        "format": fmt,
        "mime": guess_mime(p),
        "size": size,
        "size_human": human_size(size),
        "content": text,
        "truncated": truncated,
        "limit_bytes": PREVIEW_MAX_BYTES,
        "is_system": paths.is_system_path(p),
        "hint": (
            f"文件超过 {human_size(PREVIEW_MAX_BYTES)}，只返回了前 {human_size(PREVIEW_MAX_BYTES)}"
            if truncated
            else None
        ),
    }


# ---------------------------------------------------------------------------
# ★ Range 流式（F-G6 硬要求）
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^bytes=(?P<spec>.+)$", re.IGNORECASE)


def _etag(p: Path) -> str:
    st = p.stat()
    return f'"{st.st_size:x}-{int(st.st_mtime):x}"'


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """解析 ``Range: bytes=...`` → ``(start, end)``（闭区间，end 必含）。

    返回 ``None`` 表示「按整文件 200 回」。非法 / 越界抛 :class:`RangeNotSatisfiable`
    （416）。支持 ``0-1023``、``1024-``、``-500``（后缀）；多段只回第一段——
    浏览器媒体元素只发单段，CDN 语义一致。
    """
    if header is None or not str(header).strip():
        return None
    m = _RANGE_RE.match(str(header).strip())
    if not m:
        raise RangeNotSatisfiable(
            "只支持 bytes 范围的 Range 请求",
            detail={"range": header, "unit_expected": "bytes"},
            hint="Range 头写成 bytes=0-1048575",
        )
    first = m.group("spec").split(",")[0].strip()
    if "-" not in first:
        raise RangeNotSatisfiable("Range 格式不合法", detail={"range": header},
                                  hint="正确写法：bytes=0-1048575")
    start_s, _, end_s = first.partition("-")
    try:
        if not start_s:  # bytes=-N 后缀
            if not end_s or not end_s.isdigit():
                raise ValueError(start_s)
            length = int(end_s)
            if length == 0:
                raise ValueError("0 长度后缀")
            start = max(0, size - length)
            end = size - 1
        else:
            if not start_s.isdigit():
                raise ValueError(start_s)
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError as exc:
        raise RangeNotSatisfiable(
            "Range 里的字节位置不是数字",
            detail={"range": header, "offending": str(exc)},
            hint="正确写法：bytes=0-1048575 或 bytes=1048576-",
        ) from exc
    if size == 0 or start >= size or end < start:
        raise RangeNotSatisfiable(
            "请求的字节范围超出文件大小",
            detail={"range": header, "file_size": size, "start": start, "end": end},
            hint="文件可能已被替换，重新打开预览即可",
        )
    return start, min(end, size - 1)


def _if_range_allows(if_range: str | None, etag: str, mtime: int) -> bool:
    """``If-Range`` 不匹配（文件换过）时按整文件 200 回，而不是给错的 206。"""
    if not if_range:
        return True
    val = str(if_range).strip()
    if val.startswith("W/"):
        val = val[2:].strip()
    if val.startswith('"') and val.endswith('"'):
        return val.strip('"') == etag.strip('"')
    # 只给了 HTTP-date：与 Last-Modified 同秒即视为未变
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(val)
    except (TypeError, ValueError):
        return False
    if dt is None:
        return False
    return int(dt.timestamp()) == int(mtime)


def stream_plan(raw: str, *, range_header: str | None = None, if_range: str | None = None,
                download: bool = False) -> dict[str, Any]:
    """算出流式回包的元信息（不产生 HTTP 响应体）。

    返回 ``{path, size, start, length, status, headers, chunks}``：
    - 合法 Range + If-Range 通过 → ``status=206`` 且带 ``Content-Range``
    - 无 Range / If-Range 失配 → ``status=200``，``start=0``、``length=size``
    - 非法 Range → 抛 :class:`RangeNotSatisfiable`（416）
    """
    p = _require_file(raw)
    st = p.stat()
    size = int(st.st_size)
    mtime = int(st.st_mtime)
    etag = _etag(p)
    mime = guess_mime(p)

    rng: tuple[int, int] | None = None
    if _if_range_allows(if_range, etag, mtime):
        rng = parse_range(range_header, size)
    if rng is None:
        start, end, status = 0, size - 1, 200
    else:
        start, end = rng
        status = 206
    length = max(0, end - start + 1) if size else 0

    headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "ETag": etag,
        "Last-Modified": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{p.name}"'
    return {
        "path": p,
        "size": size,
        "start": start,
        "end": end,
        "length": length,
        "status": status,
        "mime": mime,
        "is_large": size > LARGE_FILE,
        "headers": headers,
        "chunks": lambda: iter_file_bytes(p, start, length),
    }


def iter_file_bytes(p: Path, start: int, length: int, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    """分块迭代文件字节。**任何大小都不整读进内存**（SPEC-05 §3.1）。

    文件句柄由生成器自己持有，生成器结束（客户端断开）时随 with 关闭。
    """
    if length <= 0:
        return
    remaining = length
    with Path(p).open("rb") as f:
        if start:
            f.seek(start)
        while remaining > 0:
            data = f.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


# ---------------------------------------------------------------------------
# 孤儿索引清理（SPEC-05 §2：artifacts 表是索引不是真相源）
# ---------------------------------------------------------------------------


def _artifacts_rows(project: str | None = None) -> list[sqlite3.Row]:
    try:
        conn = db.get_conn()
        if project:
            return conn.execute(
                "SELECT id, project, zone, rel_path FROM artifacts WHERE project=?", (project,)
            ).fetchall()
        return conn.execute("SELECT id, project, zone, rel_path FROM artifacts").fetchall()
    except sqlite3.OperationalError as exc:
        # 表还没建（理论上 lifespan 已 init_db）——记日志，不静默，也不让列表挂掉
        log.warning("artifacts table unavailable, orphan scan skipped: %s", exc)
        return []


def clean_orphan_index(project: str | None = None) -> list[str]:
    """剔除指向已不存在文件的 artifacts 行，**每条都记一条日志**（PRD 原则四）。"""
    rows = _artifacts_rows(project)
    if not rows:
        return []
    gone: list[str] = []
    conn = db.get_conn()
    for r in rows:
        p = _abs_from_rel_path(str(r["rel_path"]))
        if p is not None and p.exists():
            continue
        conn.execute("DELETE FROM artifacts WHERE id=?", (r["id"],))
        gone.append(str(r["rel_path"]))
    if gone:
        conn.commit()
    for rel in gone:
        log.warning("orphan artifact removed (file missing on disk): %s", rel)
    return gone


def _forget_artifact_rows(p: Path) -> int:
    """删文件时同步清掉它的索引行。

    ``artifacts.rel_path`` 两种写法都见过（``outputs/x/...`` 与 ``x/...``），
    两种都删，免得留下指向已删文件的孤儿行。
    """
    rel = _rel_outputs(p)
    conn = db.get_conn()
    cur = conn.execute(
        "DELETE FROM artifacts WHERE rel_path=? OR rel_path=?", (rel, paths.rel_to_root(p))
    )
    n = cur.rowcount or 0
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# 删除保护（F-G7 硬要求）
# ---------------------------------------------------------------------------


def _prune_tokens() -> None:
    now = time.time()
    for k in [k for k, v in _TOKENS.items() if float(v.get("expires_at", 0)) < now]:
        _TOKENS.pop(k, None)


def _warning_for_file(p: Path) -> str:
    """SPEC-05 §3.2 / UI-SPEC 规则 19：文案必须含「你正在删除 `x` 及其全部内容」。"""
    return f"你正在删除 `{p.name}` 及其全部内容"


def _warning_for_project(name: str, stats: dict[str, Any]) -> str:
    return (
        f"你正在删除项目 `{name}` 及其全部内容"
        f"（{stats['file_count']} 个文件，{stats['total_size_human']}，"
        f"含成品 / 素材 / 会话日志）"
    )


def issue_confirm_token(*, path: str | None = None, project: str | None = None) -> dict[str, Any]:
    """破坏性操作的前置口令（SPEC-05 §3 第 8 个端点）。一次性、短时效。"""
    _prune_tokens()
    if bool(path) == bool(project):
        raise ValidationError(
            "要么给 path（删文件），要么给 project（删整个项目）",
            detail={"path": path, "project": project},
            hint="一次确认口令只对应一个删除目标",
        )
    if path:
        p = _require_file(path)
        if paths.is_system_path(p):
            raise SystemFileProtected(
                f"`.session/` 等系统文件禁止删除：{paths.rel_to_root(p)}",
                detail={"path": paths.rel_to_root(p), "protected": True},
                hint="系统文件由工作台自己维护；需要清理请到设置里解锁（M1 只给提示）",
            )
        target = f"file:{_rel_outputs(p)}"
        warning = _warning_for_file(p)
        extra: dict[str, Any] = {"name": p.name, "size": p.stat().st_size,
                                 "size_human": human_size(p.stat().st_size)}
    else:
        stats = project_stats(str(project))
        target = f"project:{project}"
        warning = _warning_for_project(str(project), stats)
        extra = {k: stats[k] for k in ("file_count", "total_bytes", "total_size_human")}

    token = secrets.token_urlsafe(24)
    _TOKENS[token] = {
        "target": target,
        "warning": warning,
        "extra": extra,
        "issued_at": time.time(),
        "expires_at": time.time() + _CONFIRM_TTL,
    }
    log.info("library: confirm token issued for %s (ttl=%ds)", target, _CONFIRM_TTL)
    return {
        "token": token,
        "expires_in": _CONFIRM_TTL,
        "target": target,
        "warning": warning,
        "requires_typing": extra.get("name"),
        **extra,
    }


def _consume_token(token: str | None, target: str) -> dict[str, Any]:
    """校验并**消费**口令。缺口令 / 过期 / 目标不匹配都拒绝（一次性）。"""
    _prune_tokens()
    if not token or not str(token).strip():
        raise ValidationError(
            "删除前必须先确认",
            detail={"target": target, "reason": "missing_confirm"},
            hint="先 POST /api/library/confirm-token 拿口令，再带 ?confirm=<token> 重发",
        )
    rec = _TOKENS.get(str(token).strip())
    if rec is None:
        raise ValidationError(
            "确认口令无效或已被用过",
            detail={"target": target, "reason": "unknown_or_used_token"},
            hint="口令一次性且 5 分钟过期；重新打开确认弹窗再取一个",
        )
    if rec["target"] != target:
        raise ValidationError(
            "确认口令与要删除的目标不匹配",
            detail={"target": target, "token_target": rec["target"], "reason": "target_mismatch"},
            hint="别复用上一个文件的确认口令，重新走一次确认流程",
        )
    _TOKENS.pop(str(token).strip(), None)
    return rec


def delete_file(raw: str, confirm: str | None) -> dict[str, Any]:
    """删单个文件（SPEC-05 §3 第 9 个端点）。

    顺序：路径逃逸(400) → 系统文件(403) → 文件不存在(404) → 确认口令(422) → 真删。
    """
    p = resolve_library_path(raw)  # 逃逸直接 400
    if paths.is_system_path(p):
        raise SystemFileProtected(
            f"系统文件禁止删除：{paths.rel_to_root(p)}",
            detail={"path": paths.rel_to_root(p), "name": p.name, "protected": True},
            hint="`.session/` 与 `.index.json` 由工作台自己维护；需要清理请到设置里解锁",
        )
    if not p.is_file():
        raise NotFound(
            "文件不存在（或已被移动/删除）",
            detail={"path": _strip_outputs_prefix(raw)},
            hint="刷新一下列表，磁盘上的内容才是准的",
        )
    target = f"file:{_rel_outputs(p)}"
    _consume_token(confirm, target)  # 校验 + 消费口令，通过后才真删
    size = p.stat().st_size
    p.unlink()
    dropped = _forget_artifact_rows(p)
    pruned = _prune_empty_parents(p.parent)
    log.info("library: file deleted %s (bytes=%d, index_rows=%d)", _rel_outputs(p), size, dropped)
    return {
        "ok": True,
        "deleted": _rel_outputs(p),
        "rel_to_root": paths.rel_to_root(p),
        "name": p.name,
        "size": size,
        "size_human": human_size(size),
        "index_rows_removed": dropped,
        "pruned_dirs": pruned,
        "statement": f"已删除 {p.name} 及其全部内容",
    }


def _prune_empty_parents(d: Path) -> list[str]:
    """删完文件后把空目录收掉，但**永远不碰系统目录与项目根**。"""
    pruned: list[str] = []
    root = paths.OUTPUTS.resolve()
    cur = Path(d).resolve()
    while cur != root and root in cur.parents:
        if paths.is_system_path(cur) or not cur.is_dir():
            break
        try:
            next(cur.iterdir())
            break  # 还有东西，留着
        except StopIteration:
            pass
        except OSError:  # pragma: no cover
            break
        try:
            cur.rmdir()
        except OSError:  # pragma: no cover
            break
        pruned.append(cur.name)
        cur = cur.parent
    return pruned


def delete_project(name: str, confirm: str | None) -> dict[str, Any]:
    """删整个项目（SPEC-05 §3 第 10 个端点）。确认弹窗必须列出文件数与总大小。"""
    _require_project(name)
    stats = project_stats(name)
    rec = _consume_token(confirm, f"project:{name}")
    d = paths.project_dir(name)
    shutil.rmtree(d)
    conn = db.get_conn()
    try:
        cur = conn.execute("DELETE FROM artifacts WHERE project=?", (name,))
        dropped = cur.rowcount or 0
        conn.commit()
    except sqlite3.OperationalError as exc:  # pragma: no cover - 表没建
        dropped = 0
        log.warning("artifacts cleanup skipped for project %s: %s", name, exc)
    log.info(
        "library: project deleted %s (files=%d, bytes=%d, warning=%s)",
        name, stats["file_count"], stats["total_bytes"], rec["warning"],
    )
    return {
        "ok": True,
        "deleted": name,
        "rel_to_root": paths.rel_to_root(d),
        "file_count": stats["file_count"],
        "total_bytes": stats["total_bytes"],
        "total_size_human": stats["total_size_human"],
        "zones": stats["zones"],
        "index_rows_removed": dropped,
        "statement": f"已删除项目 {name} 及其全部内容（{stats['file_count']} 个文件，{stats['total_size_human']}）",
    }


def unlock_system(payload: dict[str, Any]) -> dict[str, Any]:
    """``POST /api/library/unlock-system``（SPEC-05 §3 第 11 个端点）。

    **M1 只给 UI 提示，不提供解锁能力**（spec 原文即如此）。本函数因此**不返回
    ``ok: true`` 式的假解锁**：即使确认短语正确，也明确回 ``unlocked: false``
    并说明原因，避免前端误以为已解锁。
    """
    typed = str(payload.get("confirm") or payload.get("typing") or "")
    phrase = "解锁系统文件"
    ok = typed.strip() == phrase
    if ok:
        log.info("library: system unlock requested but not enabled in M1 (target=%s)", payload.get("path"))
    return {
        "ok": True,
        "unlocked": False,
        "enabled": False,
        "code": "SystemFileProtected",
        "target": payload.get("path") or payload.get("project"),
        "message": "M1 未开放系统文件删除" if ok else f"确认短语不对，需要逐字输入「{phrase}」",
        "hint": (
            "`.session/` 与 `.index.json` 里的内容由工作台自己维护；"
            "要清理会话记录请在设置页操作，或直接删掉整个项目"
        ),
        "notice": "会话日志（.session/）、索引文件（.index.json）受系统保护，禁止删除",
    }
