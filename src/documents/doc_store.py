"""Per-session, in-memory vector store for one uploaded document.

Chunks are embedded with the same Voyage model as the map (src.embed) and held
in Streamlit session state as a NumPy matrix. Retrieval is cosine similarity in
NumPy — at a few dozen chunks this is instant and needs no index.

Hard rule: nothing here is written to Postgres. The store lives in
st.session_state and is cleared when the file is removed or the session ends.
"""

from __future__ import annotations

import numpy as np

from src.documents.chunk import chunk_text
from src.embed import embed_texts

# Key under which the built store lives in st.session_state.
STATE_KEY = "doc_store"

RETRIEVE_K = 5


def build_store(doc_text: str, filename: str) -> dict:
    """Chunk + embed a document. Returns a store dict (caller stashes it in
    session state). Embeddings are L2-normalised so cosine == dot product."""
    chunks = chunk_text(doc_text)
    if not chunks:
        return {"filename": filename, "chunks": [], "matrix": None}

    vectors = embed_texts(chunks, input_type="document")
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.clip(norms, 1e-8, None)

    return {"filename": filename, "chunks": chunks, "matrix": matrix}


def search_chunks(store: dict | None, query: str, k: int = RETRIEVE_K) -> list[dict]:
    """Return the top-k most similar chunks, shaped like a retrieve() hit so
    generate.stream_answer / _format_context handle them exactly like a map
    entity — just with entity_type="uploaded_document"."""
    if not store or store.get("matrix") is None or not store.get("chunks"):
        return []

    (q,) = embed_texts([query], input_type="query")
    q = np.asarray(q, dtype=np.float32)
    q = q / max(float(np.linalg.norm(q)), 1e-8)

    sims = store["matrix"] @ q                       # cosine, since both normed
    top = np.argsort(-sims)[:k]

    fname = store["filename"]
    out = []
    for i in top:
        out.append({
            "entity_id": f"doc::{i}",
            "entity_type": "uploaded_document",
            "name": f"{fname} — passage {int(i) + 1}",
            "doc_text": store["chunks"][int(i)],
            "score": float(sims[int(i)]),
        })
    return out
