"""SPEC-02 §5 · 新建向导 4 步状态机（**全程 < 3 分钟**）。

| step | 收集 | 可跳过 |
|---|---|---|
| 1 基础信息 | 账号名、主平台、内容方向 | 否（最少要账号名） |
| 2 社媒链接 | 各平台主页 URL | ✅ |
| 3 运营意图 | 想涨粉 / 接商单 / 做转化 | ✅ |
| 4 偏好红线 | 不想出现的话、禁忌话题 | ✅ |

两条设计取舍：

1. **跳过也前进**（spec 明写「跳过也前进」）。跳过的那步留空，不写垃圾占位内容，
   之后在六维编辑页随时能补。
2. **token 化、可恢复**。进度存在 ``settings`` 表（``wizard:<token>``），
   因此中途关掉页面、乃至重启服务，回来带着 token 就能接着走完，已填内容不丢。
   用 ``settings`` 而不是内存字典，是因为「中途退出可恢复」是 spec 的验收点，
   内存字典连刷新页面都扛不住之外的场景一律作废。

**各步落到哪一维**（六维之外没有地方放，spec 也没加字段，故只写进已有维度）：

- 第 1 步 → ``name`` / ``platforms`` / ``identity``
- 第 2 步 → ``platform_rules``（平台主页链接表）
- 第 3 步 → ``identity``（追加「运营意图」段）
- 第 4 步 → ``preferences``
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from ..core import db
from ..errors import ValidationError
from . import store

__all__ = [
    "STEPS",
    "STEP_KEYS",
    "WizardState",
    "abandon",
    "create_token",
    "get_state",
    "load_state",
    "save_state",
    "step_meta",
]

#: 向导步骤的稳定 key（API 传这个，不要传序号——序号会随插入漂移）
STEP_KEYS: tuple[str, ...] = ("basic", "social", "intent", "redlines")

#: step 1 不可跳过：没有账号名就没有画像的锚点
_REQUIRED = frozenset({"basic"})


@dataclass(frozen=True)
class StepSpec:
    key: str
    index: int
    title: str
    sub: str
    fields: tuple[str, ...]
    skippable: bool
    hint: str


#: 4 步定义。``fields`` 是前端要渲染的表单项名，值原样收进 ``data``。
STEPS: tuple[StepSpec, ...] = (
    StepSpec(
        key="basic",
        index=1,
        title="基础信息",
        sub="账号名 + 主平台 + 内容方向",
        fields=("name", "platform", "direction"),
        skippable=False,
        hint="只填账号名就能继续，剩下的以后随时补",
    ),
    StepSpec(
        key="social",
        index=2,
        title="社媒链接",
        sub="各平台主页 URL",
        fields=("urls",),
        skippable=True,
        hint="先跳过也行；M2 抓取内容时再补",
    ),
    StepSpec(
        key="intent",
        index=3,
        title="运营意图",
        sub="这个号想达成什么",
        fields=("goals",),
        skippable=True,
        hint="想涨粉 / 接商单 / 做转化，可多选",
    ),
    StepSpec(
        key="redlines",
        index=4,
        title="偏好红线",
        sub="不想出现的话、禁忌话题",
        fields=("bans",),
        skippable=True,
        hint="写进「偏好红线」，产出时禁止违反",
    ),
)

_BY_KEY = {s.key: s for s in STEPS}


@dataclass
class WizardState:
    token: str
    profile_id: str
    # 已完成的步数（0–4）
    completed: int = 0
    # 已跳过的步 key
    skipped: list[str] = field(default_factory=list)
    # 各步原始输入，导出/续跑用
    data: dict[str, dict[str, Any]] = field(default_factory=dict)
    finished: bool = False

    @property
    def next_step(self) -> str:
        """下一步的 key；4 步都过完 → ``done``（spec §5 的 ``step: done``）。"""
        if self.finished or self.completed >= len(STEPS):
            return "done"
        return STEP_KEYS[self.completed]

    @property
    def progress(self) -> int:
        return min(self.completed, len(STEPS))

    @property
    def progress_label(self) -> str:
        return f"{self.progress}/{len(STEPS)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "profile_id": self.profile_id,
            "completed": self.completed,
            "progress": self.progress,
            "progress_label": self.progress_label,
            "next_step": self.next_step,
            "skipped": list(self.skipped),
            "finished": self.finished,
        }


def step_meta(key: str) -> dict[str, Any]:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise ValidationError(
            "没有这一步",
            detail={"step": key, "available": list(STEP_KEYS) + ["done"]},
            hint="step 取 basic / social / intent / redlines，或 done 结束向导",
        )
    return {
        "key": spec.key,
        "index": spec.index,
        "title": spec.title,
        "sub": spec.sub,
        "fields": list(spec.fields),
        "skippable": spec.skippable,
        "hint": spec.hint,
    }


# ---------------------------------------------------------------------------
# 状态存取（settings 表，跨进程存活）
# ---------------------------------------------------------------------------


def _state_key(token: str) -> str:
    return f"wizard:{token}"


def create_token(profile_id: str, *, profile_name: str = "") -> str:
    """新建一个 token 并把初始进度落库。返回 token（spec §5：新建响应里带）。"""
    store.get_profile(profile_id)  # 不存在 → ProfileNotFound
    token = secrets.token_urlsafe(12)
    state = WizardState(token=token, profile_id=profile_id, data={"_name": {"name": profile_name}})
    save_state(state)
    return token


def save_state(state: WizardState) -> WizardState:
    conn = db.get_conn()
    payload = json.dumps(
        {
            "profile_id": state.profile_id,
            "completed": state.completed,
            "skipped": state.skipped,
            "data": state.data,
            "finished": state.finished,
        },
        ensure_ascii=False,
    )
    with db.db_session():
        conn.execute(
            "INSERT INTO settings (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (_state_key(state.token), payload),
        )
    return state


def load_state(token: str) -> WizardState | None:
    row = db.get_conn().execute("SELECT v FROM settings WHERE k=?", (_state_key(token),)).fetchone()
    if row is None:
        return None
    try:
        raw = json.loads(row["v"] or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return WizardState(
        token=token,
        profile_id=str(raw.get("profile_id") or ""),
        completed=int(raw.get("completed") or 0),
        skipped=list(raw.get("skipped") or []),
        data=dict(raw.get("data") or {}),
        finished=bool(raw.get("finished")),
    )


def get_state(token: str) -> WizardState:
    state = load_state(token)
    if state is None:
        raise ValidationError(
            "向导进度找不到了",
            detail={"token": token},
            hint="这个 token 已过期（完成或放弃后会清掉）；重新建一个画像走一遍向导",
        )
    return state


def abandon(token: str) -> dict[str, Any]:
    """中途放弃：清掉进度，**已填进画像的内容全部保留**（spec §5）。"""
    state = get_state(token)
    conn = db.get_conn()
    with db.db_session():
        conn.execute("DELETE FROM settings WHERE k=?", (_state_key(token),))
    return {"abandoned": True, "profile_id": state.profile_id, "kept": True}


# ---------------------------------------------------------------------------
# 步进
# ---------------------------------------------------------------------------


def advance(
    token: str,
    step: str,
    data: dict[str, Any] | None = None,
    *,
    skip: bool = False,
) -> WizardState:
    """走一步：校验 → 把这一步落进画像维度 → 推进进度。

    ``step="done"`` 直接结束。**第 1 步不可跳过**（spec §5），其余每步都能跳，
    跳过后照样推进——这是「全程 < 3 分钟」的关键。
    """
    state = get_state(token)
    store.get_profile(state.profile_id)  # 画像被删了就 404，别留下悬空进度

    if step == "done":
        state.finished = True
        return save_state(state)

    spec = _BY_KEY.get(step)
    if spec is None:
        raise ValidationError(
            "没有这一步",
            detail={"step": step, "available": list(STEP_KEYS) + ["done"], "expecting": state.next_step},
            hint="step 取 basic / social / intent / redlines，或 done 结束向导",
        )

    payload = dict(data or {})
    wants_skip = bool(skip) or not any(str(v).strip() for v in payload.values())
    if wants_skip and spec.key in _REQUIRED:
        raise ValidationError(
            "第一步要先给账号名",
            detail={"step": spec.key, "need": ["name"]},
            hint="只填账号名就能继续；其余内容以后在六维编辑页补",
        )

    if not wants_skip:
        _apply_step(state.profile_id, spec, payload)

    state.data[spec.key] = payload
    if wants_skip:
        state.skipped.append(spec.key)
    state.completed = max(state.completed, spec.index)
    return save_state(state)


def _apply_step(profile_id: str, spec: StepSpec, data: dict[str, Any]) -> None:
    """把一步的输入折进六维。**只增不覆盖**——已写好的正文不会被向导覆盖掉。"""
    if spec.key == "basic":
        changes: dict[str, Any] = {}
        name = str(data.get("name") or "").strip()
        if name:
            changes["name"] = name
        platform = str(data.get("platform") or "").strip()
        if platform:
            profile = store.get_profile(profile_id)
            if platform not in profile.platforms:
                changes["platforms"] = [*profile.platforms, platform]
        direction = str(data.get("direction") or "").strip()
        if direction:
            changes["identity"] = _append_section("", direction, "内容方向")
        if changes:
            store.update_profile(profile_id, changes)
        return

    if spec.key == "social":
        urls = _urls_block(data.get("urls"))
        if not urls:
            return
        profile = store.get_profile(profile_id)
        store.update_profile(
            profile_id, {"platform_rules": _append_section(profile.platform_rules, urls, "社媒主页")}
        )
        return

    if spec.key == "intent":
        goals = _bullets(data.get("goals"))
        if not goals:
            return
        profile = store.get_profile(profile_id)
        store.update_profile(
            profile_id, {"identity": _append_section(profile.identity, goals, "运营意图")}
        )
        return

    if spec.key == "redlines":
        bans = _bullets(data.get("bans"))
        if not bans:
            return
        profile = store.get_profile(profile_id)
        store.update_profile(
            profile_id, {"preferences": _append_section(profile.preferences, bans, "我不想要的")}
        )


def _bullets(raw: Any) -> str:
    """把「多选/多行输入」归一成 Markdown 列表。"""
    items: list[str] = []
    if isinstance(raw, str):
        parts = [p for p in raw.replace("，", "\n").replace("、", "\n").splitlines()]
        items = [p.strip() for p in parts if p.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(p).strip() for p in raw if str(p).strip()]
    return "\n".join(f"- {x}" for x in items)


def _urls_block(raw: Any) -> str:
    """社媒链接 → Markdown 表格（平台 | 主页）。"""
    rows: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        rows = [(str(k).strip(), str(v).strip()) for k, v in raw.items() if str(v).strip()]
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            text = str(item).strip()
            if not text:
                continue
            if isinstance(item, dict):
                name = str(item.get("platform") or item.get("name") or "主页").strip()
                url = str(item.get("url") or "").strip()
            else:
                name, _, url = text.partition(" ")
            if url:
                rows.append((name or "主页", url))
    elif isinstance(raw, str) and raw.strip():
        rows = [("主页", line.strip()) for line in raw.splitlines() if line.strip()]
    if not rows:
        return ""
    out = ["| 平台 | 主页 |", "|---|---|"]
    out += [f"| {n} | {u} |" for n, u in rows]
    return "\n".join(out)


def _append_section(existing: str, block: str, heading: str) -> str:
    """在已有正文后面追加一个小节。标题已存在就替换那一段，不重复堆叠。"""
    body = (existing or "").strip()
    chunk = f"## {heading}\n\n{block.strip()}"
    if not body:
        return chunk
    marker = f"## {heading}"
    lines = body.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == marker), None)
    if idx is None:
        return f"{body}\n\n{chunk}"
    end = next(
        (i for i in range(idx + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    kept = lines[:idx] + lines[end:]
    merged = [*kept, *chunk.splitlines()]
    while merged and not merged[-1].strip():
        merged.pop()
    return "\n".join(merged).strip()
