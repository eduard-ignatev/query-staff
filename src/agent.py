"""LangGraph workflow for SQL generation, validation, and self-correction."""

from __future__ import annotations

import json
import os
from typing import TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

from database import SQLSafetyError, get_schema_context, validate_sql
from prompts import sql_correction_prompt, sql_generation_prompt

load_dotenv()


MAX_ITERATIONS = 3


class AgentState(TypedDict):
    user_query: str
    schema_context: str
    generated_sql: str
    generation_explanation: str
    validation_error: str
    correction_explanation: str
    iteration_count: int


class StructuredSQLResponse(TypedDict):
    explanation: str
    sql_query: str


def _build_model() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
        temperature=0,
    )


def _as_text(content: object) -> str:
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


def _extract_json_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not contain a JSON object.")
    return stripped[start : end + 1]


def _invoke_structured_sql(prompt: str) -> StructuredSQLResponse:
    model = _build_model()
    response = model.invoke(prompt)
    raw_text = _as_text(response.content)
    payload = json.loads(_extract_json_block(raw_text))
    explanation = str(payload.get("explanation", "")).strip()
    sql_query = str(payload.get("sql_query", "")).strip()
    if not explanation or not sql_query:
        raise ValueError("Structured output must include non-empty 'explanation' and 'sql_query'.")
    return {"explanation": explanation, "sql_query": sql_query}


def retrieve_schema_node(state: AgentState) -> AgentState:
    return {
        **state,
        "schema_context": get_schema_context(state["user_query"]),
        "validation_error": "",
    }


def generate_sql_node(state: AgentState) -> AgentState:
    structured = _invoke_structured_sql(
        sql_generation_prompt(state["user_query"], state["schema_context"])
    )
    return {
        **state,
        "generated_sql": structured["sql_query"],
        "generation_explanation": structured["explanation"],
        "validation_error": "",
    }


def validate_sql_node(state: AgentState) -> AgentState:
    try:
        normalized_sql = validate_sql(state["generated_sql"])
        return {
            **state,
            "generated_sql": normalized_sql,
            "validation_error": "",
        }
    except SQLSafetyError as exc:
        return {
            **state,
            "validation_error": f"SQL safety validation failed: {exc}",
            "iteration_count": state["iteration_count"] + 1,
        }


def self_correct_node(state: AgentState) -> AgentState:
    structured = _invoke_structured_sql(
        sql_correction_prompt(
            user_query=state["user_query"],
            schema_context=state["schema_context"],
            failed_sql=state["generated_sql"],
            validation_error=state["validation_error"],
        )
    )
    return {
        **state,
        "generated_sql": structured["sql_query"],
        "correction_explanation": structured["explanation"],
    }


def success_node(state: AgentState) -> AgentState:
    return state


def fail_gracefully_node(state: AgentState) -> AgentState:
    return state


def route_after_validate(state: AgentState) -> str:
    if not state["validation_error"]:
        return "success"
    return "fail" if state["iteration_count"] >= MAX_ITERATIONS else "self_correct"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve_schema", retrieve_schema_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("self_correct", self_correct_node)
    graph.add_node("success", success_node)
    graph.add_node("fail_gracefully", fail_gracefully_node)

    graph.add_edge(START, "retrieve_schema")
    graph.add_edge("retrieve_schema", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "success": "success",
            "self_correct": "self_correct",
            "fail": "fail_gracefully",
        },
    )
    graph.add_edge("self_correct", "validate_sql")
    graph.add_edge("success", END)
    graph.add_edge("fail_gracefully", END)
    return graph.compile()


_PLAN_GRAPH = build_graph()


def _initial_state(user_query: str) -> AgentState:
    return {
        "user_query": user_query,
        "schema_context": "",
        "generated_sql": "",
        "generation_explanation": "",
        "validation_error": "",
        "correction_explanation": "",
        "iteration_count": 0,
    }


def generate_query_plan(user_query: str) -> AgentState:
    """Generate a validated SQL plan (no execution)."""
    return _PLAN_GRAPH.invoke(_initial_state(user_query))
