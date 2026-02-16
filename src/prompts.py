"""Prompt builders for SQL generation and correction."""

from __future__ import annotations


SQL_POLICY = """You are a MySQL Text2SQL assistant.

Hard rules:
- Return exactly one SQL statement in the `sql_query` field.
- Only SELECT is allowed.
- Never use INSERT, UPDATE, DELETE, REPLACE, ALTER, DROP, TRUNCATE, CREATE, GRANT, REVOKE.
- Use only tables/columns from the provided schema context.
- Prefer explicit JOIN conditions.
- For non-aggregate queries, include LIMIT 100 or lower.

Output format:
- Return strict JSON with exactly two keys:
  - "explanation": short rationale for query design
  - "sql_query": the SQL statement
- Do not include markdown fences or any extra text.
"""


def sql_generation_prompt(user_query: str, schema_context: str) -> str:
    return f"""{SQL_POLICY}

Schema context:
{schema_context}

User question:
{user_query}

Produce structured JSON output only.
"""


def sql_correction_prompt(
    user_query: str, schema_context: str, failed_sql: str, validation_error: str
) -> str:
    return f"""{SQL_POLICY}

The previous SQL failed.
User question:
{user_query}

Schema context:
{schema_context}

Failed SQL:
{failed_sql}

Validation error:
{validation_error}

Produce corrected structured JSON output only.
"""
