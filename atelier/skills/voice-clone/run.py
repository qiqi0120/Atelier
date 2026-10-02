#!/usr/bin/env python3
"""voice-clone · v0 准备工具：参考音频检查 + 音色需求单（F-F25）。"""

from __future__ import annotations

import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="voice-clone")
    sample = str(sk.load_params(params, "sample", required=True, label="参考音频路径") or "").strip()
    path = Path(sample)
    if not path.exists():
        print(f"voice-clone: 参考音频不存在：{sample}", file=sys.stderr)
        return 2

    checks: list[str] = []
    ok = True
    if path.suffix.lower() == ".wav":
        try:
            info = tools.wav_info(path)
            dur = info["duration"]
            checks.append(f"时长 {dur}s（建议 10~60s）" + ("" if 10 <= dur <= 60 else " ← 不在建议区间"))
            if not 10 <= dur <= 60:
                ok = False
            checks.append(f"声道 {info['channels']}（建议单声道）" + ("" if info["channels"] == 1 else " ← 建议转单声道"))
            checks.append(f"采样率 {info['rate']}Hz（≥16kHz 为佳）" + ("" if info["rate"] >= 16000 else " ← 偏低"))
            if info["rate"] < 16000:
                ok = False
        except ValueError as e:
            checks.append(f"WAV 解析失败：{e}")
            ok = False
    else:
        checks.append(f"格式 {path.suffix}（多数供应商要求 wav/mp3；wav 信息可校验，其他格式无法本机校验）")
    size_kb = path.stat().st_size // 1024
    checks.append(f"大小 {size_kb}KB" + ("" if size_kb <= 10240 else " ← 超过常见 10MB 限制" ))

    out.mkdir(parents=True, exist_ok=True)
    dst = out / "voice-clone-checklist.md"
    dst.write_text(
        "# 音色接入需求单（v0 · 未接入供应商）\n\n"
        "## 参考音频体检\n\n"
        + "\n".join(f"- {c}" for c in checks)
        + "\n\n## 选供应商时要确认的事\n\n"
        "- 是否允许克隆本人声音（授权书要求）\n"
        "- 参考音频格式/时长/条数要求\n"
        "- 接口形态：上传样本 → 训练 → voice_id → TTS 调用\n"
        "- 计费方式（训练费 + 调用量）\n\n"
        "## 接入后的参数映射（供 AT Later）\n\n"
        f"- 参考音频：`{path}`\n"
        "- 建议接入点：`required_keys: [VOICE_CLONE_API_KEY]`，走「上传样本 → 轮询 voice_id」两步\n\n"
        f"体检结论：{'✅ 基本达标，可以接' if ok else '⚠️ 有不合格项，先按上面标注修'}\n",
        encoding="utf-8",
    )
    print(f"voice-clone: 体检完成（{'达标' if ok else '有不合格项'}）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "markdown", "name": dst.name}],
        "summary": f"参考音频体检：{'达标' if ok else '有不合格项'}（v0 未接入供应商）",
        "result_markdown": (
            "声音克隆**未接入供应商**（如实说明）。本技能交付了参考音频体检 + 接入需求单，"
            "选定供应商后按需求单配置。\n\n"
            + "\n".join(f"- {c}" for c in checks)
        ),
        "ok": ok,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
