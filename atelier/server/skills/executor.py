"""脚本沙箱执行（SPEC-04 §6 / SPEC-01 §9）。

铁律：
- ``asyncio.create_subprocess_exec`` + ``shell=False``，参数数组传入（**不拼 shell 字符串**）
- 工作目录 = ``outputs/<project>/``
- 超时默认 600s（长任务允许 2h），超时强制 kill
- 失败返回 **stderr 摘要 8KB + 返回码**，绝不允许只报 500 空壳
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from atelier.server import paths
from atelier.server.errors import ValidationError

log = logging.getLogger("atelier.skills.executor")

DEFAULT_TIMEOUT = 600
LONG_TIMEOUT = 7200
STDERR_LIMIT = 8 * 1024
STDOUT_LIMIT = 64 * 1024
RESULT_PREFIX = "ATELIER_RESULT "


@dataclass
class ScriptResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    duration: float = 0.0
    artifacts: list[dict] = field(default_factory=list)
    payload: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "returncode": self.returncode,
            "ok": self.ok,
            "timed_out": self.timed_out,
            "duration": round(self.duration, 3),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "artifacts": self.artifacts,
        }


def _tail(text: str, limit: int) -> str:
    """取尾部 ``limit`` 字节（崩溃 traceback 在尾部），并标注截断。"""
    b = text.encode("utf-8", "replace")
    if len(b) <= limit:
        return text
    cut = b[-limit:].decode("utf-8", "replace")
    return f"…（前 {len(b) - limit} 字节已截断）\n{cut}"


def project_workdir(project: str) -> Path:
    """技能脚本的工作目录 = ``outputs/<project>/``，并保证存在。"""
    if not project or not isinstance(project, str):
        raise ValidationError("缺少 project 名，技能脚本需要明确的工作目录")
    try:
        d = paths.product_dir(project)
    except Exception as e:
        raise ValidationError(f"项目名不合法：{project}（{e}）") from e
    workdir = d.parent
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def script_out_dir(project: str, skill_id: str) -> Path:
    """脚本产物目录 = ``outputs/<项目>/成品/<skill_id>/``（SPEC-01 F-G4 分区）。

    与工作目录不同：cwd 是 ``outputs/<项目>/``（SPEC-04 §6），
    但产物按成品/素材分区落盘。用 ``resolve_inside`` 兜住 skill_id，防路径逃逸。
    """
    base = paths.product_dir(project)
    out = paths.resolve_inside(base, skill_id or "misc")
    out.mkdir(parents=True, exist_ok=True)
    return out


def parse_artifacts(stdout: str, workdir: Path) -> tuple[list[dict], dict]:
    """抓取脚本最后一行 ``ATELIER_RESULT {json}``。"""
    payload: dict = {}
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                payload = json.loads(line[len(RESULT_PREFIX) :])
            except json.JSONDecodeError as e:
                log.error("ATELIER_RESULT is not valid JSON: %s", e)
            break
    arts: list[dict] = []
    for a in payload.get("artifacts") or []:
        if not isinstance(a, dict) or not a.get("path"):
            continue
        p = Path(str(a["path"]))
        # 脚本只允许写工作目录内的文件
        try:
            rel = p.resolve().relative_to(workdir.resolve())
        except ValueError:
            log.error("artifact escaped workdir, dropped: %s", p)
            continue
        arts.append(
            {
                "path": p,
                "rel": rel.as_posix(),
                "name": a.get("name") or p.name,
                "kind": a.get("kind") or guess_kind(p),
                "size": p.stat().st_size if p.exists() else 0,
            }
        )
    return arts, payload


def guess_kind(p: Path) -> str:
    return {
        ".md": "markdown", ".html": "html", ".htm": "html", ".json": "json",
        ".png": "image", ".jpg": "image", ".jpeg": "image", ".svg": "image",
        ".webp": "image", ".mp4": "video", ".mov": "video", ".mp3": "audio", ".wav": "audio",
    }.get(p.suffix.lower(), "file")


async def run_script(
    script: Path,
    params: dict | None = None,
    workdir: Path | None = None,
    project: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    skill_id: str = "",
) -> ScriptResult:
    """执行技能脚本。**永不抛异常**：失败以 ``returncode`` + ``stderr`` 摘要表达。"""
    workdir = Path(workdir) if workdir is not None else project_workdir(project or "default")
    workdir.mkdir(parents=True, exist_ok=True)
    out_dir = script_out_dir(project or workdir.name, skill_id) if skill_id else workdir
    timeout = min(max(int(timeout or DEFAULT_TIMEOUT), 1), LONG_TIMEOUT)
    python = sys.executable or "python3"
    env = {
        **os.environ,
        "ATELIER_OUT": str(out_dir),
        "ATELIER_PROJECT": project or workdir.name,
        "ATELIER_SKILL_ID": skill_id,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    argv = [python, str(script), "--params", json.dumps(params or {}, ensure_ascii=False),
            "--out", str(out_dir), "--project", project or workdir.name]
    log.info("skill script exec: %s (cwd=%s, out=%s, timeout=%ds)", script, workdir, out_dir, timeout)
    started = asyncio.get_running_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(workdir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        shell=False,  # 铁律：不经 shell
    )
    timed_out = False
    err_text = ""
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        err_text = (err_b or b"").decode("utf-8", "replace")
    except (TimeoutError, asyncio.TimeoutError):
        timed_out = True
        log.error("skill script timeout after %ss, killing: %s", timeout, script)
        proc.kill()
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), 10)
        except (TimeoutError, asyncio.TimeoutError):  # pragma: no cover
            out_b, err_b = b"", b""
        err_text = ((err_b or b"").decode("utf-8", "replace")
                    + f"\n[atelier] 超时 {timeout}s，已强制终止进程（pid 回收可能滞后）")
    duration = asyncio.get_running_loop().time() - started
    stdout = (out_b or b"").decode("utf-8", "replace")
    stderr = _tail(err_text, STDERR_LIMIT)
    if not timed_out and proc.returncode not in (0, None):
        log.error("skill script failed rc=%s: %s", proc.returncode, stderr[-500:])
    elif timed_out:
        log.error("skill script timed out: %s", script)
    arts, payload = parse_artifacts(stdout, workdir)
    return ScriptResult(
        returncode=proc.returncode,
        stdout=_tail(stdout, STDOUT_LIMIT),
        stderr=stderr,
        timed_out=timed_out,
        duration=duration,
        artifacts=arts,
        payload=payload,
    )
