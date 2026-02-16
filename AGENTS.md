# AGENTS.md: Text2SQL Agent Project Instructions

## Objective
Build an AI agent that translates natural-language questions into SQL for user review, then allows approved SQL execution against MySQL from Streamlit. The design should follow a stateful, self-correcting workflow inspired by Uber Query-GPT.

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
Implement an iterative self-correcting workflow for SQL generation and validation. SQL execution is handled by the Streamlit layer after user approval.

### State Definition (`TypedDict`)
- `user_query`: original natural-language query
- `schema_context`: schema context used for SQL generation
- `generated_sql`: latest SQL query
- `generation_explanation`: brief rationale from the model for generated SQL
- `validation_error`: SQL safety/validation error message
- `correction_explanation`: brief rationale from the model for corrected SQL
- `iteration_count`: retry counter for self-correction
- `final_answer`: terminal status message for generation/correction flow

### Required Nodes and Routing
1. **Retrieve Schema**
   - Load schema context for SQL generation.
   - Full schema loading is acceptable for this sample database.

2. **Generate SQL**
   - Produce valid MySQL SQL using `user_query` + `schema_context`.
   - Must return structured output with:
     - `explanation`
     - `sql_query`

3. **Validate SQL (Safety Gate)**
   - Enforce read-only policy before execution.
   - Reject any non-`SELECT` query and any query containing mutating/DDL keywords.
   - Require a bounded result pattern (`LIMIT` unless aggregation-only query).
   - Ensure single statement only.

4. **Self-Correct (Reflection)**
   - Triggered when validation fails.
   - Use validation error + failed SQL to generate a fixed SQL query.
   - Must return structured output with:
     - `explanation`
     - `sql_query`
   - Increment `iteration_count` and retry validation.
   - Maximum retries: 3.

5. **Fail Gracefully (Terminal)**
   - If all retries fail, set `final_answer` with:
     - a concise explanation,
     - why validation failed,
     - what the user can rephrase.

## Execution Boundary
- Query execution is not an agent node.
- Streamlit executes SQL only after explicit user approval (`Generate Query` -> review/edit -> `Run Query`).
- Query result rendering is tabular UI output, not LLM synthesis.

## SQL Safety Requirements (Non-Negotiable)
- Strictly read-only DB credentials.
- Allow only `SELECT` statements.
- Block `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `ALTER`, `DROP`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`, and multi-statement SQL.
- Never execute raw user SQL directly.
- Log rejected SQL with reason for debugging.

## Structured Output Contract (Required)
Both SQL generation and SQL correction model calls must return structured output:
- `explanation`: short natural-language rationale (for user/debug visibility).
- `sql_query`: single MySQL `SELECT` statement candidate.

## MVP Definition of Done
- Dockerized app boots with one command.
- End-to-end flow works: NL query -> Generate Query -> user review/edit -> Run Query -> table output.
- Reflection loop works for at least one validation-failed-then-fixed query.
- Read-only safety gate blocks disallowed SQL patterns.
- Structured output (`explanation`, `sql_query`) is enforced for generation and correction calls.
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
│   ├── agent.py            # SQL generation/validation/correction workflow
│   ├── database.py         # Database connection logic and safety validation
│   └── prompts.py          # Prompt templates for SQL generation/correction
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
