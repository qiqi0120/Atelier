"""SPEC-01 §1 · paths 测试。

重点覆盖三件最容易出安全事故的事：
1. ``..`` 穿越
2. symlink 逃逸
3. 项目名校验（含中文 / 大写 / 分隔符 / 超长）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.server import paths
from atelier.server.errors import (
    NotFound,
    PathEscapeError,
    SystemFileProtected,
    ValidationError,
)


class TestRootLayout:
    def test_all_roots_live_under_root(self, atelier_root: Path) -> None:
        assert paths.ROOT == atelier_root.resolve()
        for p in (paths.OUTPUTS, paths.PROFILES, paths.VAR, paths.SKILLS, paths.VAR_DB, paths.SESSIONS):
            assert p.is_relative_to(paths.ROOT), f"{p} 跑出 ROOT 了"

    def test_ensure_dirs_is_idempotent(self, atelier_root: Path) -> None:
        paths.ensure_dirs()
        paths.ensure_dirs()  # 第二次不能炸
        for d in (paths.OUTPUTS, paths.PROFILES, paths.VAR, paths.SESSIONS):
            assert d.is_dir()

    def test_project_zones(self, atelier_root: Path) -> None:
        assert paths.product_dir("demo") == paths.OUTPUTS / "demo" / "成品"
        assert paths.material_dir("demo") == paths.OUTPUTS / "demo" / "素材"


class TestProjectName:
    @pytest.mark.parametrize("name", ["a", "demo", "lunch-2026", "my_project_01", "0", "a" * 64])
    def test_valid_names_accepted(self, atelier_root: Path, name: str) -> None:
        assert paths.validate_project_name(name) == name

    @pytest.mark.parametrize(
        "name",
        ["", "Demo", "demo/x", "demo\\x", "..", "../etc", "-demo", "_demo", "a" * 65, "咖啡", "a b", "a.b"],
    )
    def test_invalid_names_rejected(self, atelier_root: Path, name: str) -> None:
        with pytest.raises(ValidationError) as ei:
            paths.validate_project_name(name)
        assert ei.value.http == 422
        assert ei.value.detail["name"] == name
        assert ei.value.detail.get("reason")

    def test_invalid_name_blocks_path_use(self, atelier_root: Path) -> None:
        """非法项目名不能被用来拼路径（铁律的实际防线）。"""
        with pytest.raises(ValidationError):
            paths.project_dir("../etc")


class TestResolveInside:
    def test_normal_relative_ok(self, atelier_root: Path) -> None:
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        assert paths.resolve_inside(base, "成品/a.md") == base / "成品" / "a.md"

    def test_dot_prefix_is_ignored(self, atelier_root: Path) -> None:
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        assert paths.resolve_inside(base, "./成品/./a.md") == base / "成品" / "a.md"

    def test_rejects_dotdot_traversal(self, atelier_root: Path) -> None:
        """验收项：../../etc/passwd 必须抛 PathEscapeError。"""
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        with pytest.raises(PathEscapeError) as ei:
            paths.resolve_inside(base, "../../etc/passwd")
        assert ei.value.http == 400
        assert ei.value.code == "PathEscapeError"
        assert ei.value.detail["offending"] == ".."

    def test_rejects_windows_style_traversal(self, atelier_root: Path) -> None:
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        with pytest.raises(PathEscapeError):
            paths.resolve_inside(base, r"..\..\etc\passwd")

    def test_rejects_absolute_path(self, atelier_root: Path) -> None:
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        with pytest.raises(PathEscapeError) as ei:
            paths.resolve_inside(base, "/etc/passwd")
        assert "绝对路径" in ei.value.message

    @pytest.mark.parametrize("bad", ["C:\\Windows\\system32", "\\\\server\\share"])
    def test_rejects_windows_absolute(self, atelier_root: Path, bad: str) -> None:
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        with pytest.raises(PathEscapeError):
            paths.resolve_inside(base, bad)

    def test_rejects_symlink_escape(self, atelier_root: Path) -> None:
        """验收项：base 内指向外部的 symlink 不能被穿出去。"""
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        outside = atelier_root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("不该被读到", encoding="utf-8")
        (base / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(PathEscapeError) as ei:
            paths.resolve_inside(base, "link/secret.txt")
        assert ei.value.detail["reason"] == "symlink_escape"

    def test_symlink_inside_base_is_allowed(self, atelier_root: Path) -> None:
        """指向 base 内部的 symlink 应该放行（只挡逃逸，不挡一切链接）。"""
        base = paths.OUTPUTS / "demo"
        (base / "成品").mkdir(parents=True)
        (base / "成品" / "real.md").write_text("ok", encoding="utf-8")
        (base / "alias").symlink_to(base / "成品", target_is_directory=True)
        assert paths.resolve_inside(base, "alias/real.md") == (base / "成品" / "real.md").resolve()

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_rejects_empty(self, atelier_root: Path, bad: object) -> None:
        base = paths.OUTPUTS
        with pytest.raises(ValidationError):
            paths.resolve_inside(base, bad)  # type: ignore[arg-type]

    def test_base_itself_resolves(self, atelier_root: Path) -> None:
        base = paths.OUTPUTS / "demo"
        base.mkdir(parents=True)
        assert paths.resolve_inside(base, ".") == base.resolve()


class TestNewProject:
    def test_creates_zones_and_index(self, atelier_root: Path) -> None:
        d = paths.new_project("lunch")
        assert d == paths.OUTPUTS / "lunch"
        assert (d / "成品").is_dir() and (d / "素材").is_dir() and (d / ".session").is_dir()
        assert paths.index_path("lunch").exists()
        assert "lunch" in paths.list_projects()

    def test_idempotent_keeps_created_at(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        first = paths.index_path("lunch").read_text("utf-8")
        paths.new_project("lunch")
        assert paths.index_path("lunch").read_text("utf-8") == first

    def test_invalid_name_rejected(self, atelier_root: Path) -> None:
        with pytest.raises(ValidationError):
            paths.new_project("../evil")


class TestSystemPath:
    @pytest.mark.parametrize(
        "p",
        [
            "outputs/demo/.session/state.json",
            "outputs/demo/.index.json",
            "outputs/demo/.atelier/cache.db",
            ".atelier-anything",
            "outputs/demo/成品/.atelierx.md",
        ],
    )
    def test_system_paths_protected(self, p: str) -> None:
        assert paths.is_system_path(Path(p)) is True

    @pytest.mark.parametrize("p", ["outputs/demo/成品/a.md", "outputs/demo/素材/b.png", "var/sessions/x/y.jsonl"])
    def test_normal_paths_not_protected(self, p: str) -> None:
        assert paths.is_system_path(Path(p)) is False

    def test_assert_deletable_raises(self) -> None:
        with pytest.raises(SystemFileProtected) as ei:
            paths.assert_deletable(Path("outputs/demo/.session/a.json"))
        assert ei.value.http == 403

    def test_assert_deletable_passes(self) -> None:
        p = Path("outputs/demo/成品/a.md")
        assert paths.assert_deletable(p) == p


class TestRelToRoot:
    @pytest.mark.parametrize(
        ("rel", "expect"),
        [
            ("outputs/demo/成品/a.md", "outputs/demo/成品/a.md"),
            ("profiles/p1.md", "profiles/p1.md"),
            ("var/atelier.db", "var/atelier.db"),
        ],
    )
    def test_rel_to_root(self, atelier_root: Path, rel: str, expect: str) -> None:
        p = atelier_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        assert paths.rel_to_root(p) == expect

    def test_outside_root_returns_absolute(self, atelier_root: Path, in_tmp_cwd: Path) -> None:
        outside = in_tmp_cwd / "elsewhere.txt"
        outside.write_text("x", encoding="utf-8")
        assert paths.rel_to_root(outside) == outside.resolve().as_posix()


class TestSessionPaths:
    def test_turn_log_path(self, atelier_root: Path) -> None:
        assert paths.turn_log("s1", "t1") == paths.SESSIONS / "s1" / "t1.jsonl"

    @pytest.mark.parametrize("bad", ["../evil", "a/b", "", "x" * 200, "1 2"])
    def test_turn_log_rejects_bad_id(self, atelier_root: Path, bad: str) -> None:
        with pytest.raises(ValidationError):
            paths.turn_log("s1", bad)

    def test_turn_log_glob(self, atelier_root: Path) -> None:
        p = paths.turn_log("s9", "t9")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n", encoding="utf-8")
        assert p in paths.turn_log_paths("t9")


class TestRequireDir:
    def test_missing_raises_not_found(self, atelier_root: Path) -> None:
        with pytest.raises(NotFound) as ei:
            paths.require_dir(paths.OUTPUTS, "nope/missing.md")
        assert ei.value.http == 404

    def test_existing_ok(self, atelier_root: Path) -> None:
        paths.ensure_dirs()
        (paths.OUTPUTS / "a.md").write_text("x", encoding="utf-8")
        assert paths.require_dir(paths.OUTPUTS, "a.md").name == "a.md"
