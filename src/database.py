"""Database access and SQL safety validation for the Text2SQL agent."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Missing dependency 'pymysql'. Install it (for example via uv) before using database.py."
    ) from exc


_BANNED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "replace",
    "alter",
    "drop",
    "truncate",
    "create",
    "grant",
    "revoke",
    "lock",
    "unlock",
    "rename",
    "call",
    "set",
    "use",
}
_AGGREGATE_ONLY_PATTERN = re.compile(
    r"^\s*select\s+(?:distinct\s+)?(?:count|sum|avg|min|max)\s*\(",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"\b[a-z_]+\b", re.IGNORECASE)


class SQLSafetyError(ValueError):
    """Raised when SQL violates the read-only safety policy."""


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    connect_timeout: int = 10
    read_timeout: int = 30
    write_timeout: int = 30


def load_db_config_from_env() -> DBConfig:
    """Load database connection settings from environment variables."""
    return DBConfig(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "query_staff_ro"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "employees"),
    )


def _strip_comments(sql: str) -> str:
    # Remove block comments first, then line comments.
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"#[^\n]*", " ", sql)
    return sql.strip()


def _contains_multiple_statements(sql: str) -> bool:
    trimmed = sql.strip()
    if not trimmed:
        return False
    if trimmed.endswith(";"):
        trimmed = trimmed[:-1].rstrip()
    return ";" in trimmed


def validate_sql(sql: str) -> str:
    """Validate SQL against the project's read-only safety rules."""
    normalized = _strip_comments(sql)
    if not normalized:
        raise SQLSafetyError("SQL is empty after comment stripping.")

    if _contains_multiple_statements(normalized):
        raise SQLSafetyError("Multiple SQL statements are not allowed.")

    if not normalized.lower().startswith("select"):
        raise SQLSafetyError("Only SELECT statements are allowed.")

    words = {word.lower() for word in _WORD_PATTERN.findall(normalized)}
    banned_used = sorted(_BANNED_KEYWORDS.intersection(words))
    if banned_used:
        raise SQLSafetyError(f"Disallowed SQL keyword(s): {', '.join(banned_used)}.")

    has_limit = " limit " in f" {normalized.lower()} "
    aggregate_only = bool(_AGGREGATE_ONLY_PATTERN.match(normalized))
    if not has_limit and not aggregate_only:
        raise SQLSafetyError("Non-aggregate queries must include a LIMIT clause.")

    return normalized


def get_connection(config: DBConfig | None = None) -> pymysql.connections.Connection:
    """Open a new MySQL connection using read-only app credentials."""
    cfg = config or load_db_config_from_env()
    return pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database,
        cursorclass=DictCursor,
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        write_timeout=cfg.write_timeout,
        autocommit=True,
    )


def execute_readonly_query(
    sql: str,
    params: tuple[Any, ...] | None = None,
    config: DBConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Validate and execute a read-only query.

    Raises:
        SQLSafetyError: if SQL violates policy.
        pymysql.MySQLError: if the database rejects the query.
    """
    safe_sql = validate_sql(sql)
    with get_connection(config) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("SET SESSION max_execution_time = 30000")
            cursor.execute(safe_sql, params)
            return list(cursor.fetchall())

