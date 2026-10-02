"""SPEC-05 · 内容库域测试。

覆盖 SPEC-05 §7 的必测清单，重点是三条最容易出安全事故的线：

1. **Range**：206 / 200 / 416，以及大文件真流式
2. **路径安全**：``..`` 穿越与 symlink 逃逸都拦
3. **删除保护**：系统文件 403、删除必须带一次性确认口令、文案含「及其全部内容」

另外守住一条跨层契约：HTML 预览只能进 sandbox iframe（后端测试读前端源码断言，
前端另有 vitest 真实 DOM 断言）。

⚠️ 所有写操作必须带 ``Content-Type: application/json``：地基的跨站写中间件
（SPEC-01 §8）会把无 Content-Type 的 DELETE 判成跨站写并 403。前端同理。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atelier.server import paths
from atelier.server.config import reload_settings
from atelier.server.core import db
from atelier.server.main import create_app
from atelier.server.paths import index_path, material_dir, product_dir, project_dir

JSON = {"Content-Type": "application/json"}
REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def client(atelier_root: Path) -> Iterator[TestClient]:
    app = create_app(settings=reload_settings())
    with TestClient(app) as c:
        yield c


def _png(w: int = 320, h: int = 400) -> bytes:
    """造一张**大于 1KB** 的真 PNG（噪声图，避免压缩成小文件，Range 测试才有意义）。"""
    import io
    import random

    from PIL import Image

    rnd = random.Random(20260917)
    buf = io.BytesIO()
    img = Image.frombytes("RGB", (w, h), bytes(rnd.randrange(256) for _ in range(w * h * 3)))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def demo(atelier_root: Path) -> dict[str, str]:
    """一个真实可浏览的项目：成品 3 项 + 素材 1 项 + 会话日志 + 索引文件。"""
    paths.new_project("demo")
    paths.new_project("empty")
    p = product_dir("demo")
    (p / "xhs-card").mkdir(parents=True, exist_ok=True)
    (p / "card-01.png").write_bytes(_png())
    (p / "xhs-card" / "card-02.png").write_bytes(_png(240, 300))
    (p / "post.html").write_text("<h1>hi</h1>", encoding="utf-8")
    m = material_dir("demo")
    (m / "voice.mp3").write_bytes(b"ID3\x00\x00\x00\x00" + b"\x00" * 64)
    s = project_dir("demo") / ".session"
    (s / "turn-1.jsonl").write_text('{"turn": 1}\n', encoding="utf-8")
    (p / "note.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    return {
        "card": "demo/成品/card-01.png",
        "nested": "demo/成品/xhs-card/card-02.png",
        "html": "demo/成品/post.html",
        "md": "demo/成品/note.md",
        "audio": "demo/素材/voice.mp3",
        "session": "demo/.session/turn-1.jsonl",
    }


# --------------------------------------------------------------------------- 项目


class TestProjects:
    def test_projects_listed_with_zone_counts(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/projects")
        assert r.status_code == 200
        data = r.json()
        names = [p["name"] for p in data["projects"]]
        assert {"demo", "empty"} <= set(names)
        demo_row = next(p for p in data["projects"] if p["name"] == "demo")
        assert demo_row["product_count"] == 4
        assert demo_row["material_count"] == 1
        assert demo_row["system_count"] == 1
        assert demo_row["total_bytes"] > 0
        assert demo_row["file_count"] == 7  # 成品 4 + 素材 1 + 会话 1 + .index.json 1

    def test_create_project_creates_zones_and_index(self, client: TestClient, atelier_root: Path) -> None:
        r = client.post("/api/library/projects", json={"name": "lunch-2026"}, headers=JSON)
        assert r.status_code == 201
        assert r.json()["created"] is True
        for sub in ("成品", "素材", ".session"):
            assert (paths.OUTPUTS / "lunch-2026" / sub).is_dir()
        assert index_path("lunch-2026").is_file()

    def test_create_project_rejects_bad_name(self, client: TestClient) -> None:
        r = client.post("/api/library/projects", json={"name": "../evil"}, headers=JSON)
        assert r.status_code == 422
        assert r.json()["error"]["code"] in ("ValidationError",)


# --------------------------------------------------------------------------- 浏览


class TestBrowse:
    def test_tree_lists_products_and_materials(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/tree", params={"project": "demo", "zone": "成品"})
        assert r.status_code == 200
        data = r.json()
        assert {d["name"] for d in data["dirs"]} == {"xhs-card"}
        assert {f["name"] for f in data["files"]} == {"card-01.png", "note.md", "post.html"}
        crumbs = [c["label"] for c in data["breadcrumb"]]
        assert crumbs == ["demo", "成品"]

    def test_tree_breadcrumb_drills_down(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/tree", params={"project": "demo", "zone": "成品", "sub": "xhs-card"})
        data = r.json()
        assert [c["label"] for c in data["breadcrumb"]] == ["demo", "成品", "xhs-card"]
        assert [f["name"] for f in data["files"]] == ["card-02.png"]
        assert data["sub"] == "xhs-card"

    def test_files_filter_by_kind(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/files", params={"project": "demo", "kind": "image"})
        assert r.status_code == 200
        assert {f["name"] for f in r.json()["files"]} == {"card-01.png", "card-02.png"}

    def test_files_search_by_name(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/files", params={"project": "demo", "q": "card-01"})
        assert [f["name"] for f in r.json()["files"]] == ["card-01.png"]
        r2 = client.get("/api/library/files", params={"project": "demo", "q": "不存在的名字"})
        assert r2.json()["files"] == []

    def test_files_reject_unknown_kind(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/files", params={"project": "demo", "kind": "字体"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "ValidationError"

    def test_meta_reports_size_and_dimensions(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/meta", params={"path": demo["card"]})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "card-01.png"
        assert data["width"] == 320 and data["height"] == 400
        assert data["mime"] == "image/png"
        assert data["size"] > 0
        assert data["stream_url"].startswith("/api/library/stream?path=")
        assert data["is_system"] is False

    def test_preview_returns_text_for_markdown(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/preview", params={"path": demo["md"]})
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "markdown"
        assert "# 标题" in data["content"]
        assert data["truncated"] is False

    def test_preview_rejects_binary(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/preview", params={"path": demo["card"]})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "ValidationError"


# --------------------------------------------------------------------------- ★ Range


class TestRange:
    def test_range_request_returns_206(self, client: TestClient, demo: dict[str, str]) -> None:
        full = client.get("/api/library/stream", params={"path": demo["card"]})
        size = int(full.headers["content-length"])
        assert size > 1024 or size == len(full.content)

        r = client.get(
            "/api/library/stream",
            params={"path": demo["card"]},
            headers={"Range": "bytes=0-1023"},
        )
        assert r.status_code == 206
        assert r.headers["content-range"] == f"bytes 0-1023/{size}"
        assert r.headers["accept-ranges"] == "bytes"
        assert len(r.content) == 1024
        assert r.content == full.content[:1024]

    def test_range_accepts_outputs_prefix(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get(
            "/api/library/stream",
            params={"path": f"outputs/{demo['card']}"},
            headers={"Range": "bytes=0-9"},
        )
        assert r.status_code == 206
        assert r.headers["content-range"].startswith("bytes 0-9/")

    def test_no_range_returns_200_with_accept_ranges(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get("/api/library/stream", params={"path": demo["card"]})
        assert r.status_code == 200
        assert r.headers["accept-ranges"] == "bytes"
        assert "content-range" not in r.headers

    def test_open_ended_and_suffix_ranges(self, client: TestClient, demo: dict[str, str]) -> None:
        size = len(client.get("/api/library/stream", params={"path": demo["card"]}).content)
        tail = client.get(
            "/api/library/stream", params={"path": demo["card"]}, headers={"Range": "bytes=-16"}
        )
        assert tail.status_code == 206
        assert tail.headers["content-range"] == f"bytes {size - 16}-{size - 1}/{size}"
        open_ended = client.get(
            "/api/library/stream", params={"path": demo["card"]}, headers={"Range": f"bytes={size - 5}-"}
        )
        assert open_ended.status_code == 206
        assert len(open_ended.content) == 5

    @pytest.mark.parametrize(
        "bad",
        ["bytes=abc", "items=0-10", "bytes=999999-1000000", "bytes=10-5", "bytes=-0", "bytes="],
    )
    def test_invalid_range_returns_416(self, client: TestClient, demo: dict[str, str], bad: str) -> None:
        r = client.get("/api/library/stream", params={"path": demo["card"]}, headers={"Range": bad})
        assert r.status_code == 416, bad
        body = r.json()
        assert body["error"]["code"] == "RangeNotSatisfiable"
        assert r.headers["accept-ranges"] == "bytes"

    def test_if_range_mismatch_falls_back_to_200(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.get(
            "/api/library/stream",
            params={"path": demo["card"]},
            headers={"Range": "bytes=0-10", "If-Range": '"deadbeef"'},
        )
        assert r.status_code == 200
        assert r.headers["accept-ranges"] == "bytes"

    def test_large_file_streams_range_without_loading_all(
        self, client: TestClient, atelier_root: Path
    ) -> None:
        """>50MB 的文件必须真流式：只读 1KB，服务端不整读。"""
        paths.new_project("big")
        big = product_dir("big") / "huge.mp4"
        with big.open("wb") as f:
            f.write(b"\x00" * 4096)
            f.truncate(60 * 1024 * 1024)  # 稀疏文件：占逻辑大小，不占磁盘
        try:
            r = client.get(
                "/api/library/stream",
                params={"path": "big/成品/huge.mp4"},
                headers={"Range": "bytes=0-1023"},
            )
            assert r.status_code == 206
            assert r.headers["content-range"] == "bytes 0-1023/62914560"
            assert r.headers["content-length"] == "1024"
            assert len(r.content) == 1024
        finally:
            big.unlink(missing_ok=True)

    def test_iter_file_bytes_never_reads_whole_file(self, atelier_root: Path) -> None:
        from atelier.server.library import service

        paths.new_project("chunky")
        p = product_dir("chunky") / "a.bin"
        p.write_bytes(b"x" * 10_000)
        chunks = list(service.iter_file_bytes(p, 0, 10_000, chunk_size=1024))
        assert sum(len(c) for c in chunks) == 10_000
        assert max(len(c) for c in chunks) <= 1024
        assert list(service.iter_file_bytes(p, 4, 3)) == [b"xxx"]


# --------------------------------------------------------------------------- 路径安全


class TestPathSafety:
    @pytest.mark.parametrize("evil", ["../../etc/passwd", "demo/../../etc/passwd", "/etc/passwd"])
    def test_path_escape_rejected(self, client: TestClient, evil: str) -> None:
        for endpoint in ("stream", "meta", "preview"):
            r = client.get(f"/api/library/{endpoint}", params={"path": evil})
            assert r.status_code == 400, endpoint
            body = r.json()
            assert body["error"]["code"] == "PathEscapeError"
            assert body["error"]["hint"]

    def test_symlink_escape_rejected(self, client: TestClient, demo: dict[str, str]) -> None:
        outside = project_dir("demo").parent.parent / "escape-target"
        outside.mkdir(exist_ok=True)
        secret = outside / "passwd"
        secret.write_text("root:x:0:0", encoding="utf-8")
        link = paths.OUTPUTS / "demo" / "link-out"
        link.symlink_to(outside)
        try:
            r = client.get("/api/library/stream", params={"path": "demo/link-out/passwd"})
            assert r.status_code == 400
            body = r.json()
            assert body["error"]["code"] == "PathEscapeError"
            assert body["error"]["detail"].get("reason") == "symlink_escape"
        finally:
            link.unlink(missing_ok=True)
            secret.unlink(missing_ok=True)
            outside.rmdir()


# --------------------------------------------------------------------------- 删除保护


class TestDeleteProtection:
    def test_delete_requires_confirm_token(self, client: TestClient, demo: dict[str, str]) -> None:
        target = paths.resolve_inside(paths.OUTPUTS, demo["card"])

        missing = client.delete("/api/library/file", params={"path": demo["card"]}, headers=JSON)
        assert missing.status_code == 422
        assert missing.json()["error"]["detail"]["reason"] == "missing_confirm"
        assert target.exists(), "没口令不许删"

        wrong = client.delete(
            "/api/library/file", params={"path": demo["card"], "confirm": "瞎写的"}, headers=JSON
        )
        assert wrong.status_code == 422
        assert target.exists(), "错口令不许删"

        tok = client.post("/api/library/confirm-token", json={"path": demo["card"]}, headers=JSON).json()
        assert "你正在删除 `card-01.png` 及其全部内容" == tok["warning"]
        assert tok["expires_in"] > 0

        ok = client.delete(
            "/api/library/file", params={"path": demo["card"], "confirm": tok["token"]}, headers=JSON
        )
        assert ok.status_code == 200
        assert not target.exists()
        assert "及其全部内容" in ok.json()["statement"]

    def test_confirm_token_is_single_use(self, client: TestClient, demo: dict[str, str]) -> None:
        token = client.post("/api/library/confirm-token", json={"path": demo["md"]}, headers=JSON).json()["token"]
        first = client.delete(
            "/api/library/file", params={"path": demo["md"], "confirm": token}, headers=JSON
        )
        assert first.status_code == 200
        again = client.delete(
            "/api/library/file", params={"path": demo["md"], "confirm": token}, headers=JSON
        )
        assert again.status_code in (404, 422)

    def test_token_is_bound_to_its_target(self, client: TestClient, demo: dict[str, str]) -> None:
        token = client.post("/api/library/confirm-token", json={"path": demo["md"]}, headers=JSON).json()["token"]
        r = client.delete(
            "/api/library/file", params={"path": demo["html"], "confirm": token}, headers=JSON
        )
        assert r.status_code == 422
        assert r.json()["error"]["detail"]["reason"] == "target_mismatch"
        assert paths.resolve_inside(paths.OUTPUTS, demo["html"]).exists()

    def test_delete_system_file_403(self, client: TestClient, demo: dict[str, str]) -> None:
        # 连确认口令都拿不到
        tok = client.post("/api/library/confirm-token", json={"path": demo["session"]}, headers=JSON)
        assert tok.status_code == 403
        assert tok.json()["error"]["code"] == "SystemFileProtected"
        assert "session" in tok.json()["error"]["message"]

        # 硬删也拦得住
        r = client.delete("/api/library/file", params={"path": demo["session"]}, headers=JSON)
        assert r.status_code == 403
        body = r.json()
        assert body["error"]["code"] == "SystemFileProtected"
        assert body["error"]["hint"]
        assert paths.resolve_inside(paths.OUTPUTS, demo["session"]).exists()

    def test_index_file_is_protected_too(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.delete("/api/library/file", params={"path": "demo/.index.json"}, headers=JSON)
        assert r.status_code == 403
        assert index_path("demo").is_file()

    def test_delete_project_declares_all_content(self, client: TestClient, demo: dict[str, str]) -> None:
        tok = client.post("/api/library/confirm-token", json={"project": "demo"}, headers=JSON).json()
        assert "及其全部内容" in tok["warning"]
        assert "demo" in tok["warning"]
        assert tok["file_count"] >= 5
        assert tok["total_size_human"]

        no_token = client.delete("/api/library/project", params={"project": "demo"}, headers=JSON)
        assert no_token.status_code == 422
        assert project_dir("demo").is_dir()

        r = client.delete(
            "/api/library/project", params={"project": "demo", "confirm": tok["token"]}, headers=JSON
        )
        assert r.status_code == 200
        data = r.json()
        assert "及其全部内容" in data["statement"]
        assert data["file_count"] >= 5
        assert not project_dir("demo").exists()

    def test_delete_escape_path_is_400(self, client: TestClient) -> None:
        r = client.delete("/api/library/file", params={"path": "../../etc/passwd"}, headers=JSON)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "PathEscapeError"

    def test_unlock_system_is_not_enabled_in_m1(self, client: TestClient, demo: dict[str, str]) -> None:
        r = client.post(
            "/api/library/unlock-system", json={"path": demo["session"], "confirm": "解锁系统文件"}, headers=JSON
        )
        assert r.status_code == 200
        data = r.json()
        assert data["unlocked"] is False and data["enabled"] is False
        assert "系统保护" in data["notice"]


# --------------------------------------------------------------------------- 孤儿索引


class TestOrphanIndex:
    def test_orphan_index_cleaned_on_scan(
        self, client: TestClient, demo: dict[str, str], caplog: pytest.LogCaptureFixture
    ) -> None:
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO artifacts (id, project, zone, rel_path, kind, size, mime, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("a-gone", "demo", "成品", "demo/成品/被手动删了.png", "image", 1, "image/png", db.utcnow()),
        )
        conn.execute(
            "INSERT INTO artifacts (id, project, zone, rel_path, kind, size, mime, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("a-alive", "demo", "成品", demo["card"], "image", 1, "image/png", db.utcnow()),
        )
        conn.commit()

        with caplog.at_level("WARNING", logger="atelier.library"):
            r = client.get("/api/library/files", params={"project": "demo"})
        assert r.status_code == 200
        assert r.json()["orphan_removed"] == 1
        # 列表里不能出现磁盘上已不存在的文件
        assert "被手动删了.png" not in {f["name"] for f in r.json()["files"]}

        left = conn.execute("SELECT id FROM artifacts WHERE project='demo' ORDER BY id").fetchall()
        assert [row[0] for row in left] == ["a-alive"], "孤儿行应被剔除，真实行必须留着"
        warned = [m.getMessage() for m in caplog.records if "orphan artifact removed" in m.getMessage()]
        assert warned, "必须留一条日志，不许静默"

    def test_deleting_file_clears_its_index_row(
        self, client: TestClient, demo: dict[str, str]
    ) -> None:
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO artifacts (id, project, zone, rel_path, kind, size, mime, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("a-md", "demo", "成品", demo["md"], "file", 1, None, db.utcnow()),
        )
        conn.commit()
        token = client.post("/api/library/confirm-token", json={"path": demo["md"]}, headers=JSON).json()["token"]
        r = client.delete(
            "/api/library/file", params={"path": demo["md"], "confirm": token}, headers=JSON
        )
        assert r.status_code == 200
        assert r.json()["index_rows_removed"] == 1
        assert conn.execute("SELECT 1 FROM artifacts WHERE id='a-md'").fetchone() is None

    def test_orphan_scan_survives_missing_table(
        self, atelier_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """artifacts 表还没建时扫描不能 500，只记一条警告。"""
        from atelier.server.library import service

        def _boom() -> sqlite3.Connection:
            raise sqlite3.OperationalError("no such table: artifacts")

        monkeypatch.setattr(service.db, "get_conn", _boom)
        assert service.clean_orphan_index("demo") == []


# --------------------------------------------------------------------------- 预览安全（跨层）


def test_html_preview_sandboxed(demo: dict[str, str]) -> None:
    """HTML 只能进 sandbox iframe：**不给** ``allow-same-origin``。

    后端侧：HTML 走 ``/preview`` 拿文本或 ``/stream`` 拿原文件，**不返回任何内联页面**。
    前端侧：``PreviewPane`` 必须用 ``<iframe sandbox>`` 且不带 ``allow-same-origin``。
    """
    pane = REPO_ROOT / "web" / "src" / "features" / "library" / "PreviewPane.tsx"
    src = pane.read_text("utf-8")
    assert "sandbox" in src, "HTML 预览必须放进 sandbox iframe"
    assert "allow-same-origin" not in src, "sandbox 不能给 allow-same-origin（否则可读宿主页面）"
    assert "<iframe" in src


def test_router_mounted_without_prefix_error() -> None:
    """域路由不写 prefix，由 main.py 统一加 /api（避免 /api/api）。"""
    from atelier.server.api import library as api_library

    assert api_library.router.prefix == ""
    paths_ = {r.path for r in api_library.router.routes}
    assert "/library/stream" in paths_
    # SPEC-05 §3 列 11 行，其中 /library/projects 占 GET+POST 两行 → 10 个路径
    assert len(api_library.router.routes) == 11, f"SPEC-05 §3 要求 11 个端点，实际 {sorted(paths_)}"
    assert len(paths_) == 10


def test_all_endpoints_declared_in_openapi(client: TestClient, demo: dict[str, str]) -> None:
    spec = client.get("/api/openapi.json").json()
    got = {p for p in spec["paths"] if p.startswith("/api/library")}
    assert got == {
        "/api/library/projects",
        "/api/library/tree",
        "/api/library/files",
        "/api/library/stream",
        "/api/library/meta",
        "/api/library/preview",
        "/api/library/confirm-token",
        "/api/library/file",
        "/api/library/project",
        "/api/library/unlock-system",
    }
    # 产物路径 chip（SPEC-05 §5）依赖相对路径形状，别改坏
    item = client.get("/api/library/files", params={"project": "demo"}).json()["files"]
    json.dumps(item)  # 可 JSON 化
