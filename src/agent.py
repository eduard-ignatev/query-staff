"""LangGraph workflow for the Text2SQL MVP."""

from __future__ import annotations

import os
import re
from typing import Any, TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

from database import SQLExecutionError, SQLSafetyError, execute_readonly_query, get_schema_context, validate_sql
from prompts import sql_correction_prompt, sql_generation_prompt

load_dotenv()


MAX_ITERATIONS = 3


class AgentState(TypedDict):
    user_query: str
    schema_context: str
    generated_sql: str
    execution_result: list[dict[str, Any]]
    execution_error: str
    iteration_count: int
    final_answer: str


def _build_model() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
        temperature=0,
    )


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content).strip()


def _extract_sql(text: str) -> str:
    text = text.strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


def retrieve_schema_node(state: AgentState) -> AgentState:
    schema_context = get_schema_context(state["user_query"])
    return {**state, "schema_context": schema_context, "execution_error": ""}


def generate_sql_node(state: AgentState) -> AgentState:
    model = _build_model()
    prompt = sql_generation_prompt(state["user_query"], state["schema_context"])
    response = model.invoke(prompt)
    sql = _extract_sql(_as_text(response.content))
    return {**state, "generated_sql": sql, "execution_error": ""}


def validate_sql_node(state: AgentState) -> AgentState:
    try:
        normalized = validate_sql(state["generated_sql"])
        return {**state, "generated_sql": normalized, "execution_error": ""}
    except SQLSafetyError as exc:
        return {
            **state,
            "execution_error": f"SQL safety validation failed: {exc}",
            "iteration_count": state["iteration_count"] + 1,
        }


def execute_sql_node(state: AgentState) -> AgentState:
    try:
        rows = execute_readonly_query(state["generated_sql"])
        return {
            **state,
            "execution_result": rows,
            "execution_error": "",
        }
    except SQLExecutionError as exc:
        return {
            **state,
            "execution_error": f"SQL execution failed: {exc}",
            "iteration_count": state["iteration_count"] + 1,
        }


def self_correct_node(state: AgentState) -> AgentState:
    model = _build_model()
    prompt = sql_correction_prompt(
        user_query=state["user_query"],
        schema_context=state["schema_context"],
        failed_sql=state["generated_sql"],
        execution_error=state["execution_error"],
    )
    response = model.invoke(prompt)
    fixed_sql = _extract_sql(_as_text(response.content))
    return {**state, "generated_sql": fixed_sql}


def synthesize_answer_node(state: AgentState) -> AgentState:
    rows = state["execution_result"]
    row_count = len(rows)
    if row_count == 0:
        message = "Query executed successfully. No rows returned."
    else:
        message = f"Query executed successfully. Returned {row_count} row(s)."
    return {
        **state,
        "final_answer": message,
    }


def fail_gracefully_node(state: AgentState) -> AgentState:
    return {
        **state,
        "final_answer": (
            "I could not produce a valid query after multiple attempts. "
            f"Last error: {state['execution_error']} "
            "Please rephrase the question with table names or clearer filters."
        ),
    }


def route_after_validate(state: AgentState) -> str:
    if state["execution_error"]:
        return "fail" if state["iteration_count"] >= MAX_ITERATIONS else "self_correct"
    return "execute"


def route_after_execute(state: AgentState) -> str:
    if not state["execution_error"]:
        return "synthesize"
    return "fail" if state["iteration_count"] >= MAX_ITERATIONS else "self_correct"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve_schema", retrieve_schema_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("execute_sql", execute_sql_node)
    graph.add_node("self_correct", self_correct_node)
    graph.add_node("synthesize_answer", synthesize_answer_node)
    graph.add_node("fail_gracefully", fail_gracefully_node)

    graph.add_edge(START, "retrieve_schema")
    graph.add_edge("retrieve_schema", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "execute": "execute_sql",
            "self_correct": "self_correct",
            "fail": "fail_gracefully",
        },
    )
    graph.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {
            "synthesize": "synthesize_answer",
            "self_correct": "self_correct",
            "fail": "fail_gracefully",
        },
    )
    graph.add_edge("self_correct", "validate_sql")
    graph.add_edge("synthesize_answer", END)
    graph.add_edge("fail_gracefully", END)
    return graph.compile()


_GRAPH = build_graph()


def _initial_state(user_query: str) -> AgentState:
    return {
        "user_query": user_query,
        "schema_context": "",
        "generated_sql": "",
        "execution_result": [],
        "execution_error": "",
        "iteration_count": 0,
        "final_answer": "",
    }


def generate_query_plan(user_query: str) -> AgentState:
    """Generate and validate SQL without executing it."""
    state = _initial_state(user_query)
    state = retrieve_schema_node(state)
    state = generate_sql_node(state)
    state = validate_sql_node(state)
    if state["execution_error"]:
        state["final_answer"] = (
            "I generated SQL but it failed safety validation. "
            f"Error: {state['execution_error']}"
        )
    return state


def run_approved_query(user_query: str, approved_sql: str) -> AgentState:
    """Execute a user-approved SQL query and synthesize an answer."""
    state = _initial_state(user_query)
    state["generated_sql"] = approved_sql
    state = validate_sql_node(state)
    if state["execution_error"]:
        return fail_gracefully_node(state)

    state = execute_sql_node(state)
    if state["execution_error"]:
        return fail_gracefully_node(state)

    return synthesize_answer_node(state)


def run_agent(user_query: str) -> AgentState:
    """Full automatic workflow with self-correction loop."""
    return _GRAPH.invoke(_initial_state(user_query))
