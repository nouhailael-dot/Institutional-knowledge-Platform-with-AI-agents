"""Let Ask find organizations, people and events a teammate parked in a saved map.

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


def _name(record: dict) -> str:
    return record.get("full_name") if record.get("_entity_type") == "person" else record.get("name")


def _doc(record: dict) -> str:
    kind = record.get("_entity_type")
    if kind == "person":
        parts = (record.get("full_name"), record.get("title"), record.get("organization_name"),
                 record.get("organization_location"), record.get("expertise"),
                 record.get("work_evidence"))
    elif kind == "event":
        parts = (record.get("name"), record.get("event_type"), record.get("next_date"),
                 record.get("location"), record.get("organizer"), record.get("sector"),
                 record.get("thematic_focus"), record.get("description"))
    else:
        place = ", ".join(p for p in (record.get("location_city"), record.get("state"),
                                      record.get("country")) if p)
        parts = (record.get("name"), record.get("actor_type"), record.get("category_type"),
                 record.get("description"), record.get("primary_technical_focus"),
                 record.get("mapped_topic"), place)
    return "\n".join(str(p) for p in parts if p)


def _distance(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return 1 - dot / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def search(question: str, store, skip_names=()) -> list[dict]:
    """Parked organizations, people and events close to the question, as Ask source rows."""
    found = store.parked_records()
    if not found:
        return []
    docs = [_doc(record) for _, _, record in found]
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
        run_id, description, record = found[i]
        name = str(_name(record) or "")
        if not name or name.casefold() in skip:
            continue
        skip.add(name.casefold())
        rows.append({"entity_id": f"parked:{run_id}:{name}", "entity_type": record["_entity_type"],
                     "name": name, "doc_text": docs[i], "parked": True, "map": description})
    return rows
