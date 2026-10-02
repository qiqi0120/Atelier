#!/usr/bin/env python3
"""tts · 云端文字转语音（F-F22，OpenAI 兼容接口）。"""

from __future__ import annotations

import os
import sys

from atelier.server.visual import svgkit as sk

TEXT_LIMIT = 4000


def main() -> int:
    params, out, _ = sk.skill_argv(desc="tts")
    text = str(sk.load_params(params, "text", required=True, label="文本") or "").strip()
    if len(text) > TEXT_LIMIT:
        print(f"tts: 文本 {len(text)} 字超 {TEXT_LIMIT} 上限，请分段（接口限制，如实告知）", file=sys.stderr)
        return 2
    voice = str(params.get("voice") or "alloy")
    try:
        speed = min(2.0, max(0.5, float(params.get("speed") or 1.0)))
    except (TypeError, ValueError):
        speed = 1.0
    base = os.environ.get("TTS_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("TTS_API_KEY", "")

    import httpx

    try:
        resp = httpx.post(
            f"{base}/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.environ.get("TTS_MODEL", "tts-1"), "input": text, "voice": voice, "speed": speed},
            timeout=120,
        )
    except httpx.HTTPError as e:
        print(f"tts: 请求失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if resp.status_code >= 400:
        print(f"tts: 服务返回 {resp.status_code}：{resp.text[:300]}", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"tts-{sk.slugify(text[:16])}.mp3"
    dst.write_bytes(resp.content)
    print(f"tts: {len(text)} 字 → {dst.name}（voice={voice}, speed={speed}）")
    sk.emit({
        "artifacts": [{"path": str(dst), "kind": "audio", "name": dst.name}],
        "summary": f"配音完成：{len(text)} 字 · {voice}",
        "result_markdown": (
            f"配音完成：{len(text)} 字 → mp3（音色 {voice}，语速 {speed}）。"
            "多角色/拼接请用 multi-voice；要字幕用 asr 反向生成。"
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
