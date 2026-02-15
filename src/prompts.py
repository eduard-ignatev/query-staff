"""Prompt builders for SQL generation, correction, and synthesis."""

from __future__ import annotations


SQL_POLICY = """You are a MySQL Text2SQL assistant.

Hard rules:
- Return exactly one SQL statement.
- Only SELECT is allowed.
- Never use INSERT, UPDATE, DELETE, REPLACE, ALTER, DROP, TRUNCATE, CREATE, GRANT, REVOKE.
- Use only tables/columns from the provided schema context.
- Prefer explicit JOIN conditions.
- For non-aggregate queries, include LIMIT 100 or lower.
- Do not include explanations outside SQL.
"""


def sql_generation_prompt(user_query: str, schema_context: str) -> str:
    return f"""{SQL_POLICY}

Schema context:
{schema_context}

User question:
{user_query}

Output only SQL.
"""


def sql_correction_prompt(
    user_query: str, schema_context: str, failed_sql: str, execution_error: str
) -> str:
    return f"""{SQL_POLICY}

The previous SQL failed.
User question:
{user_query}

Schema context:
{schema_context}

Failed SQL:
{failed_sql}

Error:
{execution_error}

Produce a corrected SQL statement only.
"""


def answer_synthesis_prompt(user_query: str, sql: str, result_rows: list[dict]) -> str:
    return f"""You are answering a user question from SQL query results.

Rules:
- Be concise and direct.
- Use only facts from the provided rows.
- If rows are empty, say no matching data was found.
- Mention key values from the result.

User question:
{user_query}

Executed SQL:
{sql}

Rows:
{result_rows}
"""
