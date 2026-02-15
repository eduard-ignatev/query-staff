"""Database access, schema introspection, and SQL safety validation."""

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
_LIMIT_PATTERN = re.compile(r"\blimit\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"\b[a-z_]+\b", re.IGNORECASE)


class SQLSafetyError(ValueError):
    """Raised when SQL violates the read-only safety policy."""


class SQLExecutionError(RuntimeError):
    """Raised when SQL execution fails after passing safety validation."""


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

    has_limit = bool(_LIMIT_PATTERN.search(normalized))
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
            try:
                cursor.execute(safe_sql, params)
            except pymysql.MySQLError as exc:
                raise SQLExecutionError(str(exc)) from exc
            return list(cursor.fetchall())


def get_schema_context(
    user_query: str,
    max_tables: int = 6,
    max_columns_per_table: int = 20,
    config: DBConfig | None = None,
) -> str:
    """Return targeted schema context for prompt grounding."""
    keywords = _extract_keywords(user_query)
    with get_connection(config) as conn:
        with conn.cursor() as cursor:
            db_name = (config or load_db_config_from_env()).database
            table_names = _fetch_table_names(cursor, db_name)
            ranked_tables = _rank_tables(table_names, keywords)
            selected_tables = ranked_tables[:max_tables] if ranked_tables else table_names[:max_tables]

            table_descriptions: list[str] = []
            for table_name in selected_tables:
                columns = _fetch_columns(cursor, db_name, table_name, max_columns_per_table)
                foreign_keys = _fetch_foreign_keys(cursor, db_name, table_name)
                table_descriptions.append(_format_table_context(table_name, columns, foreign_keys))

            return "\n\n".join(table_descriptions)


def _extract_keywords(text: str) -> set[str]:
    return {word.lower() for word in _WORD_PATTERN.findall(text) if len(word) > 2}


def _fetch_table_names(cursor: DictCursor, db_name: str) -> list[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
        ORDER BY table_name
        """,
        (db_name,),
    )
    return [row["table_name"] for row in cursor.fetchall()]


def _fetch_columns(
    cursor: DictCursor, db_name: str, table_name: str, max_columns: int
) -> list[dict[str, str]]:
    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable, column_key
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        LIMIT %s
        """,
        (db_name, table_name, max_columns),
    )
    return list(cursor.fetchall())


def _fetch_foreign_keys(cursor: DictCursor, db_name: str, table_name: str) -> list[dict[str, str]]:
    cursor.execute(
        """
        SELECT
            column_name,
            referenced_table_name,
            referenced_column_name
        FROM information_schema.key_column_usage
        WHERE table_schema = %s
          AND table_name = %s
          AND referenced_table_name IS NOT NULL
        ORDER BY column_name
        """,
        (db_name, table_name),
    )
    return list(cursor.fetchall())


def _rank_tables(table_names: list[str], keywords: set[str]) -> list[str]:
    def score(name: str) -> tuple[int, int]:
        tokens = set(_WORD_PATTERN.findall(name.lower()))
        overlap = len(tokens.intersection(keywords))
        # Keep deterministic ordering for equal scores.
        return (overlap, -len(name))

    return sorted(table_names, key=score, reverse=True)


def _format_table_context(
    table_name: str, columns: list[dict[str, str]], foreign_keys: list[dict[str, str]]
) -> str:
    column_lines = [
        f"- {col['column_name']} ({col['data_type']}, nullable={col['is_nullable']}, key={col['column_key'] or 'NONE'})"
        for col in columns
    ]
    if not column_lines:
        column_lines = ["- <no columns found>"]

    fk_lines = [
        f"- {fk['column_name']} -> {fk['referenced_table_name']}.{fk['referenced_column_name']}"
        for fk in foreign_keys
    ]
    if not fk_lines:
        fk_lines = ["- <no foreign keys>"]

    return (
        f"Table: {table_name}\n"
        f"Columns:\n{chr(10).join(column_lines)}\n"
        f"Foreign Keys:\n{chr(10).join(fk_lines)}"
    )


def get_schema_overview(
    max_columns_per_table: int = 15,
    config: DBConfig | None = None,
) -> dict[str, Any]:
    """Return a compact schema overview for sidebar display."""
    with get_connection(config) as conn:
        with conn.cursor() as cursor:
            db_name = (config or load_db_config_from_env()).database
            table_names = _fetch_table_names(cursor, db_name)
            tables: list[dict[str, Any]] = []

            for table_name in table_names:
                columns = _fetch_columns(cursor, db_name, table_name, max_columns_per_table)
                foreign_keys = _fetch_foreign_keys(cursor, db_name, table_name)
                tables.append(
                    {
                        "table_name": table_name,
                        "column_count": len(columns),
                        "columns": columns,
                        "foreign_keys": foreign_keys,
                    }
                )

            return {
                "database": db_name,
                "table_count": len(tables),
                "tables": tables,
            }
