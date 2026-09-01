"""
resolve_or_create.py — ingest-time entity resolution.

THE RULE: an incoming record NEVER becomes a new row until it has been scored
against the actors that already exist. This is what stops a weekly scraper from
regenerating the duplicates the backfill just removed.

    incoming record
        |
        score against canonical actors (frozen combiner)
        |
        +-- >= HIGH  -> ABSORB   : no new row. Fields the winner is missing are
        |                          copied onto it, relationships attach to the
        |                          existing actor_id, winner flagged needs_review.
        +-- >= LOW   -> REVIEW   : row is created but flagged, and the pair goes
        |                          into review_queue for a human. Nothing is
        |                          silently merged on a middling score.
        +-- <  LOW   -> CREATE   : genuinely new actor, inserted with
                                   verification_status='needs_review'.

This is the same three-zone logic as the sweep, applied one record at a time at
the point of ingestion instead of in a batch afterwards.

    from src.ML.entity_resolution.resolve_or_create import EntityResolver

    resolver = EntityResolver(session)            # loads model + candidates once
    result = resolver.resolve_actor({
        "name": "National Renewable Energy Lab",
        "description": "...", "website": "...", "location_city": "Golden",
    }, source_id=src.source_id)

    result.action        # 'absorbed' | 'queued_for_review' | 'created'
    result.actor_id      # the canonical actor to attach relationships to
    result.score         # what the model gave the best candidate
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_BUNDLE = "models/er_combiner_v1.joblib"
DEFAULT_CONFIG = "config/er_production.json"

# Fields an existing actor can inherit from an incoming record when it is empty.
INHERITABLE_FIELDS = [
    "actor_type", "actor_type_raw", "description", "website",
    "location_city", "state", "country",
    "primary_technical_focus", "technical_approach", "current_activities",
    "technology_ip_notes", "key_constraints", "estimated_trl",
    "primary_lifecycle_role",
]


@dataclass
class ResolutionResult:
    action: str                      # absorbed | queued_for_review | created
    actor_id: str                    # canonical id to attach relationships to
    score: float = 0.0
    matched_name: Optional[str] = None
    fields_absorbed: list = field(default_factory=list)
    review_id: Optional[str] = None


class EntityResolver:
    """Resolves incoming records against existing canonical actors.

    Candidates are loaded once and cached, so a weekly run of hundreds of records
    does not re-query the whole actor table each time. Call refresh() if the run
    inserts many actors and you want them visible to later records in the same run.
    """

    def __init__(self, session: Session, project_root: Optional[Path] = None,
                 bundle_path: str = DEFAULT_BUNDLE, config_path: str = DEFAULT_CONFIG):
        self.session = session
        root = project_root or Path(__file__).resolve().parents[3]
        cfg = json.loads((root / config_path).read_text())
        self.bundle = joblib.load(root / bundle_path)
        self.HIGH = float(cfg["high_threshold"])
        self.LOW = float(cfg["low_threshold"])
        self.model_name = cfg.get("model", "combiner")
        self.features = self.bundle["features"]
        self._sbert = None
        self.refresh()
        logger.info("EntityResolver ready: %d canonical actors, HIGH=%.3f LOW=%.3f",
                    len(self._actors), self.HIGH, self.LOW)

    # ---------- candidate pool ----------

    def refresh(self):
        """Reload the canonical actor pool (excludes merged-away rows)."""
        rows = self.session.execute(text("""
            SELECT a.actor_id::text AS actor_id, a.name,
                   COALESCE(a.description,'') AS description,
                   COALESCE(STRING_AGG(DISTINCT h.name, '; '), '') AS hubs
              FROM actor a
              LEFT JOIN hub_actor ha ON ha.actor_id = a.actor_id
              LEFT JOIN hub h ON h.hub_id = ha.hub_id
             WHERE a.merged_into_actor_id IS NULL
             GROUP BY a.actor_id, a.name, a.description
        """)).mappings().all()
        self._actors = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["actor_id", "name", "description", "hubs"])

    # ---------- scoring ----------

    def _sbert_model(self):
        if self._sbert is None:
            from sentence_transformers import SentenceTransformer
            self._sbert = SentenceTransformer(
                self.bundle.get("sbert_model_name",
                                "sentence-transformers/all-MiniLM-L6-v2"))
        return self._sbert

    def _candidates(self, name: str, top_k: int = 40) -> pd.DataFrame:
        """Cheap lexical shortlist before the expensive model runs."""
        if self._actors.empty:
            return self._actors
        vec = self.bundle["tfidf_vectorizer"]
        try:
            from src.ML.entity_resolution import er_common as ec
            norm = ec.normalize_name
        except ImportError:
            norm = lambda s: str(s).lower().strip()
        q = vec.transform([norm(name)])
        M = vec.transform(self._actors["name"].map(norm))
        sims = np.asarray(q.dot(M.T).todense()).ravel()
        idx = np.argsort(-sims)[:top_k]
        out = self._actors.iloc[idx].copy()
        out["_lex"] = sims[idx]
        return out[out["_lex"] > 0.15]

    def _score(self, record: dict, cands: pd.DataFrame) -> pd.DataFrame:
        from src.ML.entity_resolution import er_common as ec
        try:
            from src.ML.entity_resolution.er_mismatch_features import mismatch_features
        except ImportError:
            mismatch_features = None
        try:
            from src.ML.entity_resolution.er_description_features import description_features
        except ImportError:
            description_features = None

        pairs = pd.DataFrame({
            "name_a": [record.get("name", "")] * len(cands),
            "name_b": cands["name"].values,
            "hubs_a": [record.get("hubs", "")] * len(cands),
            "hubs_b": cands["hubs"].values,
            "desc_a": [record.get("description", "")] * len(cands),
            "desc_b": cands["description"].values,
        })

        vec = self.bundle["tfidf_vectorizer"]
        A = vec.transform(pairs.name_a.map(ec.normalize_name))
        B = vec.transform(pairs.name_b.map(ec.normalize_name))
        tfidf = np.asarray(A.multiply(B).sum(axis=1)).ravel()

        model = self._sbert_model()
        uniq = pd.concat([pairs.name_a, pairs.name_b]).unique().tolist()
        emb = model.encode(uniq, normalize_embeddings=True, show_progress_bar=False)
        lut = {t: e for t, e in zip(uniq, emb)}
        sbert = np.array([float(np.dot(lut[x], lut[y]))
                          for x, y in zip(pairs.name_a, pairs.name_b)])

        feats = pd.DataFrame({"tfidf_name_sim": tfidf, "sbert_name_sim": sbert})
        feats = pd.concat([feats, ec.name_features(pairs), ec.hub_feature(pairs)], axis=1)
        if mismatch_features is not None:
            feats = pd.concat([feats, mismatch_features(pairs)], axis=1)
        if description_features is not None:
            feats = pd.concat([feats, description_features(pairs)], axis=1)

        missing = [c for c in self.features if c not in feats.columns]
        if missing:
            raise RuntimeError(f"resolver cannot build features required by the "
                               f"frozen model: {missing}")
        X = feats[self.features].to_numpy(float)
        cands = cands.copy()
        cands["score"] = self.bundle["model"].predict_proba(X)[:, 1]
        return cands.sort_values("score", ascending=False)

    # ---------- the three actions ----------

    def _absorb(self, actor_id: str, record: dict) -> list:
        row = self.session.execute(
            text("SELECT * FROM actor WHERE actor_id = CAST(:a AS uuid)"),
            {"a": actor_id}).mappings().first()
        updates = {}
        for f in INHERITABLE_FIELDS:
            cur, new = row.get(f), record.get(f)
            empty = cur is None or (isinstance(cur, str) and not cur.strip())
            has_new = new is not None and str(new).strip() != ""
            if empty and has_new:
                updates[f] = new
        if not updates:
            return []
        sets = ", ".join(f"{k} = :{k}" for k in updates)
        params = dict(updates)
        params["a"] = actor_id
        self.session.execute(text(
            f"UPDATE actor SET {sets}, verification_status='needs_review', "
            f"updated_at=now() WHERE actor_id = CAST(:a AS uuid)"), params)
        return list(updates)

    def _queue(self, actor_id_a: str, actor_id_b: str, score: float) -> str:
        a, b = sorted([str(actor_id_a), str(actor_id_b)])
        rid = str(uuid.uuid4())
        self.session.execute(text(
            "INSERT INTO review_queue (review_id, actor_id_a, actor_id_b, score, "
            "model, status) VALUES (CAST(:r AS uuid), CAST(:a AS uuid), "
            "CAST(:b AS uuid), :s, :m, 'pending') "
            "ON CONFLICT ON CONSTRAINT uq_review_pair DO NOTHING"),
            {"r": rid, "a": a, "b": b, "s": float(score), "m": self.model_name})
        return rid

    def _create(self, record: dict, source_id) -> str:
        try:
            from src.etl.common.text_cleaning import slugify
        except ImportError:
            import re
            slugify = lambda s: re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
        aid = str(uuid.uuid4())
        cols = {"actor_id": aid, "name": record["name"],
                "slug": f"{slugify(record['name'])}-{aid[:8]}",
                "verification_status": "needs_review", "source_id": str(source_id)}
        for f in INHERITABLE_FIELDS:
            if record.get(f) is not None and str(record.get(f)).strip():
                cols[f] = record[f]
        names = ", ".join(cols)
        binds = ", ".join(
            f"CAST(:{c} AS uuid)" if c in ("actor_id", "source_id") else f":{c}"
            for c in cols)
        self.session.execute(text(f"INSERT INTO actor ({names}) VALUES ({binds})"), cols)
        return aid

    # ---------- entry point ----------

    def resolve_actor(self, record: dict, source_id, dry_run: bool = False
                      ) -> ResolutionResult:
        name = (record.get("name") or "").strip()
        if not name:
            raise ValueError("record has no name")

        cands = self._candidates(name)
        if cands.empty:
            if dry_run:
                return ResolutionResult("would_create", "", 0.0)
            return ResolutionResult("created", self._create(record, source_id), 0.0)

        scored = self._score(record, cands)
        best = scored.iloc[0]
        score, match_id, match_name = float(best["score"]), best["actor_id"], best["name"]

        if score >= self.HIGH:
            if dry_run:
                return ResolutionResult("would_absorb", match_id, score, match_name)
            absorbed = self._absorb(match_id, record)
            return ResolutionResult("absorbed", match_id, score, match_name, absorbed)

        if score >= self.LOW:
            if dry_run:
                return ResolutionResult("would_queue", match_id, score, match_name)
            new_id = self._create(record, source_id)
            rid = self._queue(new_id, match_id, score)
            return ResolutionResult("queued_for_review", new_id, score, match_name,
                                    review_id=rid)

        if dry_run:
            return ResolutionResult("would_create", "", score, match_name)
        return ResolutionResult("created", self._create(record, source_id),
                                score, match_name)
