"""CLI 测试（SPEC-01 §11）。

doctor 的验收标准是「**17 项，每项给具体值，不许只说通过**」，所以这里对
「数量」「key 唯一」「value 非空」「状态合法」逐条断言，而不是只看它能跑完。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.cli import main as cli
from atelier.launcher import is_port_free, prepare


class TestDoctor:
    def test_exactly_seventeen_checks(self) -> None:
        assert cli.DOCTOR_CHECK_COUNT == 17
        assert len(cli.CHECKS) == 17

    def test_every_check_has_a_value(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        checks = cli.check_all()
        assert len(checks) == 17
        for c in checks:
            assert c.value.strip(), f"{c.key} 只给了状态没给具体值（PRD 原则四）"
            assert c.status in (cli.OK, cli.WARN, cli.FAIL)

    def test_check_keys_unique(self) -> None:
        keys = [key for key, _, _ in cli.CHECKS]
        assert len(set(keys)) == len(keys)

    def test_每项都覆盖了约定的检查维度(self) -> None:
        """SPEC-00 §3 要求的 17 项，逐项对得上。"""
        assert {key for key, _, _ in cli.CHECKS} == {
            "python", "node", "ffmpeg", "chromium", "disk", "output_dirs",
            "channels", "tts", "cors", "csrf", "secret_scan", "credentials",
            "session_store", "db", "git", "port", "browser_session",
        }

    def test_secret_scan_self_probe_detects_fake_key(self, atelier_root: Path) -> None:
        c = cli.check_secret_scan()
        assert c.status == cli.OK
        assert "假密钥" in c.value
        assert "干净文本" in c.value

    def test_python_check_reports_version(self, atelier_root: Path) -> None:
        import sys

        c = cli.check_python()
        assert c.status == cli.OK
        assert sys.version.split()[0] in c.value

    def test_db_check_reports_nine_tables(self, atelier_root: Path) -> None:
        c = cli.check_db()
        assert c.status == cli.OK
        assert "9/9" in c.value

    def test_cors_check_fails_when_widened(self, atelier_root: Path) -> None:
        from atelier.server.config import reload_settings

        reload_settings(cors_origins=("https://evil.example.com",))
        try:
            c = cli.check_cors()
            assert c.status == cli.FAIL
            assert "evil.example.com" in c.value
        finally:
            reload_settings()

    def test_csrf_check_fails_when_disabled(self, atelier_root: Path) -> None:
        from atelier.server.config import reload_settings

        reload_settings(disable_csrf=True)
        try:
            assert cli.check_csrf().status == cli.FAIL
        finally:
            reload_settings()

    def test_output_dirs_created_by_doctor(self, atelier_root: Path) -> None:
        """doctor 要报「目录能不能用」，所以自己先幂等建出来。"""
        assert not (atelier_root / "outputs").exists()
        cli.check_all()
        for d in ("outputs", "profiles", "var", "var/sessions"):
            assert (atelier_root / d).is_dir()

    def test_report_output_has_17_lines_with_values(
        self, atelier_root: Path, capsys: pytest.CaptureFixture
    ) -> None:
        cli.run_doctor()
        out = capsys.readouterr().out
        assert "17 项" in out
        for i in range(1, 18):
            assert f"{i:2d}/17" in out, f"第 {i} 项没输出"
        assert "[OK   ]" in out or "[WARN ]" in out or "[FAIL ]" in out

    def test_json_output_shape(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        cli.run_doctor(as_json=True)
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 17
        assert len(data["checks"]) == 17
        assert data["ok"] + data["warn"] + data["fail"] == 17
        assert all(c["value"] for c in data["checks"])
        assert all({"key", "label", "status", "value"} <= set(c) for c in data["checks"])

    def test_exit_code_reflects_failures(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        rc = cli.run_doctor()
        checks = cli.check_all()
        expected = 1 if any(c.status == cli.FAIL for c in checks) else 0
        assert rc == expected

    def test_broken_check_becomes_fail_not_crash(self, atelier_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> cli.Check:
            raise RuntimeError("检查自身炸了")

        monkeypatch.setattr(cli, "CHECKS", (("boom", "会炸的检查", boom),))
        checks = cli.check_all()
        assert len(checks) == 1
        assert checks[0].status == cli.FAIL
        assert "RuntimeError" in checks[0].value


class TestParser:
    @pytest.mark.parametrize("cmd", ["web", "chat", "skill", "doctor", "ping"])
    def test_five_subcommands_exist(self, cmd: str) -> None:
        args = cli.build_parser().parse_args([cmd] if cmd != "skill" else ["skill", "x"])
        assert args.command == cmd

    def test_web_defaults_to_localhost(self) -> None:
        args = cli.build_parser().parse_args(["web"])
        assert args.host == "127.0.0.1", "SPEC-01 §9：只监听本地"
        assert args.port == 8000
        assert args.reload is False

    def test_doctor_json_flag(self) -> None:
        assert cli.build_parser().parse_args(["doctor", "--json"]).json is True

    def test_chat_prompt_optional(self) -> None:
        assert cli.build_parser().parse_args(["chat"]).prompt == ""

    def test_version_flag(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as ei:
            cli.build_parser().parse_args(["--version"])
        assert ei.value.code == 0
        assert "atelier" in capsys.readouterr().out

    def test_missing_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args([])


class TestPing:
    def test_reports_unreachable_without_server(
        self, atelier_root: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 指向一个肯定没人监听的端口
        from atelier.server.config import reload_settings

        monkeypatch.setenv("ATELIER_PORT", "9")
        args = cli.build_parser().parse_args(["ping", "--json"])
        args = type(args)(**vars(args))
        reload_settings()
        rc = cli.cmd_ping(args)
        out = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert out["reachable"] is False
        assert out["error"]

    def test_json_reports_reachable(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        """起一个真服务再 ping（127.0.0.1，随手起的，不占默认端口）。"""
        import socket
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, HTTPServer

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        payload = json.dumps({"version": "9.9.9", "config": {
            "harness_name": "mock", "mock": True, "cors_origins": ["http://localhost:5173"],
            "csrf_enabled": True,
        }}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a: object) -> None:
                pass

        server = HTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            from atelier.server.config import reload_settings

            reload_settings(port=port)
            args = cli.build_parser().parse_args(["ping", "--json"])
            rc = cli.cmd_ping(args)
            out = json.loads(capsys.readouterr().out)
            assert rc == 0
            assert out["reachable"] is True
            assert out["server"]["version"] == "9.9.9"
        finally:
            server.shutdown()
            server.server_close()
            time.sleep(0.05)


class TestSkillCommand:
    def test_unknown_skill_lists_available(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        (atelier_root / "atelier" / "skills" / "xhs-card").mkdir(parents=True)
        rc = cli.cmd_skill(cli.build_parser().parse_args(["skill", "not-there"]))
        out = capsys.readouterr().out
        assert rc == 1
        assert "没有技能" in out
        assert "xhs-card" in out, "要告诉用户有哪些可选"

    def test_existing_skill_reports_not_wired(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        (atelier_root / "atelier" / "skills" / "xhs-card").mkdir(parents=True)
        rc = cli.cmd_skill(cli.build_parser().parse_args(["skill", "xhs-card"]))
        out = capsys.readouterr().out
        assert rc == 0
        assert "xhs-card" in out
        assert "W1-B" in out

    def test_empty_skills_dir(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        (atelier_root / "atelier" / "skills").mkdir(parents=True, exist_ok=True)
        assert cli.cmd_skill(cli.build_parser().parse_args(["skill", "x"])) == 1
        assert "为空" in capsys.readouterr().out


class TestLauncher:
    def test_prepare_creates_dirs_and_db(self, atelier_root: Path) -> None:
        from atelier.server.core import db

        prepare()
        assert (atelier_root / "outputs").is_dir()
        assert (atelier_root / "var" / "atelier.db").exists()
        assert len(db.table_names()) == 9

    def test_prepare_is_idempotent(self, atelier_root: Path) -> None:
        prepare()
        prepare()

    def test_port_check(self) -> None:
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            busy = s.getsockname()[1]
            assert is_port_free(busy) is False
        with socket.socket() as s2:
            s2.bind(("127.0.0.1", 0))
            free = s2.getsockname()[1]
        assert is_port_free(free) is True


class TestMain:
    def test_main_dispatches_doctor(self, atelier_root: Path, capsys: pytest.CaptureFixture) -> None:
        rc = cli.main(["doctor", "--json"])
        assert rc in (0, 1)
        assert json.loads(capsys.readouterr().out)["total"] == 17

    def test_main_help_exits_cleanly(self) -> None:
        with pytest.raises(SystemExit) as ei:
            cli.main(["--help"])
        assert ei.value.code == 0

    def test_keyboard_interrupt_returns_130(self, atelier_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(args: object) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(cli, "run_doctor", boom)
        assert cli.main(["doctor"]) == 130
