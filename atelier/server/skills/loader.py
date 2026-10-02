"""技能资产加载器：扫描 ``atelier/skills/*/SKILL.md`` → ``SkillMeta[]``（mtime 缓存）。

约定（SPEC-04 §2 / §4）：
- 目录没变就返回缓存；``no_cache=True`` 或 ``--no-cache`` 强制重扫
- 任何单个 SKILL.md 解析失败都只记一条结构化日志并跳过，**不让整个扫描崩掉**（PRD 原则四）
- 路径一律经 ``paths.resolve_inside``，不接受 ``..`` 与绝对路径
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import yaml
from pydantic import Field

from atelier.server import paths
from atelier.server.core.models import SkillMeta, SkillParam
from atelier.server.errors import SkillNotFound, ValidationError

log = logging.getLogger("atelier.skills.loader")

LAYERS = ("发现", "策划", "制作", "发布", "归因", "通用")
MATURITIES = ("v0", "v1", "v2", "v3")
REQUIRED_FIELDS = (
    "id",
    "name",
    "layer",
    "maturity",
    "trigger",
    "cost",
    "required_keys",
    "params",
    "outputs",
    "paid",
)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,63}$")
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.DOTALL)


class LoadedSkill(SkillMeta):
    """``SkillMeta`` + 资产层扩展字段。

    ``SkillMeta`` 在 SPEC-01 §11 里是冻结契约且不含 ``outputs`` / ``paid``，
    但 SPEC-04 §2 的 front-matter 强制这两个字段，§6 的付费确认也依赖 ``paid``。
    故在此以子类承载，不改动 ``core/models.py``（地基域文件）。
    """

    outputs: list[str] = Field(default_factory=list)
    paid: bool = False
    script_path: str | None = None
    source_mtime: float = 0.0


@dataclass(frozen=True)
class SkillIssue:
    """一条结构化加载问题（PRD 原则四：失败留痕）。"""

    skill_id: str
    path: str
    level: str  # error | warn
    reason: str

    def to_dict(self) -> dict:
        return {"skill_id": self.skill_id, "path": self.path, "level": self.level, "reason": self.reason}


@dataclass
class ScanResult:
    skills: list[LoadedSkill] = dc_field(default_factory=list)
    issues: list[SkillIssue] = dc_field(default_factory=list)
    scanned_at: float = 0.0
    cached: bool = False


# 目录签名 -> 扫描结果。进程内缓存，随 mtime 变化自动失效。
_CACHE: dict[str, tuple[tuple, ScanResult]] = {}


def clear_cache() -> None:
    _CACHE.clear()


def _safe_child(base: Path, name: str) -> Path:
    try:
        return paths.resolve_inside(base, name)
    except Exception as e:
        log.error("skill path rejected", extra={"skill_id": name, "reason": str(e)})
        raise


def _signature(root: Path) -> tuple:
    """目录内容签名：(目录名, SKILL.md mtime_ns, size, run.py mtime_ns)。"""
    sig = []
    try:
        entries = sorted(p for p in root.iterdir() if p.is_dir())
    except FileNotFoundError:
        return ()
    except OSError as e:
        log.error("skills root unreadable", extra={"path": str(root), "reason": str(e)})
        return ()
    for d in entries:
        md = d / "SKILL.md"
        try:
            st = md.stat()
            m = (st.st_mtime_ns, st.st_size)
        except OSError:
            m = (0, 0)
        try:
            rst = (d / "run.py").stat()
            r = (rst.st_mtime_ns, rst.st_size)
        except OSError:
            r = (0, 0)
        sig.append((d.name, m, r))
    return tuple(sig)


def _split(raw: str) -> tuple[dict, str]:
    m = FM_RE.match(raw)
    if not m:
        raise ValueError("缺少 YAML front-matter（文件必须以 --- 开头）")
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _parse_one(skill_dir: Path, issues: list[SkillIssue]) -> LoadedSkill | None:
    sid = skill_dir.name
    md = skill_dir / "SKILL.md"
    rel = str(md.relative_to(paths.ROOT)) if _under_root(md) else str(md)

    def fail(level: str, reason: str) -> None:
        issues.append(SkillIssue(sid, rel, level, reason))
        log.log(logging.ERROR if level == "error" else logging.WARNING,
                "skill skipped: %s", reason, extra={"skill_id": sid, "path": rel, "level": level})

    if not ID_RE.match(sid):
        fail("error", f"目录名 {sid!r} 不合法（需匹配 {ID_RE.pattern}）")
        return None
    try:
        raw = md.read_text(encoding="utf-8")
    except OSError as e:
        fail("error", f"读取失败：{e}")
        return None
    try:
        fm, body = _split(raw)
    except (ValueError, yaml.YAMLError) as e:
        fail("error", f"front-matter 解析失败：{e}")
        return None
    if not isinstance(fm, dict):
        fail("error", f"front-matter 必须是映射，实际是 {type(fm).__name__}")
        return None
    missing = [f for f in REQUIRED_FIELDS if f not in fm]
    if missing:
        fail("error", f"缺少必填字段：{', '.join(missing)}")
        return None
    if fm["id"] != sid:
        fail("error", f"front-matter id={fm['id']!r} 与目录名 {sid!r} 不一致")
        return None
    if fm["layer"] not in LAYERS:
        fail("error", f"layer={fm['layer']!r} 非法，应为 {list(LAYERS)}")
        return None
    if fm["maturity"] not in MATURITIES:
        fail("error", f"maturity={fm['maturity']!r} 非法，应为 {list(MATURITIES)}")
        return None
    for key in ("required_keys", "outputs"):
        if not isinstance(fm[key], list):
            fail("error", f"{key} 必须是列表，实际是 {type(fm[key]).__name__}")
            return None
    if not isinstance(fm["paid"], bool):
        fail("error", f"paid 必须是布尔值，实际是 {type(fm['paid']).__name__}")
        return None
    params: list[SkillParam] = []
    raw_params = fm["params"]
    if not isinstance(raw_params, list):
        fail("error", "params 必须是列表")
        return None
    for p in raw_params:
        if not isinstance(p, dict) or "key" not in p:
            fail("error", f"params 条目缺少 key：{p!r}")
            return None
        try:
            params.append(SkillParam(**{**p, "label": p.get("label", p["key"]), "default": p.get("default", "")}))
        except Exception as e:  # noqa: BLE001
            fail("error", f"params 条目非法：{p!r}（{e}）")
            return None

    script = skill_dir / "run.py"
    has_script = script.is_file()
    data = {
        "id": fm["id"],
        "name": str(fm["name"]),
        "layer": fm["layer"],
        "maturity": fm["maturity"],
        "trigger": str(fm["trigger"]),
        "cost": str(fm["cost"]),
        "required_keys": [str(k) for k in fm["required_keys"]],
        "params": params,
        "body_markdown": body.strip(),
        "script": "run.py" if has_script else None,
        "outputs": [str(o) for o in fm["outputs"]],
        "paid": bool(fm["paid"]),
        "script_path": str(script) if has_script else None,
        "source_mtime": md.stat().st_mtime,
    }
    try:
        return LoadedSkill(**data)
    except Exception as e:  # noqa: BLE001 — 与 SkillMeta 契约不符也不崩扫描
        fail("error", f"构造 SkillMeta 失败（契约不符）：{e}")
        return None


def _under_root(p: Path) -> bool:
    try:
        p.relative_to(paths.ROOT)
        return True
    except ValueError:
        return False


def scan(no_cache: bool = False, root: Path | None = None) -> ScanResult:
    """扫描技能目录。``no_cache=True`` 强制重扫（对应 CLI 的 ``--no-cache``）。"""
    base = Path(root) if root is not None else paths.SKILLS
    key = str(base)
    sig = _signature(base)
    if not no_cache:
        hit = _CACHE.get(key)
        if hit and hit[0] == sig:
            out = ScanResult(skills=list(hit[1].skills), issues=list(hit[1].issues),
                             scanned_at=hit[1].scanned_at, cached=True)
            return out
    if not sig:
        log.warning("no skills found", extra={"path": key})
    issues: list[SkillIssue] = []
    skills: list[LoadedSkill] = []
    for name, _m, _r in sig:
        try:
            d = _safe_child(base, name)
        except Exception:  # noqa: BLE001,S112 — 已在 _safe_child 记日志
            continue
        s = _parse_one(d, issues)
        if s is not None:
            skills.append(s)
    skills.sort(key=lambda s: (LAYERS.index(s.layer), s.id))
    result = ScanResult(skills=skills, issues=issues, scanned_at=time.time(), cached=False)
    _CACHE[key] = (sig, ScanResult(skills=list(skills), issues=list(issues),
                                   scanned_at=result.scanned_at, cached=False))
    for i in issues:
        log.debug("issue: %s", i.reason, extra={"skill_id": i.skill_id, "level": i.level})
    return result


def list_skills(layer: str | None = None, no_cache: bool = False) -> list[LoadedSkill]:
    if layer and layer not in LAYERS:
        raise ValidationError(f"layer 非法：{layer}，应为 {list(LAYERS)}")
    skills = scan(no_cache=no_cache).skills
    return [s for s in skills if not layer or s.layer == layer]


def get_skill(skill_id: str, no_cache: bool = False) -> LoadedSkill:
    if not ID_RE.match(skill_id or ""):
        raise SkillNotFound(f"技能 id 非法：{skill_id!r}", detail={"skill_id": skill_id})
    for s in scan(no_cache=no_cache).skills:
        if s.id == skill_id:
            return s
    raise SkillNotFound(f"找不到技能 {skill_id}", detail={"skill_id": skill_id, "hint": "atelier/skills/ 下没有该目录"})


def skill_script_path(skill: LoadedSkill) -> Path | None:
    """返回技能脚本的绝对路径，并再次过 ``resolve_inside`` 防 symlink 逃逸。"""
    if not skill.script:
        return None
    if not skill.script_path:
        return None
    abs_path = Path(skill.script_path)
    try:
        rel = abs_path.relative_to(paths.SKILLS).as_posix()
    except ValueError:  # pragma: no cover — 只可能在 SKILLS 被换掉时发生
        log.error("script outside skills root", extra={"skill_id": skill.id, "path": str(abs_path)})
        raise SkillNotFound(f"技能 {skill.id} 的脚本不在技能目录内", detail={"skill_id": skill.id}) from None
    return _safe_child(paths.SKILLS, rel)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="扫描并打印技能库（--no-cache 强制重扫）")
    ap.add_argument("--no-cache", action="store_true", help="忽略 mtime 缓存，强制重扫")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--layer", default=None, choices=list(LAYERS))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    result = scan(no_cache=args.no_cache)
    skills = [s for s in result.skills if not args.layer or s.layer == args.layer]
    if args.json:
        print(json.dumps(
            {"skills": [s.model_dump(mode="json") for s in skills],
             "issues": [i.to_dict() for i in result.issues],
             "cached": result.cached},
            ensure_ascii=False, indent=2))
        return 0
    print(f"技能库：{len(skills)} 个（cached={result.cached}）")
    for s in skills:
        flags = []
        if s.paid:
            flags.append("付费")
        if s.required_keys:
            flags.append("需密钥:" + ",".join(s.required_keys))
        if s.script:
            flags.append("script")
        print(f"  [{s.layer}] {s.id:15s} {s.maturity} {' '.join(flags)}")
    for i in result.issues:
        print(f"  ! {i.level.upper()} {i.skill_id}: {i.reason}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "LAYERS",
    "MATURITIES",
    "LoadedSkill",
    "ScanResult",
    "SkillIssue",
    "clear_cache",
    "get_skill",
    "list_skills",
    "scan",
    "skill_script_path",
]
