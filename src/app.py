"""Streamlit UI for the Text2SQL MVP."""

from __future__ import annotations

from dotenv import load_dotenv
import streamlit as st

from agent import run_agent

load_dotenv()

st.set_page_config(page_title="Query Staff", page_icon=":mag:", layout="centered")
st.title("Query Staff")
st.caption("Ask natural-language questions about the employees database.")

query = st.text_area(
    "Question",
    placeholder="Example: What is the average salary by department? Limit to top 5 departments.",
    height=120,
)

run_clicked = st.button("Run Query", type="primary")

if run_clicked:
    if not query.strip():
        st.warning("Please enter a question first.")
    else:
        with st.spinner("Generating SQL and running query..."):
            final_state = run_agent(query.strip())

        st.subheader("Answer")
        st.write(final_state["final_answer"])

        with st.expander("Debug Details"):
            st.markdown("**Generated SQL**")
            st.code(final_state["generated_sql"], language="sql")

            st.markdown("**Iteration Count**")
            st.write(final_state["iteration_count"])

            st.markdown("**Execution Error**")
            st.write(final_state["execution_error"] or "<none>")

            st.markdown("**Execution Result (rows)**")
            st.write(final_state["execution_result"])
