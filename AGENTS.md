# AGENTS.md: Text2SQL Agent Project Instructions

## Objective
Build an AI agent that translates natural-language questions into SQL, executes against MySQL, and returns a clear natural-language answer. The design should follow a stateful, self-correcting workflow inspired by Uber Query-GPT.

## Scope
- This is a MVP focused on correctness and safety.
- No hard latency/performance SLOs are required.
- Agent access is strictly read-only.

## Technology Stack
- **Language:** Python 3.13.x
- **Package Management:** `uv`
- **Linting & Formatting:** `ruff`
- **Agent Framework:** LangGraph
- **LLM Integration:** LangChain + Gemini API
- **LLM Tracing:** LangSmith
- **Database:** `mysql:8.x` with `genschsa/mysql-employees` sample data
- **Interface:** Streamlit
- **Containerization:** Docker + Docker Compose

## Agent Architecture
Implement an iterative LangGraph workflow, not a single zero-shot prompt.

### State Definition (`TypedDict`)
- `user_query`: original natural-language query
- `schema_context`: relevant schema snippets used for SQL generation
- `generated_sql`: latest SQL query
- `execution_result`: raw rows/columns from DB on success
- `execution_error`: DB or SQL error on failure
- `iteration_count`: retry counter for self-correction
- `final_answer`: user-facing answer

### Required Nodes and Routing
1. **Retrieve Schema**
   - Fetch only relevant schema context.
   - Prefer targeted retrieval over full-schema dumps.

2. **Generate SQL**
   - Produce valid MySQL SQL using `user_query` + `schema_context`.

3. **Validate SQL (Safety Gate)**
   - Enforce read-only policy before execution.
   - Reject any non-`SELECT` query and any query containing mutating/DDL keywords.
   - Require a bounded result pattern (`LIMIT` unless aggregation-only query).
   - Ensure single statement only.

4. **Execute SQL**
   - Execute validated SQL.
   - On success: store `execution_result` and route to **Synthesize Answer**.
   - On failure: store `execution_error` and route to **Self-Correct**.

5. **Self-Correct (Reflection)**
   - Use `execution_error` + failed SQL to generate a fixed SQL query.
   - Increment `iteration_count` and retry execution.
   - Maximum retries: 3 total execution attempts.

6. **Fail Gracefully (Terminal)**
   - If all retries fail, set `final_answer` with:
     - a concise explanation,
     - why the query failed,
     - what the user can rephrase.

7. **Synthesize Answer**
   - Convert `execution_result` into a helpful response grounded in returned data only.

## SQL Safety Requirements (Non-Negotiable)
- Strictly read-only DB credentials.
- Allow only `SELECT` statements.
- Block `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `ALTER`, `DROP`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`, and multi-statement SQL.
- Never execute raw user SQL directly.
- Log rejected SQL with reason for debugging.

## Schema Retrieval Strategy
- Rank candidate tables using query keyword overlap on:
  - table names,
  - column names,
  - lightweight table descriptions if available.
- Keep retrieved schema under a practical context budget.
- Include join hints from foreign keys when possible.

## Answer Contract
`final_answer` should:
- answer the question directly,
- include key values and units when relevant,
- mention when results are empty,
- avoid unsupported claims beyond the SQL result.

## MVP Definition of Done
- Dockerized app boots with one command.
- End-to-end flow works: NL query -> SQL -> execution -> answer.
- Reflection loop works for at least one failed-then-fixed query.
- Read-only safety gate blocks disallowed SQL patterns.
- Basic lint checks pass (`ruff`).

## Evaluation Plan
- Once MVP is stable, create a golden dataset of NL prompts and expected outputs.
- Include:
  - straightforward lookups,
  - joins,
  - aggregations,
  - date filters,
  - ambiguous prompts (expected clarification behavior),
  - failure cases (expected graceful error responses).
- Use this dataset as a regression suite for future prompt/agent changes.

## Project Structure
The application must run entirely through Docker Compose.

```text
.
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env                    # Secret variables
├── src/
│   ├── app.py              # Streamlit UI
│   ├── agent.py            # LangGraph workflow definition
│   ├── database.py         # Database connection logic and safety validation
│   └── prompts.py          # Prompt templates for SQL and synthesis
└── AGENTS.md
```

## Required Environment Variables
- `GEMINI_API_KEY`
- `LANGSMITH_TRACING`
- `LANGSMITH_ENDPOINT`
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `DB_NAME`
- `MYSQL_ROOT_PASSWORD`

## Default Run Command
```bash
docker compose up --build
```
