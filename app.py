"""Streamlit UI — the Ask tab. v0.1: ugly and working beats late and polished.

Run from the project root:
    streamlit run app.py

Flow: question -> retrieve (hybrid) -> generate (Claude, streaming) -> answer,
with an expander listing the source entities so every answer is traceable.
"""

import streamlit as st

from src.retrieve import retrieve
from src.generate import stream_answer

st.set_page_config(page_title="UM6P Intelligence — Ask", page_icon="🔎")

st.title("🔎 Ask the map")
st.caption("Plain-English search over the UM6P Global Hubs research database. "
           "Every answer cites its sources.")

question = st.text_input(
    "Your question",
    placeholder="e.g. Who works on phosphogypsum immobilization?",
)

if question:
    with st.spinner("Searching the map…"):
        hits = retrieve(question)

    if not hits:
        st.warning("No matching entities found in the map.")
    else:
        st.subheader("Answer")
        # st.write_stream consumes the generator and renders tokens live.
        st.write_stream(stream_answer(question, hits))

        with st.expander(f"Sources ({len(hits)} entities retrieved)"):
            for i, h in enumerate(hits, 1):
                st.markdown(f"**{i}. {h['name']}**  ·  _{h['entity_type']}_")
                # Show a short preview of what was matched.
                preview = h["doc_text"][:300]
                st.caption(preview + ("…" if len(h["doc_text"]) > 300 else ""))
