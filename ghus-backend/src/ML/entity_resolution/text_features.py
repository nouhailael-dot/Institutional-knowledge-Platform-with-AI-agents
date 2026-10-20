"""
Shared text features for entity resolution.

Builds one text "document" per actor from name + description + location +
linked-hub context (the embedding input chosen in the handoff, section 8), plus
a TF-IDF matrix over those documents. Reused by the Week-1 dataset sampler and
the Week-2 TF-IDF baseline so the representation is identical across both.

DB imports are deliberately lazy (inside the function) so this module imports
with only scikit-learn installed — handy for testing the vectorizer in isolation.
"""

from sklearn.feature_extraction.text import TfidfVectorizer


def build_actor_documents(session):
    """Return (actor_ids, names, docs) as parallel lists, ordered by name.

    `docs[k]` is the text used to represent `actor_ids[k]`; `names[k]` is kept
    separately for display in the labeling CSV.
    """
    from sqlalchemy import select
    from src.db.models import Actor, Hub, HubActor

    # actor_id -> list of hub names it belongs to (disambiguating context)
    hub_ctx = {}
    for actor_id, hub_name in session.execute(
        select(HubActor.actor_id, Hub.name).join(Hub, Hub.hub_id == HubActor.hub_id)
    ).all():
        hub_ctx.setdefault(actor_id, []).append(hub_name)

    actor_ids, names, docs = [], [], []
    for a in session.execute(select(Actor).order_by(Actor.name)).scalars():
        parts = [a.name or ""]
        if a.description:
            parts.append(a.description)
        loc = " ".join(x for x in [a.location_city, a.state, a.country] if x)
        if loc:
            parts.append(loc)
        ctx = hub_ctx.get(a.actor_id)
        if ctx:
            parts.append("hubs: " + ", ".join(ctx))
        actor_ids.append(a.actor_id)
        names.append(a.name)
        docs.append("\n".join(parts))
    return actor_ids, names, docs


def tfidf_matrix(docs, **kwargs):
    """Fit a TF-IDF vectorizer over the documents. Returns (vectorizer, matrix)."""
    vec = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        **kwargs,
    )
    return vec, vec.fit_transform(docs)