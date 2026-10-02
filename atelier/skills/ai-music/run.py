#!/usr/bin/env python3
"""ai-music · v0 需求单：BGM 需求包（F-F26，未接入供应商）。"""

from __future__ import annotations

from atelier.server.visual import svgkit as sk

MOOD_TAGS = {
    "温暖": ("acoustic guitar, soft piano, 80 bpm, major key", "轻打击乐点缀，避免强鼓点"),
    "紧张": ("synth pulse, 120 bpm, minor key, rising tension", "低频持续，高潮前留 2s 静默"),
    "治愈": ("ambient pad, 70 bpm, warm reverb", "长音铺垫，别抢人声频段（2-4kHz 让位）"),
    "活力": ("upbeat pop, 128 bpm, bright synths", "鼓点清晰，副歌可给口播留白"),
}
DEFAULT = ("neutral underscore, 90 bpm", "中频让位人声，首尾各留 1s 淡入淡出")


def main() -> int:
    params, out, _ = sk.skill_argv(desc="ai-music")
    mood = str(params.get("mood") or "温暖").strip()
    try:
        duration = min(300, max(10, int(params.get("duration") or 30)))
    except (TypeError, ValueError):
        duration = 30
    scene = str(params.get("scene") or "口播背景").strip()
    desc, mix = MOOD_TAGS.get(mood, DEFAULT)

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"bgm-brief-{duration}s.md"
    dst.write_text(
        f"# BGM 需求单（投给任意音乐生成工具）\n\n"
        f"> 诚实说明：本仓库未接入音乐生成供应商，本单是给外部工具用的完整需求包。\n\n"
        f"## 基本信息\n\n- 用途：{scene}\n- 情绪：{mood}\n- 时长：{duration} 秒\n\n"
        f"## 风格描述（可直接粘贴）\n\n```\n{desc}, {duration}s, instrumental only, no vocals\n```\n\n"
        f"## 结构建议\n\n- 0~3s：淡入（避开口播第一句）\n"
        f"- 3~{duration-5}s：主体 loop\n- 后 5s：淡出\n\n"
        f"## 与口播的混音建议\n\n- {mix}\n"
        "- BGM 音量 -18dB 起，人声出现时压到 -24dB（闪避可用 audio-mix 技能）\n\n"
        "## 验收点\n\n- 无版权风险（工具的商用条款自己确认）\n- 循环点听不出接缝\n",
        encoding="utf-8",
    )
    print(f"ai-music: 需求单已生成（{mood} · {duration}s · {scene}）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "markdown", "name": dst.name}],
        "summary": f"BGM 需求单（{mood} · {duration}s · v0 未接入供应商）",
        "result_markdown": (
            "AI 音乐**未接入供应商**（如实说明）。已生成可直接投给 Suno/天工等工具的"
            f"完整需求单：风格 `{desc}`，{duration}s 结构与混音建议（配合 audio-mix 技能闪避）。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
