"""Let Ask find organizations a teammate parked in a saved map.

Parked organizations are not in the verified database, so Ask lists them after
database results and labels them. Each one is embedded the first time Ask needs
it and the vector is cached with its map, so parking itself stays free.
"""

import hashlib
import math

from src.embed import embed_texts

# Measured on saved maps with voyage-3: relevant organizations sat at cosine
# distance 0.36-0.65 from the question, unrelated ones at 0.78 and above.
MAX_DISTANCE = 0.70
LIMIT = 5


def _doc(actor: dict) -> str:
    place = ", ".join(p for p in (actor.get("location_city"), actor.get("state"), actor.get("country")) if p)
    parts = (actor.get("name"), actor.get("actor_type"), actor.get("category_type"),
             actor.get("description"), actor.get("primary_technical_focus"),
             actor.get("mapped_topic"), place)
    return "\n".join(str(p) for p in parts if p)


def _distance(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return 1 - dot / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def search(question: str, store, skip_names=()) -> list[dict]:
    """Parked organizations close to the question, as Ask source rows."""
    found = store.parked_actors()
    if not found:
        return []
    docs = [_doc(actor) for _, _, actor in found]
    keys = ["ask-embedding:" + hashlib.sha256(d.encode()).hexdigest() for d in docs]
    vectors = [store.cached(run_id, key) for (run_id, _, _), key in zip(found, keys)]
    missing = [i for i, v in enumerate(vectors) if v is None]
    if missing:
        for i, vector in zip(missing, embed_texts([docs[i] for i in missing], "document")):
            store.cache(found[i][0], keys[i], vector)
            vectors[i] = vector
    (query,) = embed_texts([question], "query")
    skip = {n.casefold() for n in skip_names}
    rows = []
    for distance, i in sorted((_distance(query, v), i) for i, v in enumerate(vectors)):
        if distance > MAX_DISTANCE or len(rows) >= LIMIT:
            break
        run_id, description, actor = found[i]
        if actor["name"].casefold() in skip:
            continue
        skip.add(actor["name"].casefold())
        rows.append({"entity_id": f"parked:{run_id}:{actor['name']}", "entity_type": "actor",
                     "name": actor["name"], "doc_text": docs[i], "parked": True,
                     "map": description})
    return rows
