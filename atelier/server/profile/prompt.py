"""SPEC-02 §4 · ★ 画像 → 消息前缀。**整个产品的地基，所有 AI 产出都经过它。**

三条不可让步的约束（PRD 4.2 验收 4、5、6）：

1. **不落全局文件、不写数据库字段**——每轮现场现拼。两个画像并发对话，
   A 的正文绝不会出现在 B 的系统提示里。
2. **通用模式完全不注入**——``general_mode=True`` 或没有画像时返回空串，
   此时 ``system_prompt`` 里一个画像字都不该有（验收 3）。
3. **每轮重申流程提醒**——对抗长对话里的指令衰减，附在 ``TurnRequest.system_suffix``。

注入点是 ``ClaudeAgentOptions(system_prompt=BASE + prefix + suffix)``。
本模块**只负责生成字符串**，不碰 SDK、不碰数据库、不碰文件系统。
"""

from __future__ import annotations

from ..core.models import Memory, Profile

__all__ = [
    "BASE_SYSTEM_PROMPT",
    "PROFILE_CLOSE_TAG",
    "PROFILE_OPEN_TAG",
    "TURN_REMINDER",
    "build_profile_prefix",
    "build_system_prompt",
    "build_turn_suffix",
    "describe_injection",
]

PROFILE_OPEN_TAG = "<account_profile>"
PROFILE_CLOSE_TAG = "</account_profile>"

#: 基础系统提示（不含画像）。这里只放不随画像变的通用约束。
BASE_SYSTEM_PROMPT = (
    "你是 Atelier 的创作助手，服务于一个私有内容工作台。\n"
    "产出要能直接发出去：结论先行、具体、能落地，不写空话套话。\n"
    "不确定的事就说不确定，不要编造数据或引用。"
)

#: 每轮重申（PRD 4.2 / 验收 6）。刻意放 system_suffix 而不是 prefix——
#: 它与画像无关，且必须出现在**每一轮**的末尾位置才能压住长对话的指令衰减。
TURN_REMINDER = (
    "【流程提醒】动手前先查技能库（skills/ 目录），有现成技能就用，不要从零手搓。\n"
    "产出落盘前必须调用 atelier_gate_run 跑门禁；图片等产物用 atelier_artifact_write 写入。"
)


def build_profile_prefix(profile: Profile | None) -> str:
    """把画像渲染成注入前缀。**通用模式 → 返回空串，一个字都不注入。**

    格式严格按 SPEC-02 §4（标题、空行、分隔都与 spec 一致）——
    这段文本会直接进模型的系统提示，改格式等于改产品行为。
    """
    if profile is None or profile.general_mode:
        return ""
    return f"""{PROFILE_OPEN_TAG}
## 定位
{profile.identity}

## 风格
{profile.style}

## 受众
{profile.audience}

## 平台约束
{profile.platform_rules}

## 偏好红线（禁止违反）
{profile.preferences}

## 长期记忆
{_memory_lines(profile.memories)}
{PROFILE_CLOSE_TAG}"""


def _memory_lines(memories: list[Memory]) -> str:
    """只注入「已采纳」的记忆。一条都没有时写「（暂无）」，不留空段。"""
    lines = ["- " + m.text for m in memories if m.adopted]
    return "\n".join(lines) or "（暂无）"


def build_turn_suffix(base_suffix: str | None = None) -> str:
    """``TurnRequest.system_suffix``：调用方的后缀在前，流程提醒固定在**末尾**。"""
    tail = TURN_REMINDER.strip()
    base = (base_suffix or "").strip()
    return f"{base}\n\n{tail}" if base else tail


def build_system_prompt(
    profile: Profile | None,
    *,
    base: str | None = None,
    suffix: str | None = None,
    include_reminder: bool = True,
) -> str:
    """完整的 ``system_prompt``：``BASE + prefix + suffix``。

    ``/api/profiles/{id}/preview`` 返回的就是这个值——**与真正发进 harness 的
    字符串走同一条函数路径**，所以「预览里看到了」等价于「这一轮真的注入了」。
    """
    parts = [base if base is not None else BASE_SYSTEM_PROMPT, build_profile_prefix(profile)]
    tail = build_turn_suffix(suffix) if include_reminder else (suffix or "")
    if tail:
        parts.append(tail)
    return "\n\n".join(p for p in parts if p)


def describe_injection(profile: Profile | None) -> dict[str, object]:
    """给 ``/preview`` 用的分块说明：哪几段拼起来、各自多长、为什么没注入。"""
    prefix = build_profile_prefix(profile)
    if profile is None:
        reason = "当前没有选择画像"
    elif profile.general_mode:
        reason = "通用模式已开启：本轮不注入任何画像内容"
    elif not prefix:
        reason = "画像六维都是空的"
    else:
        reason = "画像已内联进本轮 system_prompt"
    return {
        "injected": bool(prefix),
        "reason": reason,
        "profile_id": getattr(profile, "id", None),
        "profile_name": getattr(profile, "name", None),
        "general_mode": bool(getattr(profile, "general_mode", False)),
        "prefix_chars": len(prefix),
        "base_chars": len(BASE_SYSTEM_PROMPT),
    }
