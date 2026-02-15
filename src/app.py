"""Streamlit UI for the Text2SQL MVP."""

from __future__ import annotations

from dotenv import load_dotenv
import streamlit as st

from agent import generate_query_plan, run_approved_query
from database import get_schema_overview

load_dotenv()

st.set_page_config(page_title="Query Staff", page_icon=":mag:", layout="centered")
st.title("Query Staff")
st.caption("Ask natural-language questions about the employees database.")
st.markdown(
    """
    <style>
    div[data-testid="stTextArea"] textarea {
        font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 0.9rem;
        line-height: 1.4;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300)
def load_schema_overview() -> dict:
    return get_schema_overview()


with st.sidebar:
    st.header("Schema Overview")
    try:
        overview = load_schema_overview()
        st.caption(
            f"Database: `{overview['database']}`  |  "
            f"Tables: {overview['table_count']}"
        )
        for table in overview["tables"]:
            with st.expander(table["table_name"], expanded=False):
                st.markdown("**Columns**")
                for col in table["columns"]:
                    st.write(f"- `{col['column_name']}` ({col['data_type']})")
                if table["foreign_keys"]:
                    st.markdown("**Foreign Keys**")
                    for fk in table["foreign_keys"]:
                        st.write(
                            f"- `{fk['column_name']}` -> "
                            f"`{fk['referenced_table_name']}.{fk['referenced_column_name']}`"
                        )
    except Exception as exc:  # pragma: no cover
        st.warning(f"Could not load schema overview: {exc}")

query = st.text_area(
    "Question",
    placeholder="Example: What is the average salary by department? Limit to top 5 departments.",
    height=120,
)

if "generated_for_query" not in st.session_state:
    st.session_state.generated_for_query = ""
if "approved_sql" not in st.session_state:
    st.session_state.approved_sql = ""
if "generated_state" not in st.session_state:
    st.session_state.generated_state = None
if "executed_state" not in st.session_state:
    st.session_state.executed_state = None


if query.strip() != st.session_state.generated_for_query:
    st.session_state.approved_sql = ""
    st.session_state.generated_state = None
    st.session_state.executed_state = None


generate_clicked = st.button("Generate Query", use_container_width=True)

if generate_clicked:
    if not query.strip():
        st.warning("Please enter a question first.")
    else:
        with st.spinner("Generating SQL..."):
            state = generate_query_plan(query.strip())

        st.session_state.generated_for_query = query.strip()
        st.session_state.approved_sql = state["generated_sql"]
        st.session_state.generated_state = state
        st.session_state.executed_state = None

        if state["execution_error"]:
            st.error(state["execution_error"])
        else:
            st.success("Query generated. Review it, then click Run Query.")

if st.session_state.approved_sql:
    st.subheader("Review Generated SQL")
    st.session_state.approved_sql = st.text_area(
        "Generated SQL (editable)",
        value=st.session_state.approved_sql,
        height=200,
        key="approved_sql_editor",
    )

    debug_state = st.session_state.executed_state or st.session_state.generated_state
    if debug_state:
        with st.expander("Debug Details"):
            st.markdown("**Generated SQL**")
            st.code(debug_state["generated_sql"], language="sql")

            st.markdown("**Iteration Count**")
            st.write(debug_state["iteration_count"])

            st.markdown("**Execution Error**")
            st.write(debug_state["execution_error"] or "<none>")

            st.markdown("**Execution Result (rows)**")
            st.write(debug_state["execution_result"])

    run_clicked = st.button("Run Query", type="primary", use_container_width=True)
    if run_clicked:
        if not query.strip():
            st.warning("Please enter a question first.")
        elif not st.session_state.approved_sql.strip():
            st.warning("Generate a query first before running.")
        elif query.strip() != st.session_state.generated_for_query:
            st.warning("Question changed. Please click Generate Query again.")
        else:
            with st.spinner("Running approved SQL..."):
                state = run_approved_query(query.strip(), st.session_state.approved_sql.strip())
            st.session_state.executed_state = state

if st.session_state.executed_state:
    final_state = st.session_state.executed_state
    st.subheader("Result")
    st.write(final_state["final_answer"])

    rows = final_state["execution_result"]
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("No rows to display.")
