"""SPEC-01 §7 · SQLite schema（只存元数据，不存产物）。

**只存元数据，不存产物。** 图片/视频/正文都在 ``outputs/<项目>/``（PRD 原则一），
``artifacts`` 表只是指向文件系统的索引。

约定（SPEC-01 §7）：
- 时间统一 ISO8601 UTC 字符串
- JSON 字段用 TEXT 存 JSON
- ``PRAGMA foreign_keys=ON``（SQLite 默认关闭，必须每条连接显式开）
- 迁移不引 Alembic：``PRAGMA user_version`` 记版本号，缺什么补什么

连接策略：按线程缓存（FastAPI 的 sync 端点跑在线程池里），写操作显式 commit。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths

__all__ = [
    "SCHEMA_VERSION",
    "TABLE_NAMES",
    "column_names",
    "db_session",
    "get_conn",
    "init_db",
    "migrate",
    "reset_conn",
    "schema_version",
    "table_names",
    "utcnow",
]

#: SPEC-01 §7 的表清单。skill_runs 为 M1 收尾时补的第 10 张表（见 _apply_v2）；
#: topics / topic_scores 为 M2-1 选题域补的第 11、12 张（见 _apply_v3，SPEC-08 §1）；
#: calendar_events 为 M2-2 日历域补的第 13 张（见 _apply_v4，SPEC-09 §1）；
#: subscriptions / feed_items / hot_entries / hot_digests / algorithm_notes
#: 为 M2-3b 发现域补的第 14~18 张（见 _apply_v6，SPEC-12 §1）。
TABLE_NAMES: tuple[str, ...] = (
    "profiles",
    "memories",
    "sessions",
    "messages",
    "artifacts",
    "publish_drafts",
    "publish_records",
    "platform_creds",
    "settings",
    "skill_runs",
    "topics",
    "topic_scores",
    "calendar_events",
    "subscriptions",
    "feed_items",
    "hot_entries",
    "hot_digests",
    "algorithm_notes",
)

SCHEMA_VERSION = 6

_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, platforms TEXT NOT NULL,  -- JSON
  identity TEXT, style TEXT, audience TEXT, platform_rules TEXT, preferences TEXT,
  general_mode INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  text TEXT NOT NULL, source TEXT, adopted INTEGER DEFAULT 1, created_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, title TEXT, profile_id TEXT, archived INTEGER DEFAULT 0,
  last_turn_id TEXT, created_at TEXT, updated_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL, text TEXT NOT NULL, turn_id TEXT, attachments TEXT,
  gate_report TEXT, created_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS artifacts (            -- 产物索引，指向文件系统
  id TEXT PRIMARY KEY, project TEXT NOT NULL, zone TEXT NOT NULL,  -- 成品|素材
  rel_path TEXT NOT NULL, kind TEXT, size INTEGER, mime TEXT,
  session_id TEXT, turn_id TEXT, created_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS publish_drafts (
  id TEXT PRIMARY KEY, project TEXT, title TEXT, body TEXT, topic_tags TEXT,
  variants TEXT, attachments TEXT, topic_id TEXT, scheduled_date TEXT,
  created_at TEXT, updated_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS publish_records (
  id TEXT PRIMARY KEY, draft_id TEXT, platform TEXT NOT NULL, status TEXT NOT NULL,
  title TEXT, error TEXT, error_code TEXT, published_url TEXT, created_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS platform_creds (       -- 凭证密文，绝不存明文
  id TEXT PRIMARY KEY, platform TEXT NOT NULL, account TEXT,
  secret_ref TEXT NOT NULL,        -- 指向 keychain / 加密文件
  state TEXT NOT NULL,             -- unknown|valid|expired
  verified_at TEXT, created_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);  -- 密钥掩码、自检结果快照""",
)

#: 声明式列清单，用于「缺什么补什么」的补列迁移（比解析 DDL 稳）
_EXPECTED: dict[str, tuple[str, ...]] = {
    "profiles": (
        "id", "name", "platforms", "identity", "style", "audience",
        "platform_rules", "preferences", "general_mode", "created_at", "updated_at",
    ),
    "memories": ("id", "profile_id", "text", "source", "adopted", "created_at"),
    "sessions": ("id", "title", "profile_id", "archived", "last_turn_id", "created_at", "updated_at"),
    "messages": ("id", "session_id", "role", "text", "turn_id", "attachments", "gate_report", "created_at"),
    "artifacts": (
        "id", "project", "zone", "rel_path", "kind", "size", "mime",
        "session_id", "turn_id", "created_at",
    ),
    "publish_drafts": (
        "id", "project", "title", "body", "topic_tags", "variants", "attachments",
        "topic_id", "scheduled_date", "created_at", "updated_at",
    ),
    "publish_records": (
        "id", "draft_id", "platform", "status", "title", "error", "error_code",
        "published_url", "created_at",
    ),
    "platform_creds": ("id", "platform", "account", "secret_ref", "state", "verified_at", "created_at"),
    "settings": ("k", "v"),
    "skill_runs": (
        "id", "skill_id", "project", "profile_id", "status", "params",
        "result_markdown", "artifacts", "gate_report", "cost_estimate", "cost_actual",
        "stdout", "stderr", "returncode", "error", "missing_keys", "duration",
        "created_at", "updated_at",
    ),
    "topics": (
        "id", "profile_id", "title", "angle", "source", "source_ref",
        "status", "decode", "due_date", "created_at", "updated_at",
    ),
    "topic_scores": (
        "id", "topic_id", "dims", "total", "verdict", "reason", "created_at",
    ),
    "calendar_events": (
        "id", "title", "date", "end_date", "kind", "note",
        "remind_days", "source", "created_at", "updated_at",
    ),
    "subscriptions": (
        "id", "name", "platform", "kind", "source", "url", "keywords",
        "notes", "enabled", "last_fetched_at", "created_at", "updated_at",
    ),
    "feed_items": (
        "id", "subscription_id", "title", "url", "summary",
        "published_at", "fetched_at", "dedup_key",
    ),
    "hot_entries": (
        "id", "title", "source", "platform", "url", "heat", "note",
        "entry_date", "status", "digest_id", "created_at", "updated_at",
    ),
    "hot_digests": (
        "id", "title", "window_start", "window_end", "markdown", "entry_ids", "created_at",
    ),
    "algorithm_notes": (
        "id", "platform", "noted_at", "change", "impact", "source", "created_at", "updated_at",
    ),
}

#: 补列时的列定义（SQLite 不允许裸 ADD COLUMN 带 PRIMARY KEY，这里只列可选补的普通列）
_COLUMN_DDL: dict[tuple[str, str], str] = {}


def _apply_v1(conn: sqlite3.Connection) -> None:
    for ddl in _DDL:
        conn.execute(ddl)
    # 索引：查询热点（会话列表 / 内容库按项目过滤 / 发布记录）
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_profile ON memories(profile_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_publish_records_draft ON publish_records(draft_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_creds_platform ON platform_creds(platform)")


def _apply_v2(conn: sqlite3.Connection) -> None:
    """v2 · 补 ``skill_runs``（M1 收尾）。

    技能运行记录此前只在 ``api/capability.py`` 的进程内字典里，重启即丢
    （M1 验收报告 §6 已知缺口）。这里补第 10 张表。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skill_runs (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  project TEXT, profile_id TEXT,
  status TEXT NOT NULL,
  params TEXT,
  result_markdown TEXT, artifacts TEXT, gate_report TEXT,
  cost_estimate TEXT,
  cost_actual REAL DEFAULT 0.0,
  stdout TEXT, stderr TEXT, returncode INTEGER,
  error TEXT, missing_keys TEXT,
  duration REAL DEFAULT 0.0,
  created_at TEXT, updated_at TEXT
)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_runs_skill ON skill_runs(skill_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_runs_project ON skill_runs(project, created_at)")


def _add_missing_columns(conn: sqlite3.Connection) -> list[str]:
    """给已存在的表补上缺失的普通列（ALTER TABLE ADD COLUMN 幂等补齐）。"""
    added: list[str] = []
    for table, cols in _EXPECTED.items():
        if not _table_exists(conn, table):
            continue
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col in cols:
            if col in have:
                continue
            ddl = _COLUMN_DDL.get((table, col), f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            conn.execute(ddl)
            added.append(f"{table}.{col}")
    return added


def _apply_v3(conn: sqlite3.Connection) -> None:
    """v3 · 补 ``topics`` / ``topic_scores``（M2-1 选题域，SPEC-08 §1）。

    选题池是 M2-1 矩阵输出与 M2-2 日历建议的公共落点（PLAN-M2 §2），
    表本体先于这两个消费方冻结。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS topics (
  id TEXT PRIMARY KEY,
  profile_id TEXT,
  title TEXT NOT NULL,
  angle TEXT,
  source TEXT NOT NULL,
  source_ref TEXT,
  status TEXT NOT NULL,
  decode TEXT,
  created_at TEXT, updated_at TEXT
)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS topic_scores (
  id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  dims TEXT NOT NULL,
  total INTEGER NOT NULL,
  verdict TEXT NOT NULL,
  reason TEXT,
  created_at TEXT
)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_profile ON topics(profile_id, status)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_topic_scores_topic ON topic_scores(topic_id, created_at)"
    )


def _apply_v4(conn: sqlite3.Connection) -> None:
    """v4 · 补 ``calendar_events``（M2-2 日历域，SPEC-09 §1）。

    全局事件表（不带画像，SPEC-09 §0 D2）；``topics.due_date`` 可空列由
    ``_add_missing_columns`` 依 ``_EXPECTED`` 自动补，不在这里写 ALTER。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS calendar_events (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  date TEXT NOT NULL,
  end_date TEXT,
  kind TEXT NOT NULL,
  note TEXT,
  remind_days INTEGER NOT NULL DEFAULT 3,
  source TEXT NOT NULL,
  created_at TEXT, updated_at TEXT
)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendar_events(date)")


def _apply_v5(conn: sqlite3.Connection) -> None:
    """v5 · ``publish_drafts`` 扩 ``topic_id`` / ``scheduled_date``（M2 收尾，SPEC-10 §1）。

    实际补列由 migrate 末尾的 ``_add_missing_columns`` 依 ``_EXPECTED`` 统一执行
    （同 v4 给 topics 补 due_date 的先例）；本步只作版本标记，保证老库
    ``user_version`` 前进可判。
    """


def _apply_v6(conn: sqlite3.Connection) -> None:
    """v6 · 发现域 5 张表（M2-3b，SPEC-12 §1）。

    ``subscriptions`` → ``feed_items`` 带 ON DELETE CASCADE（删订阅清其条目）；
    ``(subscription_id, dedup_key)`` 唯一索引是去重的代码事实（SPEC-12 §0 D4），
    抓取走 ``INSERT OR IGNORE``。``hot_digests`` 只追加不改。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT,
  keywords TEXT,
  notes TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_fetched_at TEXT,
  created_at TEXT, updated_at TEXT
)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS feed_items (
  id TEXT PRIMARY KEY,
  subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT,
  summary TEXT,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  dedup_key TEXT NOT NULL
)"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uidx_feed_dedup ON feed_items(subscription_id, dedup_key)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feed_sub ON feed_items(subscription_id, fetched_at)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hot_entries (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  platform TEXT,
  url TEXT,
  heat TEXT,
  note TEXT,
  entry_date TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  digest_id TEXT,
  created_at TEXT, updated_at TEXT
)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hot_status ON hot_entries(status, created_at)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hot_digests (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  markdown TEXT NOT NULL,
  entry_ids TEXT,
  created_at TEXT
)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS algorithm_notes (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  noted_at TEXT NOT NULL,
  change TEXT NOT NULL,
  impact TEXT,
  source TEXT,
  created_at TEXT, updated_at TEXT
)"""
    )


#: 版本号 → 迁移步骤。新增版本时只往这里加一项，不要动老步骤（SPEC-01 §7 幂等）。
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _apply_v1,
    2: _apply_v2,
    3: _apply_v3,
    4: _apply_v4,
    5: _apply_v5,
    6: _apply_v6,
}

_local = threading.local()
_INIT_LOCK = threading.Lock()


def utcnow() -> str:
    """ISO8601 UTC 字符串，全库统一时间格式（SPEC-01 §7）。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


def db_path() -> Path:
    """当前生效的库文件路径（跟着 ``paths.configure`` 走）。"""
    return paths.VAR_DB


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """开一条新连接：``foreign_keys=ON`` + ``Row`` 工厂 + WAL。"""
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:  # pragma: no cover - 某些文件系统不支持 WAL
        pass
    return conn


def get_conn() -> sqlite3.Connection:
    """线程内缓存的连接（``foreign_keys`` 只在连接建立时设置一次，所以必须缓存）。"""
    conn = getattr(_local, "conn", None)
    target = db_path()
    if conn is not None and getattr(_local, "path", None) == str(target):
        return conn
    if conn is not None:
        conn.close()
    conn = connect(target)
    _local.conn = conn
    _local.path = str(target)
    return conn


def reset_conn() -> None:
    """丢掉线程内缓存连接（测试切库 / 删库重建后必须调）。"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.path = None


@contextmanager
def db_session(commit: bool = True) -> Iterator[sqlite3.Connection]:
    """事务上下文。异常时回滚，不吞异常（PRD 原则四：不静默）。"""
    conn = get_conn()
    try:
        yield conn
        if commit:
            conn.commit()
    except Exception:
        if commit:
            conn.rollback()
        raise


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def schema_version(conn: sqlite3.Connection | None = None) -> int:
    c = conn or get_conn()
    return int(c.execute("PRAGMA user_version").fetchone()[0])


def table_names(conn: sqlite3.Connection | None = None) -> list[str]:
    c = conn or get_conn()
    rows = c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r[0] for r in rows if not str(r[0]).startswith("sqlite_")]


def column_names(table: str, conn: sqlite3.Connection | None = None) -> list[str]:
    c = conn or get_conn()
    return [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]


def migrate(conn: sqlite3.Connection | None = None) -> list[str]:
    """把库升到 ``SCHEMA_VERSION``，返回本次实际执行的步骤名（幂等）。"""
    own = conn is None
    c = conn or connect()
    applied: list[str] = []
    try:
        current = schema_version(c)
        for version in range(current + 1, SCHEMA_VERSION + 1):
            step = _MIGRATIONS.get(version)
            if step is None:  # pragma: no cover - 防御性
                raise RuntimeError(f"缺少迁移步骤 v{version}")
            with c:  # 每个版本一个事务
                step(c)
                c.execute(f"PRAGMA user_version={version}")
            applied.append(f"v{version}")
        added = _add_missing_columns(c)
        if added:
            c.commit()
            applied.extend(f"add_column:{a}" for a in added)
        return applied
    finally:
        if own:
            c.close()


def init_db() -> sqlite3.Connection:
    """启动时调用：确保目录 + 迁移。返回线程内连接。"""
    paths.ensure_dirs()
    with _INIT_LOCK:
        conn = get_conn()
        migrate(conn)
    return conn


# ---------------------------------------------------------------------------
# 小工具：JSON 字段读写
# ---------------------------------------------------------------------------


def dumps(value: Any) -> str:
    """JSON 字段落库（TEXT 存 JSON，SPEC-01 §7）。"""
    return json.dumps(value, ensure_ascii=False)


def loads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
