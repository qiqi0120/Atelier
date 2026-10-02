"""SPEC-01 §7 · SQLite schema 测试。

验收点：9 张表齐全、``foreign_keys`` 真的开着（不是默认关）、迁移幂等。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atelier.server import paths
from atelier.server.core import db

EXPECTED_TABLES = {
    "profiles", "memories", "sessions", "messages", "artifacts",
    "publish_drafts", "publish_records", "platform_creds", "settings",
    "skill_runs",
}


class TestSchema:
    def test_db_file_location(self, atelier_root: Path) -> None:
        db.init_db()
        assert db.db_path() == paths.VAR / "atelier.db"
        assert db.db_path().exists()

    def test_all_domain_tables_created(self, atelier_root: Path) -> None:
        conn = db.init_db()
        created = set(db.table_names(conn))
        assert EXPECTED_TABLES <= created, f"缺表：{EXPECTED_TABLES - created}"

    def test_exactly_domain_tables(self, atelier_root: Path) -> None:
        """除了 sqlite_ 内建表，不应该多出别的业务表。"""
        conn = db.init_db()
        assert set(db.table_names(conn)) == EXPECTED_TABLES

    def test_table_names_matches_ddl(self, atelier_root: Path) -> None:
        """TABLE_NAMES 与实际建表必须一致，否则 doctor 的「N/N 张表就绪」会说谎。"""
        conn = db.init_db()
        assert set(db.TABLE_NAMES) == set(db.table_names(conn))

    def test_schema_version_recorded(self, atelier_root: Path) -> None:
        conn = db.init_db()
        assert db.schema_version(conn) == db.SCHEMA_VERSION == 2

    def test_migration_is_idempotent(self, atelier_root: Path) -> None:
        conn = db.init_db()
        assert db.migrate(conn) == []  # 已经是最新 → 什么都不做
        assert db.migrate(conn) == []
        assert db.schema_version(conn) == db.SCHEMA_VERSION

    def test_reinit_after_new_root(self, atelier_root: Path) -> None:
        db.init_db()
        db.reset_conn()
        db.init_db()  # 第二次连到同一个库也不能炸
        assert EXPECTED_TABLES <= set(db.table_names(db.get_conn()))


class TestForeignKeys:
    def test_pragma_is_on(self, atelier_root: Path) -> None:
        conn = db.init_db()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_every_new_connection_enables_pragmas(self, atelier_root: Path) -> None:
        for conn in (db.connect(), db.connect()):
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            conn.close()

    def test_orphan_memory_rejected(self, atelier_root: Path) -> None:
        db.init_db()
        with pytest.raises(sqlite3.IntegrityError), db.db_session(commit=False) as c:
            c.execute(
                "INSERT INTO memories (id, profile_id, text, source, adopted, created_at)"
                " VALUES ('m1', 'nope', '孤儿记忆', '手动', 1, ?)",
                (db.utcnow(),),
            )

    def test_cascade_delete_profile_removes_memories(self, atelier_root: Path) -> None:
        conn = db.init_db()
        with db.db_session() as c:
            c.execute(
                "INSERT INTO profiles (id, name, platforms, created_at, updated_at)"
                " VALUES ('p1', '阿宇', '[\"xhs\"]', ?, ?)",
                (db.utcnow(), db.utcnow()),
            )
            c.execute(
                "INSERT INTO memories (id, profile_id, text, source, adopted, created_at)"
                " VALUES ('m1', 'p1', '喜欢具体数字', '归因', 1, ?)",
                (db.utcnow(),),
            )
        with db.db_session() as c:
            c.execute("DELETE FROM profiles WHERE id='p1'")
        left = conn.execute("SELECT COUNT(*) FROM memories WHERE profile_id='p1'").fetchone()[0]
        assert left == 0, "删画像必须级联删记忆（ON DELETE CASCADE）"

    def test_orphan_message_rejected(self, atelier_root: Path) -> None:
        db.init_db()
        with pytest.raises(sqlite3.IntegrityError), db.db_session(commit=False) as c:
            c.execute(
                "INSERT INTO messages (id, session_id, role, text, created_at)"
                " VALUES ('x1', 'nope', 'user', 'hi', ?)",
                (db.utcnow(),),
            )


class TestColumns:
    @pytest.mark.parametrize(
        ("table", "must_have"),
        [
            ("profiles", ("id", "name", "platforms", "general_mode", "created_at", "updated_at")),
            ("memories", ("id", "profile_id", "text", "source", "adopted", "created_at")),
            ("sessions", ("id", "title", "profile_id", "archived", "last_turn_id")),
            ("messages", ("id", "session_id", "role", "text", "turn_id", "attachments", "gate_report")),
            ("artifacts", ("id", "project", "zone", "rel_path", "kind", "size", "mime")),
            ("publish_drafts", ("id", "project", "title", "body", "topic_tags", "variants")),
            ("publish_records", ("id", "draft_id", "platform", "status", "error_code", "published_url")),
            ("platform_creds", ("id", "platform", "secret_ref", "state", "verified_at")),
            ("settings", ("k", "v")),
        ],
    )
    def test_expected_columns_present(self, atelier_root: Path, table: str, must_have: tuple[str, ...]) -> None:
        conn = db.init_db()
        cols = db.column_names(table, conn)
        assert set(must_have) <= set(cols), f"{table} 缺列：{set(must_have) - set(cols)}"

    def test_platform_creds_has_no_plaintext_secret(self, atelier_root: Path) -> None:
        """SPEC-01 §9：只存 secret_ref（指向 keychain/加密文件），没有明文列。"""
        conn = db.init_db()
        cols = set(db.column_names("platform_creds", conn))
        assert "secret_ref" in cols
        assert not (cols & {"secret", "password", "token", "cookie", "value"})


class TestSession:
    def test_db_session_commits(self, atelier_root: Path) -> None:
        conn = db.init_db()
        with db.db_session() as c:
            c.execute("INSERT INTO settings (k, v) VALUES ('theme', 'dark')")
        assert conn.execute("SELECT v FROM settings WHERE k='theme'").fetchone()[0] == "dark"

    def test_db_session_rolls_back(self, atelier_root: Path) -> None:
        conn = db.init_db()
        with pytest.raises(RuntimeError), db.db_session() as c:
            c.execute("INSERT INTO settings (k, v) VALUES ('bad', '1')")
            raise RuntimeError("boom")
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE k='bad'").fetchone()[0] == 0

    def test_json_helpers(self) -> None:
        assert db.loads(db.dumps({"a": [1, 2]})) == {"a": [1, 2]}
        assert db.loads(None, default={}) == {}
        assert db.loads("not json", default="fallback") == "fallback"

    def test_utcnow_is_iso8601(self) -> None:
        s = db.utcnow()
        assert s.endswith("+00:00")
        assert "T" in s
