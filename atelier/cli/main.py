"""SPEC-01 §11 · ``atelier`` 命令行。

五个子命令（PRD F-J1~F-J5）：

======================  =======================================================
``atelier web``         起本地服务（127.0.0.1，默认 8000）
``atelier chat``        终端里对话（流式），不需要开服务
``atelier skill <名>``  就地跑一个技能
``atelier doctor``      17 项环境体检，**每项给具体值**（PRD 原则四：不许只说「通过」）
``atelier ping``        探活：服务在不在、版本对不对
======================  =======================================================

所有子命令都能 ``--json`` 输出机器可读结果，方便接 CI。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .. import __version__
from ..launcher import is_port_free
from ..server import paths
from ..server.config import get_settings
from ..server.gates.base import GateInput
from ..server.gates.registry import run_gates

__all__ = ["DOCTOR_CHECK_COUNT", "Check", "check_all", "main", "run_doctor"]

#: SPEC-00 §3：doctor 17 项检查
DOCTOR_CHECK_COUNT = 17

#: 子进程统一约束（SPEC-01 §9：shell=False、参数数组、超时 kill、stderr 截断 8KB）
SUBPROC_TIMEOUT = 6.0
STDERR_LIMIT = 8192

OK, WARN, FAIL = "ok", "warn", "fail"
_MARK = {OK: "[OK   ]", WARN: "[WARN ]", FAIL: "[FAIL ]"}


@dataclass
class Check:
    """一项体检结果。``value`` 必须给具体值，不许空着只说「通过」。"""

    key: str
    label: str
    status: str
    value: str
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 体检子工具
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: float = SUBPROC_TIMEOUT) -> tuple[int, str, str]:
    """跑子进程：``shell=False`` + 参数数组 + 超时 kill + stderr 截断。"""
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return 127, "", f"找不到可执行文件：{cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"超时（>{timeout}s）：{cmd[0]}"
    except OSError as exc:  # pragma: no cover - 权限等
        return 126, "", f"{type(exc).__name__}: {exc}"
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "")[:STDERR_LIMIT].strip()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _key_present(*names: str) -> list[str]:
    return [n for n in names if os.environ.get(n, "").strip()]


# ---------------------------------------------------------------------------
# 17 项检查
# ---------------------------------------------------------------------------


def check_python() -> Check:
    v = platform.python_version()
    ver = tuple(int(x) for x in v.split(".")[:2] if x.isdigit())
    ok = ver >= (3, 10)
    return Check(
        "python", "Python 运行时", OK if ok else FAIL,
        f"{v}（{platform.python_implementation()}，{sys.executable}）",
        "" if ok else "需要 Python 3.10+（PRD 13）",
    )


def check_node() -> Check:
    exe = shutil.which("node")
    if not exe:
        return Check("node", "Node 运行时", WARN, "未找到 node",
                     "前端构建需要 Node 22.19+；只用后端可忽略")
    rc, out, err = _run([exe, "--version"])
    if rc != 0:
        return Check("node", "Node 运行时", FAIL, f"{exe} 存在但跑不起来：{_first_line(err)[:120]}", "重装 Node")
    raw = out.lstrip("v")
    parts = raw.split(".")
    major = int(parts[0]) if parts and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    new_enough = (major, minor) >= (22, 19)
    return Check(
        "node", "Node 运行时", OK if new_enough else WARN,
        f"{raw}（{exe}）",
        "" if new_enough else "PRD 13 要求 Node 22.19+",
    )


def check_ffmpeg() -> Check:
    exe = shutil.which("ffmpeg")
    if not exe:
        return Check("ffmpeg", "FFmpeg", WARN, "未找到 ffmpeg",
                     "视频/音频类技能（M3）会失败；文字类内容不受影响")
    rc, out, err = _run([exe, "-version"])
    if rc != 0:
        return Check("ffmpeg", "FFmpeg", FAIL, f"{exe} 存在但跑不起来：{_first_line(err)[:120]}", "重装 FFmpeg")
    return Check("ffmpeg", "FFmpeg", OK, _first_line(out)[:100] or f"{exe} 可用")


def check_chromium() -> Check:
    exe = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if exe:
        return Check("chromium", "Chromium", OK, f"{exe}")
    if sys.platform == "darwin":
        for cand in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if os.path.exists(cand):
                ver = "版本未知"
                rc, out, _ = _run([cand, "--version"])
                if rc == 0:
                    ver = out
                return Check("chromium", "Chromium", OK, f"{cand}（{ver}）")
    return Check("chromium", "Chromium", WARN, "未找到 Chromium / Chrome",
                 "扫码登录与网页抓取（M4+）需要；M1 文字链路不需要")


def check_disk() -> Check:
    st = get_settings()
    usage = shutil.disk_usage(paths.ROOT)
    free_gb = usage.free / 1024**3
    if usage.free < 512 * 1024**2:
        status, hint = FAIL, "磁盘剩余不足 512MB，先清一下"
    elif usage.free < st.min_free_mb * 1024**2:
        status, hint = WARN, f"建议留够 {st.min_free_mb // 1024}GB（视频类产物很占地方）"
    else:
        status, hint = OK, ""
    return Check("disk", "磁盘剩余", status,
                 f"{free_gb:.1f} GB 可用 / 共 {usage.total / 1024**3:.0f} GB（{paths.rel_to_root(paths.ROOT)}）", hint)


def check_output_dirs() -> Check:
    problems: list[str] = []
    for d in (paths.OUTPUTS, paths.PROFILES, paths.VAR, paths.SESSIONS):
        if not d.exists():
            problems.append(f"{paths.rel_to_root(d)} 不存在")
            continue
        if not os.access(d, os.W_OK):
            problems.append(f"{paths.rel_to_root(d)} 不可写")
    value = "outputs/ · profiles/ · var/ · var/sessions/ 均可写" if not problems else "；".join(problems)
    return Check("output_dirs", "输出目录", OK if not problems else FAIL, value,
                 "" if not problems else "跑一次 `atelier web` 会自动创建；或检查目录权限")


def check_channels() -> Check:
    """三个首发平台的通道连通性。

    M1 只做「适配 + 预检 + 编排」，真实发布是 dry-run（SPEC-00 §4.2），所以这里查的是
    **配置就绪度**（平台模块在不在、凭证配了没），不做联网探测——doctor 必须在断网时
    也能跑完。
    """
    adapters: list[str] = []
    try:
        from ..server.publish import platforms  # type: ignore[import-not-found]

        adapters = sorted(
            p.stem for p in Path(platforms.__file__).parent.glob("*.py") if not p.stem.startswith("_")
        )
        detail = f"；平台适配器 {len(adapters)} 个（{', '.join(adapters)}）" if adapters else "；平台适配器尚未就绪"
    except Exception as exc:  # noqa: BLE001 - publish 域还没写完不算 fail，但要留痕
        detail = f"；publish 域未就绪（{type(exc).__name__}）"

    creds = _key_present("XHS_COOKIE", "DY_COOKIE", "GZH_COOKIE")
    cred_txt = f"{len(creds)} 项（{', '.join(creds)}）" if creds else "0 项（dry-run 模式）"
    value = f"小红书 / 抖音 / 公众号：{cred_txt}{detail}"
    return Check("channels", "平台通道连通", WARN, value,
                 "M1 不真实发布；要真发需先配平台登录态（M4 扫码）")


def check_tts() -> Check:
    keys = _key_present("MINIMAX_API_KEY", "TTS_API_KEY")
    ff = shutil.which("ffmpeg")
    if not keys:
        return Check("tts", "TTS 通道", WARN, "未配 TTS 密钥（MINIMAX_API_KEY / TTS_API_KEY）",
                     "配音类技能（M3）不可用；文字类不受影响")
    if not ff:
        return Check("tts", "TTS 通道", WARN, f"已配 {', '.join(keys)}，但缺 ffmpeg（合不出音频文件）",
                     "装 FFmpeg")
    return Check("tts", "TTS 通道", OK, f"已配 {', '.join(keys)}，ffmpeg 就绪")


def check_cors() -> Check:
    st = get_settings()
    value = f"允许来源 {len(st.cors_origins)} 个：{', '.join(st.cors_origins)}"
    if st.is_cors_locked:
        return Check("cors", "CORS", OK, value + "（仅本地）")
    return Check("cors", "CORS", FAIL, value, "PRD 13 要求只放本地来源；检查 ATELIER_CORS_ORIGINS")


def check_csrf() -> Check:
    st = get_settings()
    if st.disable_csrf:
        return Check("csrf", "跨站写拦截", FAIL, "已被 ATELIER_DISABLE_CSRF 关掉",
                     "生产/日常使用不要关；只有自动化测试才关")
    value = (
        f"已启用：只接受 {', '.join(st.allowed_write_content_types)}；"
        f"校验 Origin 与 Sec-Fetch-Site"
    )
    return Check("csrf", "跨站写拦截", OK, value)


def check_secret_scan() -> Check:
    """自检：拿一段假密钥和一段干净文本各跑一次，两个方向都要对。"""
    fake = "sk-ant-api03-" + "A" * 40
    probe_secret = run_gates(GateInput.of(fake), gate_ids=["secret_scan"])
    probe_clean = run_gates(GateInput.of("今天去了三家咖啡馆，第二家最值得推荐，人均 38。"), gate_ids=["secret_scan"])
    if not probe_secret.blocked:
        return Check("secret_scan", "出站密钥扫描", FAIL, "探针：假密钥竟然没被拦住",
                     "门禁坏了，不能出站——先修 gates/secret_scan.py")
    if probe_clean.blocked:
        item = probe_clean.items[0]
        return Check("secret_scan", "出站密钥扫描", FAIL, f"探针：干净文本被误杀（{item.message[:60]}）",
                     "词表过宽，会挡住正常内容")
    return Check("secret_scan", "出站密钥扫描", OK, "探针：假密钥已拦、干净文本放行（fail-closed 已开）")


def check_credentials() -> Check:
    keyring = importlib.util.find_spec("keyring") is not None
    master = os.environ.get("ATELIER_MASTER_KEY", "").strip()
    enc = paths.VAR / "secrets.enc"
    if keyring:
        value = "系统 keychain 可用" + (f"；降级文件 {paths.rel_to_root(enc)} 尚未创建" if not enc.exists() else "")
        return Check("credentials", "凭证存储", OK, value)
    if master:
        return Check("credentials", "凭证存储", WARN,
                     f"无 keyring，降级到 AES-GCM 文件（{paths.rel_to_root(enc)}，主密钥来自 ATELIER_MASTER_KEY）",
                     "装 keyring 体验更好（macOS Keychain / Windows DPAPI）")
    return Check("credentials", "凭证存储", FAIL, "既没有 keyring，也没有 ATELIER_MASTER_KEY",
                 "平台凭证无法加密存储（PRD 13）；设 ATELIER_MASTER_KEY 或装 keyring")


def check_session_store() -> Check:
    probe_dir = paths.SESSIONS
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = probe_dir / ".doctor-probe"
        probe.write_text("doctor\n", encoding="utf-8")
        size = probe.stat().st_size
        probe.unlink()
    except OSError as exc:
        return Check("session_store", "会话落盘", FAIL, f"{paths.rel_to_root(probe_dir)} 写入失败：{exc}",
                     "检查 var/ 目录权限与磁盘空间")
    return Check("session_store", "会话落盘", OK,
                 f"{paths.rel_to_root(probe_dir)} 可写（探针 {size} 字节已清理）；每轮事件落 <session>/<turn>.jsonl")


def check_db() -> Check:
    from ..server.core import db

    try:
        conn = db.init_db()
        tables = [t for t in db.table_names(conn) if t in db.TABLE_NAMES]
        missing = [t for t in db.TABLE_NAMES if t not in tables]
        ver = db.schema_version(conn)
    except Exception as exc:  # noqa: BLE001
        return Check("db", "元数据库", FAIL, f"{paths.rel_to_root(db.db_path())} 初始化失败：{type(exc).__name__}: {exc}",
                     "检查 var/ 目录权限；必要时删掉 var/atelier.db 重建（元数据可从产物索引恢复）")
    if missing:
        return Check("db", "元数据库", FAIL, f"缺表 {', '.join(missing)}", "跑 `atelier web` 会补建")
    return Check("db", "元数据库", OK,
                 f"{paths.rel_to_root(db.db_path())} · schema v{ver} · {len(tables)}/{len(db.TABLE_NAMES)} 张表就绪")


def check_git() -> Check:
    exe = shutil.which("git")
    if not exe:
        return Check("git", "git 可用", WARN, "未找到 git", "版本管理与回滚会没有；不影响使用")
    _, out, _err = _run([exe, "--version"])
    inside = (paths.ROOT / ".git").exists()
    status = OK if inside else WARN
    value = f"{_first_line(out) or out}；{'当前目录是 git 仓库' if inside else '当前目录不是 git 仓库'}"
    return Check("git", "git 可用", status, value, "" if inside else "建议 git init，便于回滚")


def check_port() -> Check:
    st = get_settings()
    port = st.port
    if is_port_free(port):
        return Check("port", "服务端口", OK, f"{st.host}:{port} 可用")
    detail = "已被占用（另一个 atelier 实例？）"
    for cmd in (["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], ["netstat", "-an"]):
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        rc, out, _ = _run([exe, *cmd[1:]])
        if rc == 0 and out:
            detail = f"已被占用；占用方：{_first_line(out)[:100]}"
            break
    return Check("port", "服务端口", WARN, detail, "换端口：ATELIER_PORT=8001 atelier web")


def check_browser_session() -> Check:
    """平台登录态复用的浏览器 profile（M4 扫码登录用；M1 先看目录能不能建）。"""
    profile = paths.VAR / "browser-profile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
        reused = any(profile.iterdir()) if profile.is_dir() else False
    except OSError as exc:
        return Check("browser_session", "浏览器会话复用", FAIL, f"{paths.rel_to_root(profile)} 建不了：{exc}",
                     "检查 var/ 权限")
    return Check(
        "browser_session", "浏览器会话复用", OK if reused else WARN,
        f"{paths.rel_to_root(profile)} {'已有可复用登录态' if reused else '已就绪，尚无登录态'}",
        "" if reused else "扫码登录（M4）后会存在这里，避免每次重登",
    )


#: 顺序即报告顺序。数量必须等于 :data:`DOCTOR_CHECK_COUNT`。
CHECKS: tuple[tuple[str, str, Callable[[], Check]], ...] = (
    ("python", "Python 运行时", check_python),
    ("node", "Node 运行时", check_node),
    ("ffmpeg", "FFmpeg", check_ffmpeg),
    ("chromium", "Chromium", check_chromium),
    ("disk", "磁盘剩余", check_disk),
    ("output_dirs", "输出目录", check_output_dirs),
    ("channels", "平台通道连通", check_channels),
    ("tts", "TTS 通道", check_tts),
    ("cors", "CORS", check_cors),
    ("csrf", "跨站写拦截", check_csrf),
    ("secret_scan", "出站密钥扫描", check_secret_scan),
    ("credentials", "凭证存储", check_credentials),
    ("session_store", "会话落盘", check_session_store),
    ("db", "元数据库", check_db),
    ("git", "git 可用", check_git),
    ("port", "服务端口", check_port),
    ("browser_session", "浏览器会话复用", check_browser_session),
)


def _pad(text: str, width: int) -> str:
    """按**显示宽度**补空格（中文占两列，否则表格会歪）。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(width - w, 0)


def check_all() -> list[Check]:
    """跑完 17 项。单项检查自己抛异常也算一项 fail（体检不能被一项打挂）。"""
    # 先幂等建目录：doctor 要报的是「目录能不能用」，不是「在不在」——
    # 否则刚 clone 下来必然第 6 项 fail，而 `atelier web` 一跑就又是好的。
    try:
        paths.ensure_dirs()
    except OSError:
        pass  # 建不出来正好让第 6 项报出来
    out: list[Check] = []
    for key, label, fn in CHECKS:
        try:
            out.append(fn())
        except Exception as exc:  # noqa: BLE001
            out.append(Check(key, label, FAIL, f"检查自身异常：{type(exc).__name__}: {exc}",
                             "跑 `pytest atelier/tests/test_doctor.py` 定位"))
    return out


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def run_doctor(as_json: bool = False) -> int:
    checks = check_all()
    fails = [c for c in checks if c.status == FAIL]
    warns = [c for c in checks if c.status == WARN]
    if as_json:
        print(json.dumps(
            {
                "version": __version__,
                "total": len(checks),
                "ok": len(checks) - len(fails) - len(warns),
                "warn": len(warns),
                "fail": len(fails),
                "checks": [c.to_dict() for c in checks],
            },
            ensure_ascii=False, indent=2,
        ))
        return 1 if fails else 0

    print(f"\nAtelier 体检 · {len(checks)} 项 · v{__version__} · 根目录 {paths.ROOT}\n")
    for i, c in enumerate(checks, 1):
        print(f" {_MARK[c.status]} {i:2d}/{len(checks)}  {_pad(c.label, 16)} {c.value}")
        if c.hint:
            print(f"{' ' * 29}↳ {c.hint}")
    verdict = (
        "全绿，可以开工" if not fails
        else f"{len(fails)} 项 fail（红色那几条），先修掉再开工"
    )
    print(f"\n结论：{len(fails)} fail / {len(warns)} warn / {len(checks) - len(fails) - len(warns)} ok —— {verdict}\n")
    return 1 if fails else 0


def cmd_web(args: argparse.Namespace) -> int:
    from ..launcher import launch_web

    launch_web(host=args.host, port=args.port, reload=args.reload, log_level=args.log_level)
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    st = get_settings()
    url = f"http://{st.host}:{st.port}{'/api/health'}"
    if args.json:
        out: dict[str, Any] = {"url": url}
        try:
            with urlopen(url, timeout=args.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            out.update({"reachable": True, "server": body})
        except (URLError, OSError, json.JSONDecodeError, ValueError) as exc:
            out.update({"reachable": False, "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("reachable") else 1

    try:
        with urlopen(url, timeout=args.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"服务没起来：{url}（{type(exc).__name__}: {exc}）")
        print("提示：先在另一个终端跑 `atelier web`")
        return 1
    print(f"pong · Atelier v{body.get('version')} · {url}")
    cfg = body.get("config", {})
    print(f"  harness   : {cfg.get('harness_name')}（mock={cfg.get('mock')}）")
    print(f"  CORS      : {', '.join(cfg.get('cors_origins') or [])}")
    print(f"  跨站写拦截: {'开' if cfg.get('csrf_enabled') else '关'}")
    if body.get("router_errors"):
        print("  路由装载失败：")
        for k, v in body["router_errors"].items():
            print(f"    - {k}: {v}")
    return 0


def cmd_skill(args: argparse.Namespace) -> int:
    """就地跑一个技能。

    **技能加载/执行由 W1-B 的 ``atelier/server/skills/`` 提供**，地基层不重复实现
    （SPEC-00 §3：新能力走注册表，不得双份逻辑）。这里做三件事：校验名字、列出
    真实存在的技能目录、给出该由哪段代码接上的明确说明。
    """
    name = args.name
    root = paths.SKILLS
    available = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")) \
        if root.is_dir() else []
    if not available:
        print(f"技能目录为空：{paths.rel_to_root(root)}")
        print("提示：技能资产由 W1-B 交付（每个技能一个目录 + SKILL.md）")
        return 1
    if name not in available:
        print(f"没有技能「{name}」。可用：{', '.join(available)}")
        return 1
    print(f"技能「{name}」已就位：{paths.rel_to_root(root / name)}")
    print("但**执行器尚未接线**——由 W1-B 的 atelier/server/skills/ 提供 loader/runner/executor，")
    print("地基层不实现它以免双份加载逻辑漂移。接入方式：把下面的调用加进 cli/main.py::cmd_skill")
    print("    from atelier.server.harness.tools import atelier_skill_run")
    print(f"    print(await atelier_skill_run({name!r}, {{...}}))")
    print("（同一份入口也暴露成进程内 MCP 工具，agent 在对话里已经可以调它）")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    return asyncio.run(_chat(args))


async def _chat(args: argparse.Namespace) -> int:
    import uuid

    from ..server.harness import registry
    from ..server.harness.base import EventType, TurnRequest

    harness = registry.get_harness()
    session_id = args.session or f"cli-{uuid.uuid4().hex[:8]}"
    st = get_settings()

    print(f"Atelier 对话台 · provider={harness.name} · session={session_id}")
    if st.mock:
        print("（ATELIER_MOCK=1：输出是写死的，用于验证流程，不代表真实生成）")
    print("输入内容；空行或 /exit 退出，/stop 中断当前轮\n")

    turn_no = 0
    while True:
        if args.prompt:
            line, args.prompt = args.prompt, ""
        else:
            try:
                line = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if not line or line in ("/exit", "/quit"):
            break

        turn_no += 1
        turn_id = f"turn-{turn_no:03d}"
        req = TurnRequest(
            session_id=session_id,
            turn_id=turn_id,
            prompt=line,
            profile=None,  # 终端不带画像（画像是 Web 侧的事）
            project=args.project,
        )
        print(f"\n[turn {turn_id}] " + "-" * 40)
        try:
            async for ev in harness.stream(req):
                t = ev.type
                if t == EventType.THINKING_DELTA:
                    text = ev.data.get("text") or ""
                    if text:
                        print(f"[思考] {text}", flush=True)
                elif t == EventType.TEXT_DELTA:
                    print(ev.data.get("text", ""), end="", flush=True)
                elif t == EventType.TOOL_CALL:
                    print(f"\n[工具] {ev.data.get('name')} {json.dumps(ev.data.get('input'), ensure_ascii=False)[:200]}")
                elif t == EventType.TOOL_RESULT:
                    body = json.dumps(ev.data.get("content"), ensure_ascii=False)
                    print(f"[工具结果] {body[:300]}", flush=True)
                elif t == EventType.GATE_RESULT:
                    print(f"[门禁] {json.dumps(ev.data, ensure_ascii=False)[:300]}", flush=True)
                elif t == EventType.ARTIFACT:
                    print(f"[产物] {ev.data.get('rel_path') or ev.data.get('abs_path')}", flush=True)
                elif t == EventType.ERROR:
                    print(f"\n[错误] {ev.data.get('message')}（{ev.data.get('code', '')}）", flush=True)
                elif t == EventType.DONE:
                    if ev.data.get("interrupted"):
                        print("\n[已中断]", flush=True)
                    print(f"\n[完成 · {ev.data.get('num_turns', '-')} 轮"
                          f"{' · 已中断' if ev.data.get('interrupted') else ''}]", flush=True)
        except KeyboardInterrupt:
            await harness.interrupt(turn_id)
            print("\n[已中断]", flush=True)
        except Exception as exc:  # noqa: BLE001 - CLI 也要给 code + 人话
            code = getattr(exc, "code", type(exc).__name__)
            hint = getattr(exc, "hint", "")
            print(f"\n[失败] {code}：{exc}")
            if hint:
                print(f"       ↳ {hint}")
        print()

    await harness.aclose()
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atelier", description="Atelier · 私有内容工作台")
    p.add_argument("--version", action="version", version=f"atelier {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    w = sub.add_parser("web", help="起本地服务")
    w.add_argument("--host", default=get_settings().host)
    w.add_argument("--port", type=int, default=get_settings().port)
    w.add_argument("--reload", action="store_true", help="改代码自动重载（开发用）")
    w.add_argument("--log-level", default="info")
    w.set_defaults(func=cmd_web)

    c = sub.add_parser("chat", help="终端里对话（流式）")
    c.add_argument("prompt", nargs="?", default="", help="不给就进交互模式")
    c.add_argument("--session", default=None, help="复用某个 session id")
    c.add_argument("--project", default=None, help="把这一轮落到某个项目")
    c.set_defaults(func=cmd_chat)

    s = sub.add_parser("skill", help="就地跑一个技能")
    s.add_argument("name", help="技能 id")
    s.set_defaults(func=cmd_skill)

    d = sub.add_parser("doctor", help=f"环境体检（{DOCTOR_CHECK_COUNT} 项）")
    d.add_argument("--json", action="store_true", help="输出 JSON")
    d.set_defaults(func=lambda a: run_doctor(a.json))

    g = sub.add_parser("ping", help="探活：服务在不在")
    g.add_argument("--json", action="store_true")
    g.add_argument("--timeout", type=float, default=3.0)
    g.set_defaults(func=cmd_ping)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
