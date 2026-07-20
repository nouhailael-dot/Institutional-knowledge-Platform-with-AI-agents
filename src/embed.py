"""Embed every assembled doc with Voyage and store it in search_doc.

Build step — run offline, once, and re-run whenever the source data changes:
    python -m src.embed

Idempotent: uses INSERT ... ON CONFLICT so re-running replaces rows in place
rather than duplicating them. Safe to run as many times as you like.

The `embed_texts` helper is shared with retrieve.py so the query and the
documents are embedded by the exact same model — mismatched models would make
cosine distances meaningless.
"""

import os

import voyageai

from src.assemble import assemble_all
from src.db import get_connection

MODEL = "voyage-3"          # 1024-dim output, matches search_doc.embedding
BATCH = 128                 # Voyage accepts up to 128 texts per request

_client = None


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        if not os.environ.get("VOYAGE_API_KEY"):
            raise RuntimeError("VOYAGE_API_KEY is not set. Add it to .env.")
        _client = voyageai.Client()  # reads VOYAGE_API_KEY from env
    return _client


def embed_texts(texts: list[str], input_type: str) -> list[list[float]]:
    """Embed a list of texts. input_type is 'document' when indexing and
    'query' when searching — Voyage optimizes the vector differently for each."""
    client = _get_client()
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        resp = client.embed(chunk, model=MODEL, input_type=input_type)
        out.extend(resp.embeddings)
    return out


def _to_pgvector(vec: list[float]) -> str:
    """pgvector accepts a bracketed string literal cast to ::vector."""
    return "[" + ",".join(str(x) for x in vec) + "]"


def build_index() -> int:
    docs = assemble_all()
    print(f"Assembled {len(docs)} docs. Embedding with {MODEL} ...")

    embeddings = embed_texts([d["doc_text"] for d in docs], input_type="document")
    print(f"Got {len(embeddings)} embeddings. Writing to search_doc ...")

    upsert = """
        INSERT INTO search_doc (entity_id, entity_type, name, doc_text, embedding)
        VALUES (%s, %s, %s, %s, %s::vector)
        ON CONFLICT (entity_id) DO UPDATE SET
            entity_type = EXCLUDED.entity_type,
            name        = EXCLUDED.name,
            doc_text    = EXCLUDED.doc_text,
            embedding   = EXCLUDED.embedding
    """
    with get_connection() as conn, conn.cursor() as cur:
        for d, emb in zip(docs, embeddings):
            cur.execute(upsert, (
                d["entity_id"], d["entity_type"], d["name"],
                d["doc_text"], _to_pgvector(emb),
            ))
        conn.commit()
    return len(docs)


if __name__ == "__main__":
    n = build_index()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM search_doc")
        stored = cur.fetchone()[0]
    print(f"Done. Embedded {n} docs; search_doc now holds {stored} rows.")
