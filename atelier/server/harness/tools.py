"""SPEC-01 §4 · 进程内 MCP 工具（门禁 / 落盘 / 库查询 / 技能 / 画像）。

**为什么工具本体不直接用 SDK 的 ``@tool`` 装饰**：SPEC-01 §4 写的是
``harness/tools.py`` 用 ``@tool`` 实现，但 ``@tool`` 来自 ``claude_agent_sdk``，
而本项目的硬性约定是「``claude_sdk.py`` 是唯一 import claude_agent_sdk 的文件」
（这样 tools 才能在没有 SDK 的环境里被单测直接调）。所以这里写成**纯 async
函数**，由 :func:`sdk_tools` 在运行时用 SDK 的 ``tool()`` 包一层再交给
``create_sdk_mcp_server``。对外暴露的工具名、参数、返回结构与 spec 完全一致，
少掉的只是装饰器语法糖。

**门禁无法绕过的机制（PRD 原则二 / SPEC-00 §1.1 ①）**：

1. :func:`atelier_gate_run` 命中 BLOCK 时返回 ``{"blocked": true, ...}`` 并附逐项改法；
2. :func:`atelier_artifact_write` **写盘前自己再跑一遍 BLOCK 门禁**，命中就根本不落盘。

所以即使模型无视第 1 条的返回、假装内容合格，第 2 条也会挡住它——阻断是代码路径
上的事实，不是提示词约定。密钥扫描因此是双保险（SPEC-01 §9）。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .. import paths
from ..core.models import DIMENSION_LABELS
from ..errors import NotFound, ProfileNotFound, ValidationError
from ..gates.base import GateInput
from ..gates.registry import run_gates

__all__ = [
    "MCP_SERVER_NAME",
    "TOOL_SPECS",
    "allowed_tool_names",
    "atelier_artifact_write",
    "atelier_gate_run",
    "atelier_library_list",
    "atelier_profile_get",
    "atelier_skill_run",
    "gate_input_from",
    "sdk_tools",
]

#: 进程内 MCP server 名。挂上后工具全名是 ``mcp__atelier__atelier_gate_run``
MCP_SERVER_NAME = "atelier"

#: 单次写盘的大小上限（防模型手滑写出超大文件）
MAX_WRITE_BYTES = 8 * 1024 * 1024

#: 落盘前必跑的 BLOCK 门禁（ai_flavor 是 WARN，不进这里）
WRITE_GATE_IDS: tuple[str, ...] = ("secret_scan", "compliance", "wordcount")

#: 写盘时视作文本、因而要过门禁的扩展名
_TEXT_SUFFIXES = frozenset(
    {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".htm", ".xml", ".py", ".ts", ".tsx", ".js"}
)


@dataclass(frozen=True)
class ToolSpec:
    """一个进程内工具的声明（名字/描述/入参 schema/实现）。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# 门禁
# ---------------------------------------------------------------------------


def gate_input_from(
    text: str = "",
    *,
    platform: str | None = None,
    title: str | None = None,
    image_paths: list[str] | None = None,
    profile: Any = None,
) -> GateInput:
    return GateInput(
        text=text or "",
        platform=platform,
        title=title,
        image_paths=list(image_paths or []),
        profile=profile,
    )


async def atelier_gate_run(
    text: str = "",
    platform: str | None = None,
    title: str | None = None,
    gate_ids: list[str] | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """对给定内容跑门禁，返回逐项结果。

    命中 BLOCK 级时返回 ``{"blocked": true, "items": [...], "fix_hint": "..."}``，
    **不抛异常**——模型要能读到每一项的 actual/limit/fix_hint 才知道怎么改。
    """
    if project:
        paths.validate_project_name(project)
    report = run_gates(
        gate_input_from(text, platform=platform, title=title),
        gate_ids=list(gate_ids) if gate_ids else None,
    )
    d = report.to_dict()
    hints = report.fix_hints()
    return {
        "blocked": report.blocked,
        "items": d["items"],
        "summary": d["summary"],
        "fix_hint": "；".join(dict.fromkeys(hints)) if hints else "",
        "project": project,
        "instruction": (
            "内容没落盘，请按每项 fix_hint 改后重试。改完必须重新调用本工具确认 blocked=false，"
            "然后再调 atelier_artifact_write 落盘。"
            if report.blocked
            else "门禁通过，可以调用 atelier_artifact_write 落盘。"
        ),
    }


# ---------------------------------------------------------------------------
# 落盘（门禁的第二道、也是真正生效的那道）
# ---------------------------------------------------------------------------


async def atelier_artifact_write(
    project: str,
    filename: str,
    content: str = "",
    zone: str = paths.PRODUCT_ZONE,
    platform: str | None = None,
    title: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """把产物写入 ``outputs/<project>/成品`` 或 ``/素材``，返回真实绝对路径。

    内部强制走 :func:`paths.resolve_inside`（挡 ``..`` 与 symlink 逃逸），
    并且**在写盘前自己跑一遍 BLOCK 门禁**——这是「模型无法绕过」的实现点。
    """
    paths.validate_project_name(project)
    if zone == paths.PRODUCT_ZONE:
        base = paths.product_dir(project)
    elif zone == paths.MATERIAL_ZONE:
        base = paths.material_dir(project)
    else:
        raise ValidationError(
            f"zone 只能是「{paths.PRODUCT_ZONE}」或「{paths.MATERIAL_ZONE}」",
            detail={"zone": zone},
            hint="成品是给用户看的产出，素材是输入素材（PRD F-G4）",
        )

    # 路径唯一收口：绝对路径、..、symlink 逃逸都在这里挡住
    target = paths.resolve_inside(base, filename)

    body = content or ""
    if len(body.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValidationError(
            f"内容太大了（{len(body.encode('utf-8'))} 字节）",
            detail={"limit": MAX_WRITE_BYTES},
            hint="一次别写超过 8MB，拆成几个文件",
        )

    # 门禁：只对文本内容判，素材（图片/视频）不判字数
    gates: dict[str, Any] | None = None
    if target.suffix.lower() in _TEXT_SUFFIXES:
        report = run_gates(
            gate_input_from(
                body,
                platform=platform,
                title=title if title is not None else target.stem,
            ),
            gate_ids=list(WRITE_GATE_IDS),
        )
        d = report.to_dict()
        gates = d
        if report.blocked:
            return {
                "ok": False,
                "blocked": True,
                "written": False,
                "target": paths.rel_to_root(target),
                "items": d["items"],
                "fix_hint": "；".join(dict.fromkeys(report.fix_hints())),
                "instruction": "内容未落盘。按 fix_hint 改后重新调用本工具。",
            }

    if target.exists() and not overwrite:
        return {
            "ok": False,
            "blocked": False,
            "written": False,
            "target": paths.rel_to_root(target),
            "error": "文件已存在且 overwrite=false",
            "fix_hint": "换个文件名，或传 overwrite=true 覆盖",
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(body, encoding="utf-8")

    return {
        "ok": True,
        "blocked": False,
        "written": True,
        "abs_path": str(target),  # 回传真实绝对路径（SPEC-01 §4 关键点）
        "rel_path": paths.rel_to_root(target),
        "zone": zone,
        "project": project,
        "bytes": target.stat().st_size,
        "overwritten": existed,
        "gates": gates,
    }


# ---------------------------------------------------------------------------
# 内容库（只读）
# ---------------------------------------------------------------------------


async def atelier_library_list(
    project: str | None = None,
    zone: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """查内容库已有产物（只读）。按项目 / 分区过滤，最多 ``limit`` 条。"""
    if project:
        paths.validate_project_name(project)
    base = paths.project_dir(project) if project else paths.OUTPUTS
    if not base.exists():
        return {"ok": True, "items": [], "count": 0, "note": f"还没有产物：{paths.rel_to_root(base)}"}

    items: list[dict[str, Any]] = []
    for p in sorted(base.rglob("*")):
        if len(items) >= max(int(limit), 0):
            break
        if p.is_dir() or paths.is_system_path(p):
            continue
        rel_project = p.relative_to(paths.OUTPUTS).parts[0] if p.is_relative_to(paths.OUTPUTS) else ""
        pzone = p.relative_to(paths.OUTPUTS / rel_project).parts[0] if rel_project else ""
        if zone and pzone != zone:
            continue
        try:
            st = p.stat()
            size, mtime = st.st_size, int(st.st_mtime)
        except OSError:  # pragma: no cover - 并发删除
            continue
        items.append(
            {
                "project": rel_project,
                "zone": pzone,
                "name": p.name,
                "rel_path": paths.rel_to_root(p),
                "abs_path": str(p),
                "bytes": size,
                "modified_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            }
        )

    return {"ok": True, "count": len(items), "items": items, "read_only": True}


# ---------------------------------------------------------------------------
# 技能（归属 W1-B，这里只留接口位）
# ---------------------------------------------------------------------------


async def atelier_skill_run(
    skill: str,
    params: dict[str, Any] | None = None,
    project: str = "default",
    confirm_cost: bool = False,
) -> dict[str, Any]:
    """就地运行某个技能。

    实际执行委托给技能域的 ``atelier.server.skills.runner.run_skill``（SPEC-04 §6），
    地基层不自己实现加载/执行逻辑，避免双份实现互相漂移。

    保留的关键行为：缺 ``required_keys`` 里的密钥时抛 ``SkillMissingKey``（SPEC-01 §4），
    让前端明确显示「缺什么」而不是笼统失败；付费技能未 ``confirm_cost`` 时只返回费用预估。
    """
    from atelier.server.errors import SkillMissingKey
    from atelier.server.skills import runner  # 延迟导入：保持 tools.py 顶层 SDK-free 且无循环依赖

    try:
        result = await runner.run_skill(
            skill,
            params=params,
            project=project,
            confirm_cost=confirm_cost,
        )
    except SkillMissingKey as exc:
        # runner 用异常表达缺密钥；转成结构化返回，让模型能直接把「缺什么」
        # 写进给用户的话里（SPEC-01 §4 的意图），而不是只看到一句异常。
        detail = getattr(exc, "detail", None) or {}
        missing = detail.get("missing_keys") or detail.get("keys") or []
        return {
            "ok": False,
            "blocked": True,
            "reason": "missing_keys",
            "missing_keys": missing,
            "fix_hint": (
                f"请先在设置里配置 {', '.join(missing)}，然后重试。"
                if missing
                else f"请先在设置里补齐该技能需要的密钥：{exc}"
            ),
        }

    if result.status == "cost_pending":
        return {
            "ok": False,
            "blocked": True,
            "reason": "cost_confirm_required",
            "cost": result.cost_estimate,
            "fix_hint": "这是按量计费操作，向用户说明费用并获得确认后，带 confirm_cost=true 重试。",
        }

    return {
        "ok": result.status == "done",
        "run_id": result.run_id,
        "skill_id": result.skill_id,
        "result_markdown": result.result_markdown,
        "artifacts": list(result.artifacts),
        "gate_report": result.gate_report,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# 画像（供 agent 自查红线，SPEC-01 §4）
# ---------------------------------------------------------------------------

#: 画像 md 里的中文小节名 → core.models 的维度 key
_DIMENSION_ALIASES: dict[str, str] = {
    "定位": "identity",
    "身份": "identity",
    "风格": "style",
    "调性": "style",
    "受众": "audience",
    "人群": "audience",
    "平台约束": "platform_rules",
    "平台规则": "platform_rules",
    "偏好红线": "preferences",
    "偏好": "preferences",
    "红线": "preferences",
    "长期记忆": "memories",
    "记忆": "memories",
}


#: 维度 key → 画像 md 里的**规范**中文小节名。
#: 不能从 :data:`_DIMENSION_ALIASES` 反查——那个表一个 key 有多个别名（定位/身份、
#: 风格/调性…），反查只会留下最后一个。规范名以 core.models 为准。
_KEY_TO_LABEL: dict[str, str] = dict(DIMENSION_LABELS)


async def atelier_profile_get(
    profile_id: str,
    dimension: str = "all",
) -> dict[str, Any]:
    """读画像某一维，供 agent 自查红线。找不到画像抛 ``ProfileNotFound``。"""
    paths.validate_id(profile_id, "profile_id")
    md = paths.PROFILES / f"{profile_id}.md"
    if not md.exists():
        raise ProfileNotFound(
            "画像不存在或已删除",
            detail={"profile_id": profile_id, "expected": paths.rel_to_root(md)},
            hint="用 atelier_profile_get 之前先确认画像 id；或切到通用模式",
        )

    raw = md.read_text("utf-8", errors="replace")
    want = (dimension or "all").strip()
    if want in ("all", "*"):
        return {"ok": True, "profile_id": profile_id, "dimension": "all", "content": raw}

    key = _DIMENSION_ALIASES.get(want)
    if key is None and want in ("identity", "style", "audience", "platform_rules", "preferences", "memories"):
        key = want
    if key is None:
        raise ValidationError(
            f"没有这一维：{dimension}",
            detail={"available": sorted(set(_DIMENSION_ALIASES))},
            hint="可用：定位 / 风格 / 受众 / 平台约束 / 偏好红线 / 长期记忆 / all",
        )

    # md 文件用中文小节标题，所以拿 key 反查标签再去找
    text = _extract_section(raw, _KEY_TO_LABEL.get(key, want))
    if text is None:
        text = ""  # 画像里这一维是空的：返回空串，别假装有内容
    return {"ok": True, "profile_id": profile_id, "dimension": key, "content": text}


def _extract_section(markdown: str, heading: str) -> str | None:
    """从 markdown 里取某个 ``## 小节`` 的正文；找不到返回 ``None``。

    与小节出现顺序无关：扫所有 heading，命中的那个一直收集到下一个 heading 为止。
    """
    lines = markdown.splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip().rstrip("：:")
            if found:
                break  # 已收集完，遇到下一个 heading 就收工
            found = name == heading or name in _DIMENSION_ALIASES and _DIMENSION_ALIASES[name] == heading
            if found:
                out = []
        elif found:
            out.append(line)
    if not found:
        return None
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# 工具清单 + SDK 包装
# ---------------------------------------------------------------------------

_GATE_RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "要检查的正文内容"},
        "platform": {
            "type": "string",
            "enum": ["xhs", "dy", "gzh"],
            "description": "目标平台，决定字数上限（xhs 1000 / dy 标题 55 / gzh 20000）",
        },
        "title": {"type": "string", "description": "标题（抖音按 55 字判）"},
        "gate_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "只跑指定门禁；省略则全跑",
        },
        "project": {"type": "string", "description": "项目名（可选，仅用于校验与回显）"},
    },
    "required": ["text"],
}

_ARTIFACT_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "项目名（小写字母/数字/-/_，≤64 字符）"},
        "filename": {"type": "string", "description": "相对分区目录的路径，如 探店/笔记.md"},
        "content": {"type": "string", "description": "文件正文"},
        "zone": {
            "type": "string",
            "enum": [paths.PRODUCT_ZONE, paths.MATERIAL_ZONE],
            "description": "成品（给用户看）或 素材（输入素材）",
        },
        "platform": {"type": "string", "enum": ["xhs", "dy", "gzh"]},
        "title": {"type": "string", "description": "标题（用于门禁判字数）"},
        "overwrite": {"type": "boolean", "description": "覆盖已存在文件，默认 true"},
    },
    "required": ["project", "filename", "content"],
}

_LIBRARY_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "只看某个项目；省略则看全部"},
        "zone": {"type": "string", "enum": [paths.PRODUCT_ZONE, paths.MATERIAL_ZONE]},
        "limit": {"type": "integer", "description": "最多返回几条，默认 50"},
    },
    "required": [],
}

_SKILL_RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill": {"type": "string", "description": "技能 id"},
        "params": {"type": "object", "description": "技能参数键值对", "additionalProperties": True},
    },
    "required": ["skill"],
}

_PROFILE_GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "string", "description": "画像 id"},
        "dimension": {
            "type": "string",
            "description": "定位 / 风格 / 受众 / 平台约束 / 偏好红线 / 长期记忆 / all",
        },
    },
    "required": ["profile_id"],
}

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="atelier_gate_run",
        description=(
            "对给定内容跑确定性门禁（字数/合规词/密钥扫描），返回逐项结果。"
            "命中 BLOCK 级时返回 blocked=true，此内容不允许落盘——必须先按 fix_hint 修改。"
        ),
        input_schema=_GATE_RUN_SCHEMA,
        fn=atelier_gate_run,
    ),
    ToolSpec(
        name="atelier_artifact_write",
        description=(
            "把产物写入 outputs/<项目>/成品 或 /素材，内部会再跑一次 BLOCK 门禁，"
            "不合格直接不落盘。返回真实绝对路径，可直接展示给用户点击。"
        ),
        input_schema=_ARTIFACT_WRITE_SCHEMA,
        fn=atelier_artifact_write,
    ),
    ToolSpec(
        name="atelier_library_list",
        description="查内容库已有产物（只读）。写新内容前先看看有没有能复用的。",
        input_schema=_LIBRARY_LIST_SCHEMA,
        fn=atelier_library_list,
    ),
    ToolSpec(
        name="atelier_skill_run",
        description="就地运行某个技能（如「一键成片」）。缺密钥会明确报缺哪个。",
        input_schema=_SKILL_RUN_SCHEMA,
        fn=atelier_skill_run,
    ),
    ToolSpec(
        name="atelier_profile_get",
        description="读画像某一维（定位/风格/受众/平台约束/偏好红线/长期记忆），用于自查红线。",
        input_schema=_PROFILE_GET_SCHEMA,
        fn=atelier_profile_get,
    ),
)

_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOL_SPECS}


def allowed_tool_names() -> list[str]:
    """挂到 ``ClaudeAgentOptions.allowed_tools`` 的全名列表。"""
    return [f"mcp__{MCP_SERVER_NAME}__{t.name}" for t in TOOL_SPECS]


def get_tool(name: str) -> ToolSpec:
    spec = _BY_NAME.get(name)
    if spec is None:
        raise NotFound(
            f"没有这个进程内工具：{name}",
            detail={"available": sorted(_BY_NAME)},
            hint="只能用 atelier_gate_run / atelier_artifact_write / atelier_library_list / "
            "atelier_skill_run / atelier_profile_get",
        )
    return spec


def sdk_tools() -> list[Any]:
    """用 SDK 的 ``@tool`` 包一层，返回可交给 ``create_sdk_mcp_server`` 的工具列表。

    SDK 依赖放在函数体内 import（本文件是 5 个工具的唯一真相源，但不做 SDK 的
    顶层依赖），所以单测可以在没有 SDK 的环境里直接测 ``fn``。
    """
    from claude_agent_sdk import tool  # 局部 import：保持本文件 SDK-free

    wrapped = []
    for spec in TOOL_SPECS:
        wrapped.append(tool(spec.name, spec.description, spec.input_schema)(spec.fn))
    return wrapped


def build_mcp_server() -> Any:
    """构造 in-process MCP server 配置（``mcp_servers={name: cfg}`` 用）。"""
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(MCP_SERVER_NAME, "0.1.0", sdk_tools())
