"""Streamlit UI — the Ask tab.

Two engines behind one box (the v0.2 router):
  - Counting / aggregation / membership questions  -> SQL (exact, from the DB)
  - Conceptual / "who works on X" questions         -> RAG (hybrid retrieve + Claude)

Every RAG answer cites its sources; every SQL answer shows the query it ran.
Run from the project root:  streamlit run app.py
"""

import streamlit as st

from src.retrieve import retrieve
from src.generate import stream_answer
from src.router import plan, run_sql, format_sql_answer

st.set_page_config(page_title="UM6P Intelligence — Ask", page_icon="🔎")

st.title("🔎 Ask the map")
st.caption("Plain-English search over the UM6P Global Hubs research database. "
           "Counting questions are answered exactly from the database; everything "
           "else is answered from the map with cited sources.")

question = st.text_input(
    "Your question",
    placeholder="e.g. Who works on phosphogypsum?  ·  How many actors are at TRL 6+?",
)

if question:
    # 1. Route: is this a counting/structured question, or a conceptual one?
    with st.spinner("Understanding your question…"):
        mode, sql = plan(question)

    # 2a. SQL path — exact answer from the database.
    if mode == "sql":
        try:
            cols, rows = run_sql(sql)
            answer = format_sql_answer(question, sql, cols, rows)
            st.subheader("Answer")
            st.markdown(answer)
            st.caption("⚡ Computed directly from the database — exact, not estimated.")
            with st.expander("SQL query used"):
                st.code(sql, language="sql")
        except Exception as e:
            # If the generated SQL fails, fall back to the RAG path.
            st.info("Falling back to map search…")
            mode = "semantic"

    # 2b. Semantic path — hybrid retrieval + cited answer.
    if mode == "semantic":
        with st.spinner("Searching the map…"):
            hits = retrieve(question)

        if not hits:
            st.warning("No matching entities found in the map.")
        else:
            st.subheader("Answer")
            st.write_stream(stream_answer(question, hits))
            with st.expander(f"Sources ({len(hits)} entities retrieved)"):
                for i, h in enumerate(hits, 1):
                    st.markdown(f"**{i}. {h['name']}**  ·  _{h['entity_type']}_")
                    preview = h["doc_text"][:300]
                    st.caption(preview + ("…" if len(h["doc_text"]) > 300 else ""))
