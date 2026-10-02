#!/usr/bin/env python3
"""asr · 云端语音识别 → SRT/TXT/JSON（F-F23，whisper 兼容）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from atelier.server.media import tools
from atelier.server.visual import svgkit as sk


def main() -> int:
    params, out, _ = sk.skill_argv(desc="asr")
    src = str(sk.load_params(params, "audio", required=True, label="音频/视频路径") or "").strip()
    path = Path(src)
    if not path.exists():
        print(f"asr: 文件不存在：{src}", file=sys.stderr)
        return 2
    fmt = str(params.get("format") or "srt")
    if fmt not in ("srt", "txt", "json"):
        print(f"asr: format 只支持 srt/txt/json（{fmt!r}）", file=sys.stderr)
        return 2
    base = os.environ.get("ASR_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("ASR_API_KEY", "")

    # 视频先抽音轨（需要本机 ffmpeg；纯音频直接传）
    upload = path
    if path.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
        exe = tools.ffmpeg()  # 缺失 → MediaToolError，诚实失败
        wav = Path(tools.run.__module__ and out) / f"{path.stem}-audio.wav"
        rc, _o, err = tools.run([exe, "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        if rc != 0:
            print(f"asr: 抽音轨失败：{err[-300:]}", file=sys.stderr)
            return 2
        upload = wav

    import httpx

    language = str(params.get("language") or "").strip()
    try:
        with open(upload, "rb") as f:
            resp = httpx.post(
                f"{base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": os.environ.get("ASR_MODEL", "whisper-1"),
                      "response_format": "verbose_json",
                      **({"language": language} if language else {})},
                files={"file": (upload.name, f)},
                timeout=600,
            )
    except httpx.HTTPError as e:
        print(f"asr: 请求失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if resp.status_code >= 400:
        print(f"asr: 服务返回 {resp.status_code}：{resp.text[:300]}", file=sys.stderr)
        return 2
    data = resp.json()
    segments = data.get("segments") or []
    text = str(data.get("text") or "").strip()

    out.mkdir(parents=True, exist_ok=True)
    arts = []
    if fmt == "json":
        dst = out / f"{path.stem}-transcript.json"
        dst.write_text(resp.text, encoding="utf-8")
        arts.append({"path": str(dst), "kind": "json", "name": dst.name})
        summary = f"转写完成：{len(segments)} 段 / {len(text)} 字（json）"
    elif fmt == "srt":
        cues = [{"idx": i, "start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")}
                for i, s in enumerate(segments, 1)]
        dst = out / f"{path.stem}.srt"
        dst.write_text(tools.build_srt(cues), encoding="utf-8")
        arts.append({"path": str(dst), "kind": "file", "name": dst.name})
        summary = f"转写完成：{len(cues)} 条字幕（srt）"
    else:
        dst = out / f"{path.stem}.txt"
        dst.write_text(text, encoding="utf-8")
        arts.append({"path": str(dst), "kind": "markdown", "name": dst.name})
        summary = f"转写完成：{len(text)} 字（txt）"

    print(f"asr: {summary}")
    sk.emit({
        "artifacts": arts,
        "summary": summary,
        "result_markdown": f"{summary}。翻译成双语/纯译文请接着用 sub-trans 技能。",
        "segments": len(segments),
        "chars": len(text),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
