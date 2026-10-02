"""媒体技能共享工具（SPEC-13 §2）：ffmpeg 检测/调用、probe、SRT、wav 信息。

诚实边界：ffmpeg/ffprobe 用 ``shutil.which`` 运行时检测；缺失抛
:class:`MediaToolError`，消息带安装指引——技能脚本把它翻成非零退出 + stderr，
前端看到的是明确失败而非含糊 500。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

__all__ = [
    "MediaToolError",
    "build_srt",
    "ffmpeg",
    "ffprobe",
    "have",
    "parse_srt",
    "probe",
    "require",
    "run",
    "seconds_to_ts",
    "ts_to_seconds",
    "wav_info",
]

FFMPEG_HINT = "需要 ffmpeg：macOS `brew install ffmpeg`，Debian/Ubuntu `sudo apt install ffmpeg`，Windows `winget install ffmpeg`"


class MediaToolError(Exception):
    """ffmpeg/ffprobe 不可用或执行失败（消息给人看，直接进 stderr）。"""


def have(tool: str) -> str | None:
    """工具在 PATH 上返回其路径，否则 None。"""
    return shutil.which(tool)


def require(tool: str) -> str:
    p = have(tool)
    if p is None:
        raise MediaToolError(f"未检测到 {tool}。{FFMPEG_HINT}")
    return p


def ffmpeg() -> str:
    return require("ffmpeg")


def ffprobe() -> str:
    return require("ffprobe")


def run(cmd: list[str], *, timeout: int = 600) -> tuple[int, str, str]:
    """跑外部命令：shell=False + 参数数组 + 超时（地基子进程约束）。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=False, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"命令超时（>{timeout}s）：{' '.join(cmd[:3])}…") from exc
    return proc.returncode, proc.stdout, proc.stderr


def probe(path: str | Path) -> dict:
    """ffprobe 元数据：duration / width / height / codec，失败给明确错误。"""
    exe = ffprobe()
    rc, out, err = run(
        [exe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        timeout=120,
    )
    if rc != 0:
        raise MediaToolError(f"ffprobe 读取失败：{(err or out).strip()[:300]}")
    data = json.loads(out or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float(fmt.get("duration") or video.get("duration") or audio.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": video.get("codec_name", ""),
        "audio_codec": audio.get("codec_name", ""),
    }


_TS = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})$")


def ts_to_seconds(ts: str) -> float:
    """``HH:MM:SS,mmm`` → 秒（SRT 口径）。非法抛 ValueError。"""
    m = _TS.match(ts.strip().replace(".", ","))
    if not m:
        raise ValueError(f"时间戳不合法：{ts!r}（应为 HH:MM:SS,mmm）")
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def seconds_to_ts(sec: float, *, comma: bool = True) -> str:
    """秒 → ``HH:MM:SS,mmm``（comma=False 时小数点，VTT 口径）。"""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    mi = int(sec % 3600 // 60)
    s = int(sec) % 60
    ms = round((sec - int(sec)) * 1000)
    if ms >= 1000:
        ms = 999
    sep = "," if comma else "."
    return f"{h:02d}:{mi:02d}:{s:02d}{sep}{ms:03d}"


_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


def parse_srt(text: str) -> list[dict]:
    """SRT → ``[{idx, start, end, text}]``，start/end 是秒。空块跳过。"""
    cues: list[dict] = []
    for m in _SRT_BLOCK.finditer(text.replace("\r\n", "\n")):
        body = m.group(4).strip()
        if not body:
            continue
        cues.append(
            {
                "idx": int(m.group(1)),
                "start": ts_to_seconds(m.group(2)),
                "end": ts_to_seconds(m.group(3)),
                "text": body,
            }
        )
    return cues


def build_srt(cues: list[dict]) -> str:
    """``[{idx,start,end,text}]`` → SRT 文本。idx 缺省自动编号。"""
    out: list[str] = []
    for i, c in enumerate(cues, 1):
        idx = c.get("idx") or i
        out.append(
            f"{idx}\n{seconds_to_ts(float(c['start']))} --> {seconds_to_ts(float(c['end']))}\n{str(c['text']).strip()}\n"
        )
    return "\n".join(out)


def wav_info(path: str | Path) -> dict:
    """标准库 wave 读 wav 头：时长/声道/采样率/位深。非 wav 抛 ValueError。"""
    p = Path(path)
    try:
        with wave.open(str(p), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return {
                "duration": round(frames / rate, 2) if rate else 0.0,
                "channels": w.getnchannels(),
                "rate": rate,
                "sampwidth": w.getsampwidth(),
                "bytes": p.stat().st_size,
            }
    except wave.Error as exc:
        raise ValueError(f"不是可读的 WAV 文件：{p.name}（{exc}）") from exc
