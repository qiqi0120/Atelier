#!/usr/bin/env python3
"""multi-voice · 按角色音色逐段合成 + 拼接（F-F24）。"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def synth(text: str, voice: str, key: str, base: str) -> bytes:
    import httpx

    resp = httpx.post(
        f"{base}/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": os.environ.get("TTS_MODEL", "tts-1"), "input": text, "voice": voice},
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"TTS 服务返回 {resp.status_code}：{resp.text[:200]}")
    return resp.content


def main() -> int:
    params, out, _ = sk.skill_argv(desc="multi-voice")
    script = str(sk.load_params(params, "script", required=True, label="台词") or "").strip()
    lines: list[tuple[str, str]] = []
    for raw in script.splitlines():
        if "|" not in raw:
            continue
        role, _, text = raw.partition("|")
        if role.strip() and text.strip():
            lines.append((role.strip(), text.strip()))
    if not lines:
        print('multi-voice: 台词格式应为每行「角色|台词」，如：旁白|开场了', file=sys.stderr)
        return 2
    voices_raw = sk.load_params(params, "voices", default={})
    voices = (json.loads(voices_raw) if isinstance(voices_raw, str) else voices_raw) or {}
    base = os.environ.get("TTS_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("TTS_API_KEY", "")

    out.mkdir(parents=True, exist_ok=True)
    seg_paths: list[Path] = []
    for i, (role, text) in enumerate(lines, 1):
        voice = str(voices.get(role) or voices.get("*") or "alloy")
        data = synth(text, voice, key, base)
        seg = out / f"seg-{i:02d}-{role}.mp3"
        seg.write_bytes(data)
        seg_paths.append(seg)
        print(f"multi-voice: [{i}/{len(lines)}] {role}（{voice}）{len(text)} 字")

    # 拼接：WAV 才能纯 Python 合并；mp3 需要 ffmpeg
    all_wav = all(p.suffix.lower() == ".wav" for p in seg_paths)
    merged_note = ""
    merged: dict | None = None
    if all_wav:
        dst = out / "multi-voice-merged.wav"
        with wave.open(str(dst), "wb") as w:
            first = True
            for p in seg_paths:
                with wave.open(str(p), "rb") as r:
                    if first:
                        w.setparams(r.getparams())
                        first = False
                    w.writeframes(r.readframes(r.getnframes()))
        merged = {"path": str(dst), "kind": "audio", "name": dst.name}
    else:
        ff = tools.have("ffmpeg")
        if ff:
            lst = out / "concat-list.txt"
            lst.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_paths), encoding="utf-8")
            dst = out / "multi-voice-merged.mp3"
            rc, _o, err = tools.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)])
            if rc == 0:
                merged = {"path": str(dst), "kind": "audio", "name": dst.name}
            else:
                merged_note = f"ffmpeg 合并失败（rc={rc}）：{err[-200:]}"
        else:
            merged_note = (
                "本机没有 ffmpeg：已交付分段文件。合并命令："
                f"`ffmpeg -f concat -safe 0 -i {out / 'concat-list.txt'} -c copy merged.mp3`"
                "（安装：brew install ffmpeg）——不假装已经拼好。"
            )
            (out / "concat-list.txt").write_text(
                "".join(f"file '{p.resolve()}'\n" for p in seg_paths), encoding="utf-8"
            )

    arts = [{"path": str(p), "kind": "audio", "name": p.name} for p in seg_paths]
    if merged:
        arts.append(merged)
    print(f"multi-voice: {len(lines)} 段完成" + ("，已合并" if merged else ""))
    sk.emit({
        "artifacts": arts,
        "summary": f"多角色配音完成：{len(lines)} 段" + ("（已合并）" if merged else "（分段交付）"),
        "result_markdown": (
            f"多角色配音完成：{len(lines)} 段，角色 {sorted({r for r, _ in lines})}。" +
            (f"\n\n⚠️ {merged_note}" if merged_note else "\n\n已合并为单文件。")
        ),
        "merged": bool(merged),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
