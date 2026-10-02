"""SPEC-13 §5 · M3 制作能力测试。

- 装载：37 个新技能全部合法、layer=制作、id=目录名、全部进能力地图
- 视觉/图像/长内容：直接跑 run.py（subprocess，同 executor 约定），断言产物与回传
- ffmpeg 技能：PATH 注入**假 ffmpeg/ffprobe 脚本**做确定性测试（本机无 ffmpeg 也能测）
- 诚实路径：无 ffmpeg → 退出码 2 + 安装指引；无密钥云技能 → 明确失败不假装
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from atelier.server.gates.base import GateInput
from atelier.server.gates.registry import get_gate, run_gates
from atelier.server.skills import loader

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills"
PY = sys.executable

M3_SKILLS = [
    "quote-card", "poster", "chart", "infographic", "compare", "mindmap", "meme", "ecommerce-visual",
    "img-enhance", "img-resize", "img-decorate", "chroma-key",
    "tts", "asr", "multi-voice", "voice-clone", "ai-music", "audio-denoise", "audio-mix", "audio-visualize",
    "sub-trans", "clip-cut", "aspect-crop", "album-video", "beat-cut", "intro-outro",
    "video-chapters", "ai-drama", "video-to-article", "live-highlights",
    "pdf-extract", "paper-read", "novel-writer", "longform-outline", "framework", "data-report", "doc-convert",
]
AGENT_SKILLS = {"sub-trans", "video-chapters", "ai-drama", "video-to-article",
                "paper-read", "novel-writer", "longform-outline", "framework"}


def run_skill(skill: str, params: dict, out: Path) -> subprocess.CompletedProcess:
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [PY, str(SKILL_ROOT / skill / "run.py"),
         "--params", json.dumps(params, ensure_ascii=False), "--out", str(out)],
        capture_output=True, text=True, timeout=180, shell=False, check=False,
    )


def payload(proc: subprocess.CompletedProcess) -> dict:
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("ATELIER_RESULT "):
            return json.loads(line[len("ATELIER_RESULT "):])
    raise AssertionError(f"没有 ATELIER_RESULT 回传：{proc.stdout[-300:]} / {proc.stderr[-200:]}")


@pytest.fixture
def m3_scan():
    return loader.scan(no_cache=True, root=SKILL_ROOT)


# ---------------------------------------------------------------- 装载


class TestM3Loading:
    def test_all_m3_skills_valid(self, m3_scan) -> None:
        by_id = {s.id: s for s in m3_scan.skills}
        missing = [s for s in M3_SKILLS if s not in by_id]
        assert not missing, f"缺技能：{missing}"
        assert m3_scan.issues == [], f"装载问题：{m3_scan.issues}"
        for sid in M3_SKILLS:
            s = by_id[sid]
            assert s.layer == "制作", f"{sid} layer 应为制作"
            assert s.id == sid, "id 必须等于目录名"
            assert s.body_markdown.strip(), f"{sid} 手册为空"
        # agent 技能无 run.py；其余有
        for sid in M3_SKILLS:
            has_script = (SKILL_ROOT / sid / "run.py").exists()
            assert has_script != (sid in AGENT_SKILLS), f"{sid} 的 run.py 形态不对"

    def test_all_m3_in_capability_map(self, m3_scan) -> None:
        from atelier.server.skills import manifest

        _groups, caps = manifest.build(m3_scan.skills)
        mapped = {c.skill_id for c in caps if c.skill_id}
        missing = set(M3_SKILLS) - mapped
        assert not missing, f"M3 技能未进能力地图：{missing}"


# ---------------------------------------------------------------- 视觉


class TestVisual:
    def test_quote_card(self, tmp_path: Path) -> None:
        proc = run_skill("quote-card",
                         {"quote": "内容不是拼字数，是拼一句被人记住的话", "theme": "fresh",
                          "dataset": "完播率:38%,涨粉:1.2w"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        kinds = {a["kind"] for a in data["artifacts"]}
        assert kinds == {"image", "html"}
        for a in data["artifacts"]:
            assert Path(a["path"]).exists()
        assert data["qc_problems"] == []

    def test_quote_card_requires_quote(self, tmp_path: Path) -> None:
        proc = run_skill("quote-card", {}, tmp_path)
        assert proc.returncode == 2 and "quote" in proc.stderr

    def test_chart_bar_and_bad_type(self, tmp_path: Path) -> None:
        proc = run_skill("chart", {"type": "bar", "series": {"周一": 12, "周二": 18}}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        svg = Path(data["artifacts"][0]["path"]).read_text(encoding="utf-8")
        assert "viewBox" in svg and "周一" in svg
        bad = run_skill("chart", {"type": "nope", "series": {}}, tmp_path)
        assert bad.returncode == 2 and "type 非法" in bad.stderr

    def test_chart_pie_and_radar(self, tmp_path: Path) -> None:
        proc = run_skill("chart", {"type": "pie", "series": [{"name": "图文", "value": 12},
                                                             {"name": "视频", "value": 8}]}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        proc = run_skill("chart", {"type": "radar", "series": {"选题": 4, "剪辑": 3, "分发": 2}}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        radar_min = run_skill("chart", {"type": "radar", "series": {"a": 1, "b": 2}}, tmp_path)
        assert radar_min.returncode == 2 and "至少需要 3 个维度" in radar_min.stderr

    def test_poster_mindmap_compare_infographic(self, tmp_path: Path) -> None:
        for skill, params in [
            ("poster", {"title": "秋季上新", "bullets": "全场 8 折\n老客返券", "cta": "点击领取"}),
            ("mindmap", {"outline": "内容体系\n  选题\n    爆款拆解\n  制作\n    卡片"}),
            ("compare", {"left": "自研", "right": "外包",
                         "rows": [{"dim": "成本", "left": "低", "right": "高", "win": "left"}]}),
            ("infographic", {"title": "一周复盘", "sections": [
                {"heading": "产量", "points": ["图文 3 篇"], "metric": "曝光 4.2w"}]}),
        ]:
            proc = run_skill(skill, params, tmp_path)
            assert proc.returncode == 0, f"{skill}: {proc.stderr}"
            data = payload(proc)
            assert Path(data["artifacts"][0]["path"]).exists(), f"{skill} 产物缺失"

    def test_meme_and_ecommerce(self, tmp_path: Path) -> None:
        proc = run_skill("meme", {"top_text": "改稿前", "bottom_text": "改稿第八版"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert Path(payload(proc)["artifacts"][0]["path"]).stat().st_size > 1000
        proc = run_skill("ecommerce-visual",
                         {"product": "冷萃咖啡液", "selling_points": "0 糖 0 卡\n3 秒冷溶\n24 条装"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert len(payload(proc)["artifacts"]) == 4  # 3 主图 + 1 方案

    def test_visual_qc_gate(self) -> None:
        gate = get_gate("visual_qc")
        assert gate is not None and gate.severity.value == "warn"
        good = run_gates(GateInput.of(
            '<svg xmlns="x" viewBox="0 0 800 600"><rect fill="#EEE" width="10" height="10"/>'
            "<text>标题</text><text>副题</text><circle r=\"4\"/></svg>"), gate_ids=["visual_qc"])
        assert good.blocked is False and good.items[0].passed is True
        bad = run_gates(GateInput.of("<svg viewBox='0 0 50 50'></svg>"), gate_ids=["visual_qc"])
        assert bad.blocked is False and bad.items[0].passed is False
        assert "修正" in (bad.items[0].fix_hint or "")
        non_svg = run_gates(GateInput.of("普通文字"), gate_ids=["visual_qc"])
        assert non_svg.items[0].passed is True


# ---------------------------------------------------------------- 图像


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    from PIL import Image

    p = tmp_path / "src.png"
    Image.new("RGB", (600, 400), (120, 180, 90)).save(p, "PNG")
    return p


class TestImageSkills:
    def test_enhance(self, tmp_path: Path, sample_png: Path) -> None:
        proc = run_skill("img-enhance", {"image": str(sample_png), "scale": 2}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        from PIL import Image

        img = Image.open(payload(proc)["artifacts"][0]["path"])
        assert img.size == (1200, 800)

    def test_resize_target_kb(self, tmp_path: Path) -> None:
        from PIL import Image

        big = tmp_path / "big.jpg"
        Image.new("RGB", (2000, 1500)).save(big, "JPEG", quality=98)
        proc = run_skill("img-resize", {"image": str(big), "target_kb": "80", "format": "jpeg"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        size_kb = Path(data["artifacts"][0]["path"]).stat().st_size // 1024
        assert size_kb <= 80, "应压进目标 KB"
        assert "质量二分" in data["result_markdown"]

    def test_resize_cover_pad(self, tmp_path: Path, sample_png: Path) -> None:
        from PIL import Image

        proc = run_skill("img-resize", {"image": str(sample_png), "width": 200, "height": 200, "mode": "cover"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert Image.open(payload(proc)["artifacts"][0]["path"]).size == (200, 200)
        proc = run_skill("img-resize",
                         {"image": str(sample_png), "width": 300, "height": 300, "mode": "pad", "bg": "#FFE8D6"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert Image.open(payload(proc)["artifacts"][0]["path"]).size == (300, 300)

    def test_decorate_watermark_round_stack(self, tmp_path: Path, sample_png: Path) -> None:
        proc = run_skill("img-decorate", {"images": str(sample_png), "op": "watermark", "text": "Atelier"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        proc = run_skill("img-decorate", {"images": str(sample_png), "op": "round", "radius": 30}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        from PIL import Image

        rounded = Image.open(payload(proc)["artifacts"][0]["path"])
        assert rounded.mode == "RGBA" and rounded.getpixel((0, 0))[3] == 0
        other = tmp_path / "b.png"
        Image.new("RGB", (400, 300), (30, 30, 30)).save(other, "PNG")
        proc = run_skill("img-decorate",
                         {"images": f"{sample_png}\n{other}", "op": "stack"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        stacked = Image.open(payload(proc)["artifacts"][0]["path"])
        assert stacked.size == (600, 400 + 450 + 8)  # 第二张 400x300 对齐到最宽 600 → 600x450

    def test_chroma_key(self, tmp_path: Path) -> None:
        from PIL import Image

        gs = tmp_path / "gs.png"
        Image.new("RGB", (300, 300), (60, 200, 80)).save(gs, "PNG")  # 纯绿幕
        proc = run_skill("chroma-key", {"image": str(gs), "background": "#FFE8D6"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        out = Image.open(payload(proc)["artifacts"][0]["path"])
        assert out.getpixel((150, 150))[:3] == (255, 232, 214)  # 换成了米色背景
        not_green = tmp_path / "not-green.png"
        Image.new("RGB", (300, 300), (100, 100, 100)).save(not_green, "PNG")
        proc = run_skill("chroma-key", {"image": str(not_green)}, tmp_path)
        assert proc.returncode == 2 and "不像" in proc.stderr  # 诚实失败


# ---------------------------------------------------------------- 音频/视频（假 ffmpeg）


class FakeFfmpeg:
    """PATH 注入的假 ffmpeg/ffprobe：记录参数、产出文件、吐 canned 元数据。"""

    def __init__(self, tmp_path: Path, duration: float = 120.0) -> None:
        self.bin = tmp_path / "fakebin"
        self.bin.mkdir(exist_ok=True)
        self.calls = tmp_path / "ffmpeg-calls.log"
        self.duration = duration
        self._write_ffmpeg()
        self._write_ffprobe()

    def _script(self, name: str, body: str) -> None:
        p = self.bin / name
        p.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def _write_ffmpeg(self) -> None:
        log = self.calls
        body = f'''
echo "$@" >> {log}
# 吐 silencedetect 日志（clip-cut/energy 用）
echo "silence_start: 10.0" >&2
echo "silence_end: 12.0 | silence_duration: 2.0" >&2
echo "silence_start: 50.0" >&2
echo "silence_end: 52.0 | silence_duration: 2.0" >&2
echo "silence_start: 90.0" >&2
echo "silence_end: 91.0 | silence_duration: 1.0" >&2
# 给每个像输出路径的参数创建文件
for a in "$@"; do
  case "$a" in
    *.mp4|*.wav|*.mp3|*.png|*.jpg) mkdir -p "$(dirname "$a")"; : > "$a" ;;
  esac
done
exit 0
'''
        self._script("ffmpeg", body)

    def _write_ffprobe(self) -> None:
        d = self.duration
        self._script("ffprobe", f'''
echo '{{"format":{{"duration":"{d}"}},"streams":[{{"codec_type":"video","width":1920,"height":1080,"codec_name":"h264"}},{{"codec_type":"audio","codec_name":"aac"}}]}}'
''')

    def env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", f"{self.bin}:{os.environ.get('PATH', '')}")

    def recorded(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [line.split(" ") for line in self.calls.read_text().splitlines()]


@pytest.fixture
def fake_ff(tmp_path: Path):
    return FakeFfmpeg(tmp_path)


class TestFfmpegSkills:
    def test_missing_ffmpeg_honest_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_png: Path) -> None:
        bin_dir = tmp_path / "empty-bin"
        bin_dir.mkdir()
        monkeypatch.setenv("PATH", str(bin_dir))
        proc = run_skill("audio-denoise", {"audio": str(sample_png)}, tmp_path)
        assert proc.returncode == 2
        assert "未检测到 ffmpeg" in proc.stderr and "brew install ffmpeg" in proc.stderr

    def test_audio_denoise_params(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ff.env(monkeypatch)
        src = tmp_path / "a.mp3"
        src.write_bytes(b"x")
        proc = run_skill("audio-denoise", {"audio": str(src), "strength": "strong"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        flat = [x for call in fake_ff.recorded() for x in call]
        assert "afftdn=nr=28:nf=-70" in " ".join(flat)  # strong 参数拼对
        assert payload(proc)["artifacts"][0]["kind"] == "audio"

    def test_audio_mix_duck(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ff.env(monkeypatch)
        voice, bgm = tmp_path / "v.mp3", tmp_path / "b.mp3"
        voice.write_bytes(b"x")
        bgm.write_bytes(b"x")
        proc = run_skill("audio-mix", {"voice": str(voice), "bgm": str(bgm), "duck": "on"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        flat = " ".join(x for call in fake_ff.recorded() for x in call)
        assert "sidechaincompress" in flat and "amix" in flat

    def test_aspect_crop_blur(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ff.env(monkeypatch)
        src = tmp_path / "v.mp4"
        src.write_bytes(b"x")
        proc = run_skill("aspect-crop", {"video": str(src), "target": "vertical", "mode": "blur"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        flat = " ".join(x for call in fake_ff.recorded() for x in call)
        assert "gblur" in flat and "1080:1920" in flat
        assert payload(proc)["artifacts"][0]["kind"] == "video"

    def test_clip_cut_points_and_energy(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ff.env(monkeypatch)
        src = tmp_path / "v.mp4"
        src.write_bytes(b"x")
        proc = run_skill("clip-cut", {"video": str(src), "mode": "points", "points": "30,2:15"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        assert data["starts"] == [30.0, 135.0] and len(data["artifacts"]) == 2
        fake_ff.calls.write_text("")  # 清记录
        proc = run_skill("clip-cut", {"video": str(src), "mode": "energy", "count": 2}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        # 假 ffmpeg 吐的静音区间：12s / 52s 之后是高能段
        assert payload(proc)["starts"] == [12.0, 52.0]

    def test_album_video_and_beat_cut(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch, sample_png: Path) -> None:
        fake_ff.env(monkeypatch)
        b = tmp_path / "b.png"
        b.write_bytes(sample_png.read_bytes())
        music = tmp_path / "m.mp3"
        music.write_bytes(b"x")
        proc = run_skill("album-video", {"images": f"{sample_png}\n{b}", "audio": str(music)}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        flat = " ".join(x for call in fake_ff.recorded() for x in call)
        assert "zoompan" in flat and "xfade" in flat
        fake_ff.calls.write_text("")
        proc = run_skill("beat-cut", {"images": f"{sample_png}\n{b}", "audio": str(music), "bpm": 120}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        assert data["summary"].startswith("卡点视频")

    def test_intro_outro_and_live_highlights(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch, sample_png: Path) -> None:
        fake_ff.env(monkeypatch)
        src = tmp_path / "v.mp4"
        src.write_bytes(b"x")
        proc = run_skill("intro-outro",
                         {"video": str(src), "title": "开播啦", "outro_text": "下期见", "duration": 2}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        fake_ff.calls.write_text("")
        proc = run_skill("live-highlights", {"video": str(src), "count": 2, "duration": 30}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert len(payload(proc)["artifacts"]) == 2

    def test_audio_visualize(self, tmp_path: Path, fake_ff: FakeFfmpeg, monkeypatch: pytest.MonkeyPatch, sample_png: Path) -> None:
        fake_ff.env(monkeypatch)
        src = tmp_path / "a.wav"
        src.write_bytes(b"x")
        proc = run_skill("audio-visualize", {"audio": str(src)}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        flat = " ".join(x for call in fake_ff.recorded() for x in call)
        assert "showwavespic" in flat


class TestCloudSkills:
    def test_tts_honest_network_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # 配了 key + 指到本地拒绝端口 → 快速失败且原因明确（runner 层缺 key 时是 409）
        monkeypatch.setenv("TTS_API_KEY", "sk-test")
        monkeypatch.setenv("TTS_BASE_URL", "http://127.0.0.1:1")
        proc = run_skill("tts", {"text": "测试配音"}, tmp_path)
        assert proc.returncode == 2 and "请求失败" in proc.stderr

    def test_asr_text_limit_and_missing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proc = run_skill("asr", {"audio": "/tmp/no-such-audio.mp3"}, tmp_path)
        assert proc.returncode == 2 and "不存在" in proc.stderr

    def test_multi_voice_script_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TTS_API_KEY", "sk-test")
        monkeypatch.setenv("TTS_BASE_URL", "http://127.0.0.1:1")
        proc = run_skill("multi-voice", {"script": "没有竖线的台词"}, tmp_path)
        assert proc.returncode == 2 and "角色|台词" in proc.stderr

    def test_voice_clone_v0_check(self, tmp_path: Path) -> None:
        import wave as wave_mod

        wav = tmp_path / "ref.wav"
        with wave_mod.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000 * 30)  # 30s 单声道
        proc = run_skill("voice-clone", {"sample": str(wav)}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        assert data["ok"] is True and "未接入" in data["result_markdown"]

    def test_ai_music_v0_brief(self, tmp_path: Path) -> None:
        proc = run_skill("ai-music", {"mood": "治愈", "duration": 45}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        assert "未接入" in data["result_markdown"]
        assert Path(data["artifacts"][0]["path"]).read_text(encoding="utf-8").count("BGM") >= 1


# ---------------------------------------------------------------- 长内容


class TestLongform:
    def test_pdf_extract(self, tmp_path: Path) -> None:
        from io import BytesIO

        from pypdf import PdfWriter
        from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

        w = PdfWriter()
        page = w.add_blank_page(612, 792)
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 24 Tf 72 700 Td (Atelier paper extract test.) Tj ET")
        page[NameObject("/Contents")] = w._add_object(stream)
        font = w._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }))
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            NameObject("/ProcSet"): ArrayObject([NameObject("/PDF"), NameObject("/Text")]),
        })
        buf = BytesIO()
        w.write(buf)
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(buf.getvalue())
        proc = run_skill("pdf-extract", {"pdf": str(pdf)}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        text = Path(data["artifacts"][0]["path"]).read_text(encoding="utf-8")
        assert "Atelier paper extract test." in text and "--- 第 1 页 ---" in text

    def test_data_report_stats_are_deterministic(self, tmp_path: Path) -> None:
        csv_data = "日期,播放,点赞\n10-01,1200,80\n10-02,1800,120\n10-03,900,50"
        proc = run_skill("data-report", {"data": csv_data, "title": "三日数据"}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        data = payload(proc)
        report = Path(data["artifacts"][0]["path"]).read_text(encoding="utf-8")
        assert "均值 1300" in report and "合计 3900" in report  # 播放列统计（脚本算的）
        assert "洞察" in report
        svgs = [a for a in data["artifacts"] if a["kind"] == "image"]
        assert len(svgs) == 2  # 播放 + 点赞两张图

    def test_doc_convert(self, tmp_path: Path) -> None:
        md = "# 标题甲\n\n正文 **加粗**。\n\n| A | B |\n|---|---|\n| 1 | 2 |"
        proc = run_skill("doc-convert", {"markdown": md}, tmp_path)
        assert proc.returncode == 0, proc.stderr
        html = Path(payload(proc)["artifacts"][0]["path"]).read_text(encoding="utf-8")
        assert "<h1>" in html and "<table>" in html and "<strong>" in html

    def test_agent_skills_have_manual(self, m3_scan) -> None:
        by_id = {s.id: s for s in m3_scan.skills}
        for sid in AGENT_SKILLS:
            body = by_id[sid].body_markdown
            assert len(body) > 200, f"{sid} 手册太短，agent 没法执行"
            assert "反问" in body or "不要" in body, f"{sid} 手册应有「不编造/反问」约束"
