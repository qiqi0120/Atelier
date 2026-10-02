"""SPEC-01 §1 · 路径唯一收口（铁律：全项目只有本文件可以拼路径）。

设计要点：

1. **所有根目录都是模块级常量**，业务代码只 import 常量、只调本文件的函数。
   任何 ``os.path.join(ROOT, "outputs", ...)`` 或 f-string 拼路径都算违规。
2. :func:`resolve_inside` 同时防 ``..`` 穿越和 **symlink 逃逸**：先把 base 与
   目标都 ``Path.resolve()``（会跟随符号链接），再用 ``parents`` 判定是否仍在
   base 内。macOS 上 ``/var`` → ``/private/var`` 这种系统级 symlink 也因此安全。
3. 项目名 ``^[a-z0-9][a-z0-9-_]{0,63}$``，禁止 ``..``、绝对路径、路径分隔符。

SPEC-01 §11 冻结了本文件已有的函数名。带 ``SPEC-01 §1 扩展`` 注释的两个函数
（:func:`session_dir` / :func:`turn_log`）是为满足 §3「每轮事件写
``var/sessions/<sid>/<turn_id>.jsonl``、resume 从这里读」而补的——spec 给了常量
``SESSIONS`` 但没给拼接函数，而 §1 铁律又不允许在 harness 里 f-string 拼路径。
按 §11「先提 spec 变更」，此处标注待确认。
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from .errors import NotFound, PathEscapeError, SystemFileProtected, ValidationError

__all__ = [
    "MATERIAL_ZONE",
    "OUTPUTS",
    "PRODUCT_ZONE",
    "PROFILES",
    "PROJECT_NAME_RE",
    "ROOT",
    "SESSIONS",
    "SKILLS",
    "SYSTEM_DIR_NAMES",
    "SYSTEM_FILE_NAMES",
    "SYSTEM_PREFIXES",
    "VAR",
    "VAR_DB",
    "configure",
    "current_root",
    "ensure_dirs",
    "index_path",
    "is_system_path",
    "material_dir",
    "new_project",
    "product_dir",
    "project_dir",
    "rel_to_root",
    "resolve_inside",
    "session_dir",
    "turn_log",
    "turn_log_paths",
    "validate_project_name",
]

#: SPEC-01 §1 冻结的项目名正则
PROJECT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,63}$")

#: 成品 / 素材 分区名（PRD F-G4）
PRODUCT_ZONE = "成品"
MATERIAL_ZONE = "素材"

#: PRD F-G7 禁止删除的系统文件
SYSTEM_DIR_NAMES = frozenset({".session"})
SYSTEM_FILE_NAMES = frozenset({".index.json"})
SYSTEM_PREFIXES = (".atelier",)

#: 仓库根标记：往上找带这两个的目录，认定为 Atelier 根
_ROOT_MARKERS = ("pyproject.toml", "atelier")


def _detect_root() -> Path:
    """运行时确定 ROOT。

    SPEC-01 §1 原文是「默认 cwd 的上一级」。实测该默认值在本项目布局下会取到
    ``/Users/yuzhe/AIDev``（仓库的父目录）——``outputs/``、``var/`` 会落错地方。
    因此实现为：``ATELIER_ROOT`` > 向上查找仓库标记 > 退回 spec 默认（cwd 上一级）。
    这是**对 spec 的一处偏差**，已在交付报告里登记。
    """
    env = os.environ.get("ATELIER_ROOT")
    if env and env.strip():
        return Path(env.strip()).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for cand in (cwd, *cwd.parents):
        if all((cand / m).exists() for m in _ROOT_MARKERS):
            return cand
    return cwd.parent


ROOT: Path = _detect_root()
OUTPUTS: Path = ROOT / "outputs"
PROFILES: Path = ROOT / "profiles"
VAR: Path = ROOT / "var"
SKILLS: Path = ROOT / "atelier" / "skills"
VAR_DB: Path = VAR / "atelier.db"
SESSIONS: Path = VAR / "sessions"


def configure(root: Path | str | None = None) -> Path:
    """重设 ROOT 并重绑所有派生常量（幂等；测试用临时根时调用）。

    函数体内引用的是模块全局名，所以重新绑定后所有函数立即生效。
    """
    global ROOT, OUTPUTS, PROFILES, VAR, SKILLS, VAR_DB, SESSIONS
    if root is not None:
        os.environ["ATELIER_ROOT"] = str(Path(root).expanduser().resolve())
    ROOT = _detect_root()
    OUTPUTS = ROOT / "outputs"
    PROFILES = ROOT / "profiles"
    VAR = ROOT / "var"
    SKILLS = ROOT / "atelier" / "skills"
    VAR_DB = VAR / "atelier.db"
    SESSIONS = VAR / "sessions"
    return ROOT


def current_root() -> Path:
    """当前生效的 ROOT（比直接 import ROOT 常量更抗「configure 之后」的场景）。"""
    return ROOT


# ---------------------------------------------------------------------------
# 项目名校验
# ---------------------------------------------------------------------------


def validate_project_name(name: str) -> str:
    """校验项目名，合法则原样返回；不合法抛 ``ValidationError``（SPEC-01 §1）。"""
    if not isinstance(name, str) or not name:
        raise ValidationError(
            "项目名不能为空",
            detail={"name": name, "reason": "空名字", "pattern": PROJECT_NAME_RE.pattern},
            hint="项目名只允许小写字母、数字、-、_，且必须以字母或数字开头",
        )
    if not PROJECT_NAME_RE.match(name):
        reason = "含不允许的字符"
        if "/" in name or "\\" in name:
            reason = "不能包含路径分隔符"
        elif ".." in name:
            reason = "不能包含 .."
        elif name != name.lower():
            reason = "必须全小写"
        elif len(name) > 64:
            reason = "超过 64 个字符"
        raise ValidationError(
            "项目名不合法：只允许小写字母、数字、-、_",
            detail={"name": name, "reason": reason, "pattern": PROJECT_NAME_RE.pattern},
            hint="例如 lunch-2026 或 my_project_01",
        )
    return name


# ---------------------------------------------------------------------------
# 项目目录（成品 / 素材 分区）
# ---------------------------------------------------------------------------


def project_dir(project: str) -> Path:
    return OUTPUTS / validate_project_name(project)


def product_dir(project: str) -> Path:
    return project_dir(project) / PRODUCT_ZONE


def material_dir(project: str) -> Path:
    return project_dir(project) / MATERIAL_ZONE


def index_path(project: str) -> Path:
    return project_dir(project) / ".index.json"


def new_project(name: str) -> Path:
    """创建 ``outputs/<name>/{成品,素材,.session}`` 并建索引，返回项目目录。

    幂等：已存在时补齐缺失的分区，不覆盖已有 ``.index.json`` 的 ``created_at``。
    """
    validate_project_name(name)
    d = project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    for sub in (PRODUCT_ZONE, MATERIAL_ZONE, ".session"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    idx = index_path(name)
    now = _now()
    payload: dict[str, object] = {
        "name": name,
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "zones": [PRODUCT_ZONE, MATERIAL_ZONE],
    }
    if idx.exists():
        try:
            old = json.loads(idx.read_text("utf-8"))
            if isinstance(old, dict):
                payload["created_at"] = old.get("created_at", now)
        except (json.JSONDecodeError, OSError):
            pass  # 索引坏了就重建，不静默吞：项目目录内容仍在
    idx.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def list_projects() -> list[str]:
    """扫 outputs/ 下所有合法项目名（按创建时间倒序交给调用方排）。"""
    if not OUTPUTS.exists():
        return []
    names = [p.name for p in OUTPUTS.iterdir() if p.is_dir() and PROJECT_NAME_RE.match(p.name)]
    return sorted(names)


# ---------------------------------------------------------------------------
# 会话 / 每轮事件落盘（SPEC-01 §1 扩展，待 spec 确认）
# ---------------------------------------------------------------------------


def session_dir(session_id: str) -> Path:
    """``var/sessions/<session_id>``。session_id 走 resolve_inside 防穿越。"""
    validate_id(session_id, "session_id")
    return resolve_inside(SESSIONS, session_id)


def turn_log(session_id: str, turn_id: str) -> Path:
    """``var/sessions/<sid>/<turn_id>.jsonl``。"""
    validate_id(turn_id, "turn_id")
    return session_dir(session_id) / f"{turn_id}.jsonl"


def turn_log_paths(turn_id: str) -> list[Path]:
    """按 turn_id 反查落盘位置（``resume`` 只拿到 turn_id 时的兜底扫描）。"""
    validate_id(turn_id, "turn_id")
    if not SESSIONS.exists():
        return []
    return sorted(SESSIONS.glob(f"*/{turn_id}.jsonl"))


def validate_id(value: str, label: str = "id") -> str:
    """内部 id 白名单：字母数字 - _，长度上限 128。"""
    if not isinstance(value, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$", value):
        raise ValidationError(
            f"{label} 不合法",
            detail={label: value},
            hint="id 只能包含字母、数字、-、_，且必须以字母或数字开头",
        )
    return value


# ---------------------------------------------------------------------------
# 路径安全
# ---------------------------------------------------------------------------


def resolve_inside(base: Path, rel: str) -> Path:
    """把外部传入的相对路径解析为 ``base`` 内的绝对路径。

    逃出 base 即抛 ``PathEscapeError``，覆盖三种情况：

    - ``..`` 穿越（``../../etc/passwd``）
    - 绝对路径（``/etc/passwd``、``C:\\\\x``）
    - **symlink 逃逸**：``base/link -> /etc``，``base/link/passwd`` 会被 resolve 出来

    返回值是 ``resolve()`` 后的绝对路径，可直接用于读写。
    """
    if rel is None or not str(rel).strip():
        raise ValidationError("路径不能为空", detail={"rel": rel}, hint="传入一个相对路径，例如 成品/笔记.md")

    raw = str(rel)
    if raw.startswith(("/", "\\")) or PureWindowsPath(raw).drive or PureWindowsPath(raw).is_absolute():
        raise PathEscapeError(
            "只接受相对路径，不接受绝对路径",
            detail={"base": str(base), "rel": raw},
            hint="路径请相对于工作台目录给，例如 outputs/demo/成品/笔记.md 里的 成品/笔记.md",
        )

    # 按两种分隔符切分，同时挡住 posix 的 `..` 与 windows 的 `..\` 变体
    parts = [p for p in re.split(r"[\\/]+", raw) if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathEscapeError(
            "路径里不允许 `..`",
            detail={"base": str(base), "rel": raw, "offending": ".."},
            hint="只能访问工作台目录内的文件",
        )

    base_r = Path(base).expanduser().resolve()
    target = base_r.joinpath(*parts) if parts else base_r
    # 关键：resolve() 会跟随 symlink，于是 symlink 逃逸在这里被「现形」
    resolved = target.resolve()
    if resolved != base_r and base_r not in resolved.parents:
        raise PathEscapeError(
            "路径超出允许范围",
            detail={
                "base": str(base_r),
                "rel": raw,
                "resolved": str(resolved),
                "reason": "symlink_escape" if target.exists() else "outside_base",
            },
            hint="不能通过软链接指向工作台目录外",
        )
    return resolved


def is_system_path(p: Path) -> bool:
    """PRD F-G7：``.session/`` / ``.index.json`` / ``.atelier*`` 为系统文件，禁止删除。"""
    try:
        path = Path(p)
    except TypeError:  # pragma: no cover - 防御性
        return False
    for part in path.parts:
        if part in SYSTEM_DIR_NAMES or part in SYSTEM_FILE_NAMES:
            return True
        if part.startswith(SYSTEM_PREFIXES):
            return True
    return False


def assert_deletable(p: Path) -> Path:
    """删除前的守门：命中系统文件抛 ``SystemFileProtected``，否则原样返回。"""
    if is_system_path(p):
        raise SystemFileProtected(
            ".session/ 为系统文件，禁止删除",
            detail={"path": str(p)},
            hint="只删成品/素材里的内容；系统文件由工作台自己维护",
        )
    return Path(p)


def rel_to_root(p: Path) -> str:
    """统一转成 ``outputs/...`` 形式供 UI 显示（相对 ROOT 的 posix 字符串）。"""
    path = Path(p)
    try:
        rp = path.resolve()
        rr = ROOT.resolve()
    except OSError:  # pragma: no cover - 极端情况
        return path.as_posix()
    if rp == rr:
        return "."
    for base, prefix in ((OUTPUTS, "outputs"), (PROFILES, "profiles"), (VAR, "var")):
        try:
            br = base.resolve()
        except OSError:  # pragma: no cover
            continue
        if rp == br:
            return prefix
        if br in rp.parents:
            return f"{prefix}/" + rp.relative_to(br).as_posix()
    if rr in rp.parents:
        return rp.relative_to(rr).as_posix()
    return rp.as_posix()


def ensure_dirs() -> None:
    """幂等创建所有根目录（outputs / profiles / var / var/sessions）。"""
    for d in (OUTPUTS, PROFILES, VAR, SESSIONS):
        d.mkdir(parents=True, exist_ok=True)


def require_dir(base: Path, rel: str) -> Path:
    """``resolve_inside`` + 存在性检查，不存在抛 ``NotFound``。"""
    p = resolve_inside(base, rel)
    if not p.exists():
        raise NotFound(
            "文件不存在",
            detail={"path": rel_to_root(p)},
            hint="内容库里看看是不是已经被移动或删除了",
        )
    return p


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
