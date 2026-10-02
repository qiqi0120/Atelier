"""能力地图：解析 ``capabilities.toml``，从技能派生 ``Capability[]``（SPEC-04 §3）。

规则：
- 分组顺序 = TOML 中 ``[groups]`` 出现顺序（tomllib 保序）
- ``maturity`` 从技能继承；``kind = "chat"`` 的纯对话能力没有 skill_id
- **技能不存在 → 该能力不显示**（能力地图不能有死链），并记 ERROR
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import tomllib

from atelier.server.core.models import Capability

log = logging.getLogger("atelier.skills.manifest")

MANIFEST_FILE = "capabilities.toml"
LAYER_ORDER = ("发现", "策划", "制作", "发布", "归因", "通用")


@dataclass(frozen=True)
class Group:
    name: str
    desc: str

    def to_dict(self) -> dict:
        return {"name": self.name, "desc": self.desc}


def manifest_path() -> Path:
    """能力地图清单与本模块同目录（包内资产，非运行时数据，不经 paths 收口）。"""
    return Path(__file__).with_name(MANIFEST_FILE)


def load_manifest() -> dict:
    p = manifest_path()
    if not p.exists():
        log.error("capabilities manifest missing: %s", p)
        return {"groups": {}, "items": []}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.error("capabilities manifest unreadable: %s", e)
        return {"groups": {}, "items": []}


def validate_no_dead_links(capabilities: list[Capability], skills) -> list[str]:
    """每条 ``skill_id`` 非空的 Capability 都必须能命中技能，否则记 ERROR 并返回死链 id。"""
    known = {s.id for s in skills}
    dead = [c.id for c in capabilities if c.skill_id and c.skill_id not in known]
    for c in dead:
        log.error(
            "capability dead link: item %s -> skill %s not found (能力地图不允许死链)",
            c.id, c.skill_id,
        )
    return dead


def unmapped_skills(capabilities: list[Capability], skills) -> list[str]:
    """有技能但没进能力地图的（只告警：能力地图是策展入口，不要求全覆盖）。"""
    used = {c.skill_id for c in capabilities if c.skill_id}
    missing = [s.id for s in skills if s.id not in used]
    for sid in missing:
        log.warning("skill not present in capability map: %s", sid)
    return missing


def _maturity_ok(v: object) -> bool:
    return v in ("v0", "v1", "v2", "v3")


def build(skills) -> tuple[list[Group], list[Capability]]:
    """从已加载技能派生能力地图。返回 (groups, capabilities)。死链在此被丢弃。"""
    by_id = {s.id: s for s in skills}
    data = load_manifest()
    raw_groups = data.get("groups", {}) or {}
    groups = [Group(name=str(name), desc=str((cfg or {}).get("desc", ""))) for name, cfg in raw_groups.items()]
    group_names = {g.name for g in groups}
    caps: list[Capability] = []
    for item in data.get("items", []) or []:
        iid = str(item.get("id") or "").strip()
        group = str(item.get("group") or "")
        kind = str(item.get("kind") or "skill")
        if not iid:
            log.error("capability item without id: %r", item)
            continue
        if group not in group_names:
            log.error("capability %s references unknown group %r", iid, group)
            continue
        if kind == "chat":
            name, trigger = str(item.get("name") or ""), str(item.get("trigger") or "")
            maturity = str(item.get("maturity") or "v3")
            if not name or not trigger:
                log.error("chat capability %s needs name and trigger", iid)
                continue
            if not _maturity_ok(maturity):
                log.error("chat capability %s has invalid maturity %r", iid, maturity)
                continue
            caps.append(Capability(id=iid, group=group, name=name, trigger=trigger,
                                   maturity=maturity, skill_id=None))
            continue
        skill = by_id.get(iid)
        if skill is None:
            log.error("capability %s -> skill %s not found, dropped (死链)", iid, iid)
            continue
        caps.append(
            Capability(
                id=item.get("capability_id", iid),
                group=group,
                name=skill.name,
                trigger=skill.trigger,
                maturity=skill.maturity,
                skill_id=skill.id,
            )
        )
    return groups, caps


def get_capabilities(no_cache: bool = False, skills=None) -> dict:
    """API 用：``{"groups": [{name, desc, items: [...]}]}``。"""
    from atelier.server.skills import loader

    skills = skills if skills is not None else loader.scan(no_cache=no_cache).skills
    groups, caps = build(skills)
    dead = validate_no_dead_links(caps, skills)
    icons = {}
    for it in load_manifest().get("items", []) or []:
        if it.get("icon"):
            icons[str(it.get("id"))] = str(it["icon"])
    out: list[dict] = []
    for g in groups:
        items = []
        for c in caps:
            if c.group != g.name:
                continue
            d = c.model_dump()
            for src in skills:
                if src.id == c.skill_id:
                    d["outputs"] = src.outputs
                    d["paid"] = src.paid
                    d["required_keys"] = src.required_keys
                    d["has_script"] = bool(src.script)
                    break
            else:
                d.update({"outputs": [], "paid": False, "required_keys": [], "has_script": False})
            d["icon"] = icons.get(c.id)
            items.append(d)
        out.append({**g.to_dict(), "items": items, "count": len(items)})
    return {"groups": out, "dead_links": dead, "total": len(caps)}
