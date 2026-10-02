"""SPEC-01 §6 · 共享数据模型（全局契约，模型名与字段在 §11 冻结）。

刻意保持**纯数据**：这里只有 pydantic 校验 + 少量派生方法（``Profile.completeness``、
``PlatformVariant`` 的字数核算），不碰数据库、不碰文件系统、不抛 AtelierError。
业务域（profile / sessions / library / publish）自己负责持久化与错误语义。

字段严格按 SPEC-01 §6 转写，包括「有没有默认值」——``turn_id: str | None``（无默认值）
和 ``error: str | None = None``（有默认值）在 spec 里是不同的，调用方要按 spec 传。
唯一偏离：spec 里写的可变默认 ``= []`` 换成 ``Field(default_factory=list)``
（可变默认值在 Python 里是共享对象，这是 spec 的笔误，不算接口变更）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from ..gates.base import Severity

__all__ = [
    "DIMENSION_LABELS",
    "PROFILE_DIMENSIONS",
    "Attachment",
    "Capability",
    "Memory",
    "Message",
    "PlatformVariant",
    "PrecheckItem",
    "Profile",
    "PublishDraft",
    "Session",
    "SkillMeta",
    "SkillParam",
    "to_dict",
    "utcnow",
]

#: 画像六维的 key（``completeness()`` 的返回键，前端按这个渲染雷达图）
PROFILE_DIMENSIONS: tuple[str, ...] = (
    "identity",
    "style",
    "audience",
    "platform_rules",
    "preferences",
    "memories",
)

#: 六维中文名（API 侧一并返回，前端不用再翻译）
DIMENSION_LABELS: dict[str, str] = {
    "identity": "定位",
    "style": "风格",
    "audience": "受众",
    "platform_rules": "平台约束",
    "preferences": "偏好红线",
    "memories": "长期记忆",
}

#: 文本型五维（``memories`` 单独处理，它是列表不是文本）
_TEXT_DIMS: tuple[str, ...] = PROFILE_DIMENSIONS[:-1]

#: 长期记忆这一维的别名
MEMORY_LABELS: tuple[str, ...] = ("长期记忆", "记忆")

#: 中文标签 → 英文 key（``Profile.dimension()`` 反查用）
_LABEL_TO_KEY: dict[str, str] = {v: k for k, v in DIMENSION_LABELS.items()}

#: 单维「写满」的参考长度（够用了就 100 分，不做语义判断）
_FULL_CHARS = 80

_WS = re.compile(r"\s+")


def utcnow() -> datetime:
    """带时区的当前时间。与 db.utcnow() 同一口径（ISO8601 UTC）。"""
    return datetime.now(UTC)


def _count_chars(text: str) -> int:
    """非空白字符数，口径与门禁 ``wordcount.count_chars`` 一致。"""
    return len(_WS.sub("", text or ""))


class Memory(BaseModel):
    """长期记忆条目（PRD F-A6）。"""

    id: str
    text: str
    source: str  # "归因" | "手动" | "对话内记下"
    created_at: datetime
    adopted: bool = True


class Attachment(BaseModel):
    """素材附件。``path`` 相对 ``outputs/``（SPEC-01 §6）。"""

    id: str
    kind: Literal["image", "video", "audio", "doc"]
    path: str  # 相对 outputs/
    name: str
    size: int
    mime: str


class Profile(BaseModel):
    """创作者画像（六维）。``general_mode=True`` 时不注入系统提示（PRD 4.2）。"""

    id: str
    name: str
    platforms: list[str]
    identity: str = ""  # 定位
    style: str = ""  # 风格
    audience: str = ""  # 受众
    platform_rules: str = ""  # 平台约束
    preferences: str = ""  # 偏好红线
    memories: list[Memory] = []
    general_mode: bool = False  # 通用模式：不注入画像
    created_at: datetime
    updated_at: datetime

    def completeness(self) -> dict[str, int]:
        """六维各 0-100。

        纯长度启发式：写够 :data:`_FULL_CHARS` 字即满分，线性插值。
        长期记忆按**条数**算（每条 25 分，4 条满分）——记忆是要攒的，不是要长的。
        """
        out: dict[str, int] = {}
        for dim in ("identity", "style", "audience", "platform_rules", "preferences"):
            n = len((getattr(self, dim) or "").strip())
            out[dim] = int(min(100, round(n / _FULL_CHARS * 100)))
        adopted = [m for m in self.memories if m.adopted]
        out["memories"] = int(min(100, len(adopted) * 25))
        return out

    def dimension(self, name: str) -> str:
        """取某一维的文本（``atelier_profile_get`` 工具用，SPEC-01 §4）。

        ``name`` 同时接受英文 key（``identity``）与中文标签（``定位``）——agent 与前端
        说的是中文，别让调用方自己维护映射表。``memories`` / ``all`` 特殊处理。
        """
        if name == "all":
            return "\n".join(
                f"## {DIMENSION_LABELS[d]}\n{getattr(self, d)}" for d in _TEXT_DIMS
            )
        if name in ("memories", "memory", *MEMORY_LABELS):
            return "\n".join(f"- {m.text}（{m.source}）" for m in self.memories if m.adopted)
        if name in _TEXT_DIMS:
            return getattr(self, name, "")
        key = _LABEL_TO_KEY.get(name)
        if key in _TEXT_DIMS:
            return getattr(self, key, "")
        raise ValueError(
            f"没有这一维：{name}（可用：{', '.join(DIMENSION_LABELS)} / all）"
        )


class Session(BaseModel):
    id: str
    title: str
    profile_id: str | None
    created_at: datetime
    updated_at: datetime
    archived: bool = False
    last_turn_id: str | None = None


class Message(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    text: str
    turn_id: str | None
    attachments: list[Attachment] = []
    gate_report: dict | None = None
    created_at: datetime


class SkillParam(BaseModel):
    key: str
    label: str
    default: str = ""


class SkillMeta(BaseModel):
    """技能元信息（``body_markdown`` 是 SKILL.md 正文，``script`` 是入口脚本相对路径）。"""

    id: str
    name: str
    layer: Literal["发现", "策划", "制作", "发布", "归因", "通用"]
    maturity: Literal["v0", "v1", "v2", "v3"]  # 已验证/可用/需配置/接入中
    trigger: str  # F-C2 触发语
    cost: str  # "本地 · 免费" / "按量计费 · 需密钥"
    required_keys: list[str]
    params: list[SkillParam]
    body_markdown: str
    script: str | None


class Capability(BaseModel):
    """能力地图条目（PRD F-C1 两级组织：group → name）。"""

    id: str
    group: str  # "做内容 · 要成品"
    name: str
    trigger: str
    maturity: Literal["v0", "v1", "v2", "v3"]
    skill_id: str | None


class PlatformVariant(BaseModel):
    """母版 → 单平台版本的适配结果（字数超限红标并阻断发布，M1 出口标准 7）。"""

    platform: Literal["xhs", "dy", "gzh"]
    title: str
    body: str
    char_count: int
    char_limit: int
    over_limit: bool
    adapted: bool
    status: Literal["pending", "adapting", "ready", "publishing", "sent", "failed"]
    error: str | None = None
    published_url: str | None = None

    def recount(self) -> PlatformVariant:
        """按当前 body 重算字数与超限标记（不重置 status）。"""
        self.char_count = _count_chars(self.body)
        self.over_limit = self.char_count > self.char_limit
        return self


class PublishDraft(BaseModel):
    id: str
    project: str | None
    title: str
    body: str
    topic_tags: list[str]
    variants: list[PlatformVariant]
    attachments: list[str]
    #: 关联选题（可空，SPEC-10 §0 D5；删选题不级联，悬空引用由读侧降级）
    topic_id: str | None = None
    #: 计划发布日 YYYY-MM-DD（可空；人工排期上日历，非平台定时发送——那是 M4 F-G20）
    scheduled_date: str | None = None
    created_at: datetime
    updated_at: datetime


class PrecheckItem(BaseModel):
    """发布前预检项（severity 复用门禁的 :class:`Severity`，前端上色统一）。"""

    id: str
    label: str
    severity: Severity
    passed: bool
    message: str
    fix_hint: str | None = None
    platform: str | None = None


# 前向引用（Profile→Memory、Message→Attachment、SkillMeta→SkillParam、PublishDraft→PlatformVariant）
# 需要在全部类定义后显式 rebuild，否则 pydantic 解析不了字符串注解
for _model in (Profile, Message, SkillMeta, PublishDraft, PlatformVariant, PrecheckItem):
    _model.model_rebuild()


def to_dict(model: BaseModel) -> dict[str, Any]:
    """统一的可 JSON 化导出（datetime → ISO8601 字符串）。"""
    return model.model_dump(mode="json")
