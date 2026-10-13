"""Hybrid retrieval — THE CORE FILE. Retrieval quality IS answer quality.

A question comes in; two searches run against search_doc and their results are
fused into one ranked list of the top entities:

  1. Vector search  (pgvector cosine) — matches MEANING. Finds "nutrient
     management" when you ask about "soil health".
  2. Keyword search (Postgres tsvector) — matches EXACT TERMS. Catches acronyms
     (USGS, SRNL, IFAD) that vector search ranks poorly because they carry
     little semantic weight.

Neither alone is enough for this dataset, which is dense with acronyms. We merge
the two lists with Reciprocal Rank Fusion (RRF) — a simple, robust scheme that
needs no score calibration between the two very different scoring scales.
"""

from src.db import get_connection
from src.embed import embed_texts, _to_pgvector

RRF_K = 60  # RRF constant; 60 is the standard default, tune against evals later

# search_doc is a snapshot rebuilt offline (python -m src.embed). Between rebuilds
# it can still hold actors that were since rejected or merged, so an actor only
# counts when it is live in actor_read. Hubs and events are not reviewed.
LIVE_ONLY = """(entity_type <> 'actor' OR EXISTS (
    SELECT 1 FROM actor_read a
    WHERE a.actor_id = search_doc.entity_id AND a.merged_into_actor_id IS NULL))"""


def vector_search(question: str, limit: int = 20) -> list[dict]:
    """Semantic search: embed the question, find the nearest doc embeddings."""
    (query_vec,) = embed_texts([question], input_type="query")
    sql = f"""
        SELECT entity_id, entity_type, name, doc_text,
               embedding <=> %s::vector AS distance
        FROM search_doc
        WHERE {LIVE_ONLY}
        ORDER BY distance ASC
        LIMIT %s
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (_to_pgvector(query_vec), limit))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def keyword_search(question: str, limit: int = 20) -> list[dict]:
    """Lexical search over the tsvector. websearch_to_tsquery handles free text
    (quotes, OR, minus) gracefully, so raw user questions just work."""
    sql = f"""
        SELECT entity_id, entity_type, name, doc_text,
               ts_rank(doc_tsv, websearch_to_tsquery('english', %s)) AS rank
        FROM search_doc
        WHERE doc_tsv @@ websearch_to_tsquery('english', %s) AND {LIVE_ONLY}
        ORDER BY rank DESC
        LIMIT %s
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (question, question, limit))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _rrf_merge(vector_hits: list[dict], keyword_hits: list[dict],
               top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion. Each list contributes 1/(k + rank) to an entity's
    score; entities found by BOTH searches rise to the top. Rank is 0-indexed
    position in each list. Returns the top_k entities as full row dicts."""
    scores: dict = {}
    rows: dict = {}
    for hits in (vector_hits, keyword_hits):
        for rank, hit in enumerate(hits):
            eid = hit["entity_id"]
            scores[eid] = scores.get(eid, 0.0) + 1.0 / (RRF_K + rank + 1)
            rows[eid] = hit  # both lists carry the same columns; keep one copy

    ranked_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
    result = []
    for eid in ranked_ids:
        row = dict(rows[eid])
        row["score"] = scores[eid]
        result.append(row)
    return result


def retrieve(question: str, top_k: int = 10) -> list[dict]:
    """The public entry point: question -> top_k entities (hybrid).
    Each result is {entity_id, entity_type, name, doc_text, score}."""
    vector_hits = vector_search(question, limit=20)
    keyword_hits = keyword_search(question, limit=20)
    return _rrf_merge(vector_hits, keyword_hits, top_k)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "who works on phosphogypsum?"
    print(f"Query: {q}\n")
    for i, hit in enumerate(retrieve(q), 1):
        print(f"{i:2}. [{hit['entity_type']:5}] {hit['name']}  "
              f"(score {hit['score']:.4f})")
