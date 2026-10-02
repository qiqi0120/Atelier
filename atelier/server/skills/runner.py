"""就地运行器（SPEC-04 §6 / F-C8）。

执行顺序（顺序本身是契约）：
1. 前置检查：缺 ``required_keys`` → ``SkillMissingKey``（409），message 写明缺哪个
2. ``paid: true`` → **先返回费用预估**，需 ``confirm_cost=True`` 才真跑（PRD 原则三）
3. 有 ``run.py`` → 走确定性脚本（executor，shell=False）
   无 ``run.py`` → 拼 ``TurnRequest`` 调 ``harness.stream()``
4. 产物收集（脚本 artifacts / agent 的 ``ARTIFACT`` 事件）
5. ``gates.run_gates()`` → 附在结果里
6. 返回 ``{result_markdown, artifacts, gate_report, cost_actual}``
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from atelier.server import paths
from atelier.server.errors import SkillMissingKey, SkillRunFailed
from atelier.server.harness.base import EventType, TurnRequest
from atelier.server.skills import executor, keys, loader
from atelier.server.skills.loader import LoadedSkill

log = logging.getLogger("atelier.skills.runner")

SYSTEM_SUFFIX = (
    "【流程提醒】动手前先查技能库（atelier/skills/），有现成技能就用，不要从零手搓。"
    "产出落盘前必须调用 atelier_gate_run 跑门禁；产物用 atelier_artifact_write 写入。"
)

# 按量计费技能的单价（CNY）。PRD 原则三：付费必须先给预估。
# 估算取保守上界；实际按生成量结算，跑完回 cost_actual。
COST_RATES: dict[str, dict] = {
    "one-video": {"unit": "秒", "rate": 0.52, "fallback_qty": 45,
                  "breakdown": [("视频生成", 0.5), ("配音", 0.02)]},
    "aigc-image": {"unit": "张", "rate": 0.35, "fallback_qty": 1,
                   "breakdown": [("文生图", 0.35)]},
}
DEFAULT_COST = {"unit": "次", "rate": 0.0, "fallback_qty": 1, "breakdown": []}


@dataclass
class RunResult:
    run_id: str
    skill_id: str
    status: str  # done | cost_pending | failed
    result_markdown: str = ""
    artifacts: list[dict] = field(default_factory=list)
    gate_report: dict | None = None
    cost_estimate: dict | None = None
    cost_actual: float = 0.0
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    error: dict | None = None
    missing_keys: list[str] = field(default_factory=list)
    project: str = ""
    duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "skill_id": self.skill_id,
            "status": self.status,
            "project": self.project,
            "result_markdown": self.result_markdown,
            "artifacts": self.artifacts,
            "gate_report": self.gate_report,
            "cost_estimate": self.cost_estimate,
            "cost_actual": self.cost_actual,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "error": self.error,
            "missing_keys": self.missing_keys,
            "duration": round(self.duration, 3),
        }


def estimate_cost(skill: LoadedSkill, params: dict) -> dict:
    """付费技能的费用预估。**只算不花**，返回给前端做确认弹窗。"""
    cfg = COST_RATES.get(skill.id, DEFAULT_COST)
    qty = cfg["fallback_qty"]
    if skill.id == "one-video":
        try:
            qty = int(params.get("duration") or qty)
        except (TypeError, ValueError):
            pass
    elif skill.id == "aigc-image":
        try:
            qty = min(4, max(1, int(params.get("count") or qty)))
        except (TypeError, ValueError):
            pass
    lines = []
    total = 0.0
    for label, rate in cfg["breakdown"]:
        amt = round(rate * qty, 2)
        total += amt
        lines.append({"label": label, "qty": f"{qty} {cfg['unit']}", "rate": rate, "amount": amt})
    return {
        "currency": "CNY",
        "amount": round(total, 2),
        "breakdown": lines,
        "note": "预估为保守上界，实际按生成量结算。确认后才会计费。",
        "requires_confirm": True,
    }


def build_prompt(skill: LoadedSkill, params: dict) -> str:
    lines = [
        f"请执行技能「{skill.name}」（{skill.id}）。",
        "",
        f"触发语：{skill.trigger}",
        "",
        "## 操作手册（严格照做）",
        "",
        skill.body_markdown,
        "",
        "## 本次参数",
        "",
    ]
    if params:
        for k, v in params.items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- （未提供参数，请用默认值或反问用户）")
    lines += ["", "完成后请把产物写入 `atelier_artifact_write` 指定的项目成品目录，并说明落盘路径。"]
    return "\n".join(lines)


def _run_gates(text: str, params: dict) -> dict | None:
    """跑门禁。地基门禁模块未就绪时降级为 None + 告警，不崩运行（并行开发期）。"""
    try:
        from atelier.server.gates.base import GateInput
        from atelier.server.gates.registry import run_gates
    except ImportError as e:
        log.warning("gates module unavailable, gate report skipped: %s", e)
        return None
    content = GateInput(
        text=text or "",
        platform=params.get("platform"),
        title=params.get("title") or params.get("topic"),
        image_paths=[],
        profile=None,
    )
    report = run_gates(content)
    return report.to_dict() if hasattr(report, "to_dict") else dict(report)


def _artifact_from_path(p: Path, kind: str = "") -> dict:
    try:
        rel = paths.rel_to_root(p)
    except Exception:  # noqa: BLE001 — 兜底成绝对路径，不让产物信息丢失
        rel = str(p)
    return {"path": rel, "name": p.name, "kind": kind or executor.guess_kind(p),
            "size": p.stat().st_size if p.exists() else 0}


async def _run_via_harness(
    skill: LoadedSkill, params: dict, project: str, profile_id: str | None, run_id: str
) -> tuple[str, list[dict], str, dict | None]:
    from atelier.server.harness.registry import get_harness

    harness = get_harness()
    req = TurnRequest(
        session_id=f"skill-{skill.id}-{profile_id or 'nop'}-{run_id[:8]}",
        turn_id=run_id,
        prompt=build_prompt(skill, params),
        profile=None,  # 画像由调用方内联（SPEC-02 §4）；本域不读 profiles/
        attachments=[],
        system_suffix=SYSTEM_SUFFIX,
        project=project,
    )
    text_parts: list[str] = []
    artifacts: list[dict] = []
    error: dict | None = None
    async for ev in harness.stream(req):
        data = ev.data or {}
        if ev.type == EventType.TEXT_DELTA:
            text_parts.append(str(data.get("text", "")))
        elif ev.type == EventType.ARTIFACT:
            raw = data.get("path")
            if raw:
                p = Path(str(raw))
                artifacts.append(_artifact_from_path(p, str(data.get("kind") or "")))
        elif ev.type == EventType.ERROR:
            error = {"message": str(data.get("message") or "AI 运行时返回错误"),
                     "detail": data.get("detail")}
        elif ev.type == EventType.DONE:
            break
    return "".join(text_parts), artifacts, "", error


async def run_skill(
    skill_id: str,
    params: dict | None = None,
    project: str = "default",
    profile_id: str | None = None,
    *,
    confirm_cost: bool = False,
) -> RunResult:
    """就地运行一个技能。``confirm_cost`` 是 SPEC-04 §6 付费确认所需的附加开关。"""
    started = time.time()
    run_id = uuid.uuid4().hex
    params = dict(params or {})
    skill = loader.get_skill(skill_id)
    result = RunResult(run_id=run_id, skill_id=skill_id, status="done", project=project)

    # 1. 前置检查：密钥
    missing = keys.missing_keys(skill.required_keys)
    if missing:
        result.missing_keys = missing
        raise SkillMissingKey(
            f"缺少密钥 {', '.join(missing)}，无法运行「{skill.name}」",
            detail={"skill_id": skill_id, "missing_keys": missing,
                    "hint": f"在「{skill.name}」卡片内的「API 配置」里填 {missing[0]}"},
        )

    # 2. 付费技能：先给费用预估，未确认不执行
    if skill.paid and not confirm_cost:
        result.status = "cost_pending"
        result.cost_estimate = estimate_cost(skill, params)
        result.result_markdown = cost_markdown(skill, result.cost_estimate)
        result.duration = time.time() - started
        log.info("cost gate: %s requires confirmation (¥%.2f)", skill_id, result.cost_estimate["amount"])
        return result

    # 3. 执行：脚本优先，否则走 AI
    if skill.script:
        script = loader.skill_script_path(skill)
        if script is None:
            raise SkillRunFailed(
                f"技能 {skill_id} 声明了脚本 {skill.script} 但找不到",
                detail={"skill_id": skill_id, "script": skill.script},
            )
        res = await executor.run_script(
            script, params=params, project=project, skill_id=skill_id, timeout=executor.LONG_TIMEOUT
        )
        result.returncode = res.returncode
        result.stdout = res.stdout
        result.stderr = res.stderr
        result.artifacts = [_artifact_from_path(a["path"], a.get("kind", "")) for a in res.artifacts]
        result.result_markdown = str(res.payload.get("result_markdown") or res.stdout.strip())
        if not res.ok:
            # 不抛 500 空壳：返回码 + stderr 摘要都带上（SPEC-01 §8）
            raise SkillRunFailed(
                f"技能执行失败：{skill.name} 返回码 {res.returncode}"
                + ("（超时）" if res.timed_out else "（见 stderr）"),
                detail={"skill_id": skill_id, "returncode": res.returncode,
                        "timed_out": res.timed_out, "stderr": res.stderr,
                        "artifacts": result.artifacts},
            )
    else:
        text, arts, _out, err = await _run_via_harness(skill, params, project, profile_id, run_id)
        result.result_markdown = text
        result.artifacts = arts
        if err:
            result.status = "failed"
            result.error = err

    # 4-5. 门禁
    result.gate_report = _run_gates(result.result_markdown, params)
    result.cost_actual = 0.0 if not skill.paid else float(
        (result.cost_estimate or {}).get("amount") or 0.0
    )
    result.duration = time.time() - started
    log.info("skill %s done in %.2fs, %d artifacts", skill_id, result.duration, len(result.artifacts))
    return result


def cost_markdown(skill: LoadedSkill, est: dict) -> str:
    """费用确认弹窗 / 对话里展示的 Markdown。"""
    lines = [f"## 「{skill.name}」按量计费，需确认后再执行", "", "本次预计消耗：", ""]
    for b in est["breakdown"]:
        lines.append(f"- {b['label']}  {b['qty']} × ¥{b['rate']}  ≈ ¥{b['amount']}")
    lines += ["", f"**合计 ≈ ¥{est['amount']}**", "", est["note"],
              "", "请确认费用后再运行（`confirm_cost: true`）。点取消不产生任何费用。"]
    return "\n".join(lines)
