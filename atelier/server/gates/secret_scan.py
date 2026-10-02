"""门禁：出站内容密钥扫描（BLOCK，**fail-closed**）。

SPEC-01 §5 / §9：``secret_scan`` 必须是 fail-closed——**扫描器自己抛异常时按
「命中」处理**，宁可误杀不可漏放。实现方式是把整个扫描过程包在 ``try`` 里，
任何异常（含正则表被破坏、输入类型不对）都产出一条 BLOCK 失败项。

这份门禁是双保险的其中一半（SPEC-01 §9）：另一半是
``harness/tools.py::atelier_artifact_write`` 在真正写盘前再跑一次，
所以即使模型绕过提示词直接写文件，密钥也落不了盘。
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .base import GateInput, GateItem, Severity, ai_item
from .registry import register

__all__ = ["PATTERN_SPECS", "SecretScanGate", "scan_secrets"]

#: (规则名, 正则)。顺序即报告顺序。
PATTERN_SPECS: tuple[tuple[str, str], ...] = (
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    ("openai_style_key", r"\bsk-(?!ant-)[A-Za-z0-9]{20,}"),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ("private_key_block", r"-{3,}\s*BEGIN(?:\s+[A-Z0-9]+)*\s*PRIVATE KEY\s*-{3,}"),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("stripe_live_key", r"\b[rs]k_live_[A-Za-z0-9]{16,}\b"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    (
        "assigned_secret",
        (
            r"(?i)\b(?:api[_\-]?key|secret[_\-]?key|access[_\-]?token"
            r"|auth[_\-]?token|password|passwd|pwd)"
            r"\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-\+/]{16,}[\"']?"
        ),
    ),
)

#: 正则缓存（进程内复用）。:func:`_patterns` 每次都校验这张表的完整性。
_PATTERNS: dict[str, re.Pattern[str]] = {name: re.compile(rx) for name, rx in PATTERN_SPECS}

#: 每条规则的处置建议（不给出真实密钥片段，只给类型）
_ADVICE: dict[str, str] = {
    "anthropic_key": "把 ANTHROPIC_API_KEY 放进环境变量或「设置」页，正文里只留 $ANTHROPIC_API_KEY",
    "openai_style_key": "密钥移出正文，改用占位符",
    "aws_access_key": "AWS Access Key 泄了要去 IAM 里禁用并轮换，正文里只留 AKIA…（已打码）",
    "github_token": "去 GitHub Settings → Developer settings 撤销该 token 并重建",
    "private_key_block": "私钥绝不能进内容；确认没贴错文件",
    "jwt": "JWT 不能外发；改用平台官方授权方式",
    "slack_token": "去 Slack app 管理页撤销该 token",
    "stripe_live_key": "立刻在 Stripe 后台 roll key",
    "google_api_key": "去 Google Cloud 控制台限制并轮换该 key",
    "assigned_secret": "密钥移出正文，改成「见 .env」这样的指路",
}


def _patterns() -> dict[str, re.Pattern[str]]:
    """返回规则表；表被破坏就抛异常（由上层转成 fail-closed 命中）。"""
    if set(_PATTERNS) != {name for name, _ in PATTERN_SPECS}:
        raise RuntimeError("secret_scan 规则表不完整，拒绝以「无命中」放行")
    for name, rx in _PATTERNS.items():
        if not isinstance(rx, re.Pattern):
            raise TypeError(f"secret_scan 规则 {name} 不是合法正则")
        if not rx.pattern:
            raise ValueError(f"secret_scan 规则 {name} 模式为空")
    return _PATTERNS


def _masked(value: str) -> str:
    """报告里只给前后 4 位，绝不回显完整密钥。"""
    if len(value) <= 12:
        return "***"
    return f"{value[:4]}…{value[-4:]}（{len(value)} 字符）"


def _scan_one(text: str, where: str) -> list[dict[str, str]]:
    rules = _patterns()
    out: list[dict[str, str]] = []
    for name, rx in rules.items():
        for m in rx.finditer(text):
            out.append(
                {
                    "rule": name,
                    "where": where,
                    "masked": _masked(m.group(0)),
                    "advice": _ADVICE.get(name, "把密钥移出内容"),
                }
            )
    return out


def scan_secrets(text: str, title: str | None = None) -> list[dict[str, str]]:
    """扫正文 + 标题，返回命中列表。异常直接向上抛（调用方负责 fail-closed）。"""
    hits: list[dict[str, str]] = []
    hits += _scan_one(text or "", "正文")
    if title:
        hits += _scan_one(title, "标题")
    return hits


@register
class SecretScanGate:
    """出站内容密钥扫描，fail-closed。"""

    id = "secret_scan"
    label = "密钥扫描"
    severity = Severity.BLOCK
    doc = "出站内容里的 API key / token / 私钥，扫描器异常时按命中处理（fail-closed）"

    def run(self, content: GateInput) -> GateItem:
        try:
            hits = scan_secrets(content.text, content.title)
        except Exception as exc:  # noqa: BLE001 - fail-closed 是这个门禁的全部意义
            return ai_item(
                gate=self.id,
                label="密钥扫描（扫描器异常，按命中处理）",
                passed=False,
                actual=f"{type(exc).__name__}",
                limit="0 个密钥",
                message=(
                    f"密钥扫描器自身异常，按「命中」阻断（fail-closed）：{type(exc).__name__}: {exc}。"
                    "宁可误杀不可漏放，内容未落盘。"
                ),
                fix_hint="跑 `atelier doctor` 看诊断；确认环境正常后重试",
            )

        if not hits:
            return ai_item(
                gate=self.id,
                label="密钥扫描",
                passed=True,
                actual=0,
                limit="0 个密钥",
                message="未检出 API key / token / 私钥",
                fix_hint=None,
            )

        detail = "；".join(f"{h['rule']}（{h['where']}：{h['masked']}）" for h in hits)
        return ai_item(
            gate=self.id,
            label=f"密钥扫描（{len(hits)} 处）",
            passed=False,
            actual=detail,
            limit="0 个密钥",
            message=f"内容里检出 {len(hits)} 处疑似密钥，已阻断落盘：{detail}",
            fix_hint=hits[0]["advice"],
        )


#: 给 doctor 用的自检入口（也顺手当 ``_patterns`` 的可视探针）
def probe() -> Callable[[str], list[dict[str, str]]]:
    return scan_secrets
