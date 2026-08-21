"""
SQLAlchemy ORM models for the GHUS Ecosystem Intelligence Platform.

Mirrors the schema documented in docs/architecture/entity-model-v1.md and the
diagram in docs/architecture/entity-model-v1.png.

Conventions:
- Every entity table has a UUID primary key, plus provenance fields.
- Every entity table has created_at and updated_at timestamps.
- Foreign keys are typed as Mapped[uuid.UUID] for clarity.
- Junction tables use composite primary keys.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from src.db.base import Base


class Vector(UserDefinedType):
    """Minimal pgvector column type for ORM metadata parity."""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "vector"


class TSVector(UserDefinedType):
    """PostgreSQL tsvector column type used by derived search tables."""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "tsvector"


# ============================================================
# SUPPORTING / REFERENCE TABLES
# ============================================================

class Source(Base):
    """Provenance for every fact in the database."""
    __tablename__ = "source"

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000))
    retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    description: Mapped[Optional[str]] = mapped_column(Text)
    trust_tier: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FundingSource(Base):
    """Reference table for funding origins (USDA, NSF, etc.)."""
    __tablename__ = "funding_source"

    funding_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(40))
    description: Mapped[Optional[str]] = mapped_column(Text)


class Sector(Base):
    """Controlled vocabulary of priority sectors."""
    __tablename__ = "sector"

    sector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    parent_sector_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("sector.sector_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# CORE ECOSYSTEM ENTITIES
# ============================================================

class Hub(Base):
    """A geographic ecosystem (e.g., UC Davis / Sacramento Valley).
    First-class entity per Phase 2 brief."""
    __tablename__ = "hub"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    primary_city: Mapped[Optional[str]] = mapped_column(String(120))
    state: Mapped[Optional[str]] = mapped_column(String(80))
    country: Mapped[Optional[str]] = mapped_column(String(80), default="USA")
    region: Mapped[Optional[str]] = mapped_column(String(120))
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6))
    description: Mapped[Optional[str]] = mapped_column(Text)
    official_websites: Mapped[Optional[str]] = mapped_column(Text)
    strategic_value_summary: Mapped[Optional[str]] = mapped_column(Text)
    core_topic_strengths: Mapped[Optional[str]] = mapped_column(Text)
    composition_narrative: Mapped[Optional[str]] = mapped_column(Text)
    programs_and_labs_narrative: Mapped[Optional[str]] = mapped_column(Text)
    talent_narrative: Mapped[Optional[str]] = mapped_column(Text)
    research_infrastructure_narrative: Mapped[Optional[str]] = mapped_column(Text)
    industry_integration_narrative: Mapped[Optional[str]] = mapped_column(Text)
    international_engagement_narrative: Mapped[Optional[str]] = mapped_column(Text)
    upstream_inputs: Mapped[Optional[str]] = mapped_column(Text)
    downstream_outputs: Mapped[Optional[str]] = mapped_column(Text)
    integrated_flow_description: Mapped[Optional[str]] = mapped_column(Text)
    constraints_summary: Mapped[Optional[str]] = mapped_column(Text)
    funding_summary: Mapped[Optional[str]] = mapped_column(Text)
    cross_hub_themes: Mapped[Optional[str]] = mapped_column(Text)
    primary_sectors: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(20)))
    secondary_sectors: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(20)))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Actor(Base):
    """Organizations operating within hubs."""
    __tablename__ = "actor"

    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(160), unique=True)
    actor_type: Mapped[Optional[str]] = mapped_column(String(40))
    actor_type_raw: Mapped[Optional[str]] = mapped_column(String(255))  # preserves free-text original
    description: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(String(500))
    location_city: Mapped[Optional[str]] = mapped_column(String(120))
    state: Mapped[Optional[str]] = mapped_column(String(80))
    country: Mapped[Optional[str]] = mapped_column(String(80))
    primary_technical_focus: Mapped[Optional[str]] = mapped_column(Text)
    technical_approach: Mapped[Optional[str]] = mapped_column(Text)
    current_activities: Mapped[Optional[str]] = mapped_column(Text)
    technology_ip_notes: Mapped[Optional[str]] = mapped_column(Text)
    key_constraints: Mapped[Optional[str]] = mapped_column(Text)
    funding_summary: Mapped[Optional[str]] = mapped_column(Text)
    estimated_trl: Mapped[Optional[int]] = mapped_column(SmallInteger)
    merged_into_actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("actor.actor_id"), nullable=True)
    primary_lifecycle_role: Mapped[Optional[str]] = mapped_column(String(30))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Person(Base):
    """Researchers, faculty, founders, program directors."""
    __tablename__ = "person"

    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    orcid: Mapped[Optional[str]] = mapped_column(String(30))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    tel_num: Mapped[Optional[str]] = mapped_column(String(50))
    country_code: Mapped[Optional[str]] = mapped_column(String(5))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Event(Base):
    """Industry conferences, academic summits, ecosystem events."""
    __tablename__ = "event"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[Optional[str]] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    thematic_focus: Mapped[Optional[str]] = mapped_column(Text)
    expected_attendance: Mapped[Optional[str]] = mapped_column(String(120))
    access_type: Mapped[Optional[str]] = mapped_column(String(120))
    recurring_pattern: Mapped[Optional[str]] = mapped_column(String(60))
    next_date: Mapped[Optional[datetime]] = mapped_column(Date)
    sponsoring_orgs: Mapped[Optional[str]] = mapped_column(Text)
    host_actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id")
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# STRATEGIC ALIGNMENT ENTITIES
# ============================================================

class StrategicDocument(Base):
    """Uploaded OCP, UM6P, GHUS strategy documents. Powers RAG."""
    __tablename__ = "strategic_document"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_organization: Mapped[Optional[str]] = mapped_column(String(60))
    document_type: Mapped[Optional[str]] = mapped_column(String(60))
    upload_date: Mapped[Optional[datetime]] = mapped_column(Date)
    full_text: Mapped[Optional[str]] = mapped_column(Text)
    extracted_themes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(200)))
    storage_uri: Mapped[Optional[str]] = mapped_column(String(500))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Challenge(Base):
    """A specific OCP/UM6P priority being matched against the ecosystem.
    NutriCrops is the first instance."""
    __tablename__ = "challenge"

    challenge_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    sponsoring_org: Mapped[Optional[str]] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    target_sectors: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(20)))
    target_technologies: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(200)))
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("strategic_document.document_id"))
    created_date: Mapped[Optional[datetime]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ActorRelevance(Base):
    """One row per (actor, challenge) evaluation. The heart of NutriCrops-style sheets."""
    __tablename__ = "actor_relevance"
    __table_args__ = (
        UniqueConstraint("actor_id", "challenge_id", name="uq_actor_challenge"),
    )

    actor_relevance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    challenge_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("challenge.challenge_id"), nullable=False)
    relevance_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    maturity_risk: Mapped[Optional[str]] = mapped_column(String(40))
    collaboration_orientation: Mapped[Optional[str]] = mapped_column(String(60))
    challenge_relevance_narrative: Mapped[Optional[str]] = mapped_column(Text)
    why_relevant: Mapped[Optional[str]] = mapped_column(Text)
    current_evidence: Mapped[Optional[str]] = mapped_column(Text)
    source_links: Mapped[Optional[str]] = mapped_column(Text)
    additional_validation_needed: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# ACTOR PROFILE / FACT / EVALUATION SIDECARS
# ============================================================

class ActorProfile(Base):
    """One canonical, actor-level profile assembled from existing actor fields.

    This sidecar keeps richer profile summaries queryable without removing the
    legacy narrative columns already present on actor.
    """
    __tablename__ = "actor_profile"

    actor_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), unique=True, nullable=False
    )
    profile_summary: Mapped[Optional[str]] = mapped_column(Text)
    identity_summary: Mapped[Optional[str]] = mapped_column(Text)
    technical_summary: Mapped[Optional[str]] = mapped_column(Text)
    funding_summary: Mapped[Optional[str]] = mapped_column(Text)
    lifecycle_summary: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    generated_by: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ActorCapabilityFact(Base):
    """Atomic actor capability/funding/activity facts backfilled from actor text.

    The legacy actor columns stay in place; this table gives the same content a
    cleaner fact-level shape for filtering, review, and future enrichment.
    """
    __tablename__ = "actor_capability_fact"
    __table_args__ = (
        UniqueConstraint("actor_id", "fact_type", "source_field", name="uq_actor_capability_fact"),
    )

    actor_capability_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_field: Mapped[str] = mapped_column(String(80), nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    evidence_url: Mapped[Optional[str]] = mapped_column(Text)
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    generated_by: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ActorEvaluation(Base):
    """Context-specific actor evaluations.

    This generalizes challenge relevance and partnership value without removing
    actor_relevance or partnership_profile.
    """
    __tablename__ = "actor_evaluation"
    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "evaluation_context",
            "context_entity_type",
            "context_entity_id",
            name="uq_actor_evaluation_context",
        ),
    )

    actor_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    evaluation_context: Mapped[str] = mapped_column(String(120), nullable=False)
    context_entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    context_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(5, 3))
    evaluation_summary: Mapped[Optional[str]] = mapped_column(Text)
    evidence_summary: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    generated_by: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ============================================================
# JUNCTION TABLES
# ============================================================

class HubActor(Base):
    """Many-to-many: actors can belong to multiple hubs."""
    __tablename__ = "hub_actor"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hub.hub_id"), primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True)
    relationship_type: Mapped[Optional[str]] = mapped_column(String(30))
    is_primary: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ActorSector(Base):
    """Tags actors with the sectors they operate in."""
    __tablename__ = "actor_sector"

    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True)
    sector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sector.sector_id"), primary_key=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))


class ActorPerson(Base):
    """Affiliations between people and organizations."""
    __tablename__ = "actor_person"

    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("person.person_id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(120), primary_key=True)
    is_current: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(Date)
    end_date: Mapped[Optional[datetime]] = mapped_column(Date)


class EventSector(Base):
    """Tags events with the sectors they cover."""
    __tablename__ = "event_sector"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("event.event_id"), primary_key=True)
    sector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sector.sector_id"), primary_key=True)


class HubFunding(Base):
    """Funding source connections for hubs."""
    __tablename__ = "hub_funding"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hub.hub_id"), primary_key=True)
    funding_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funding_source.funding_source_id"), primary_key=True)
    narrative: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))


# ============================================================
# PRECOMPUTED / DERIVED TABLES
# ============================================================

class HubSectorStrength(Base):
    """Precomputed nightly. Powers 'which hubs are strongest for X' queries instantly."""
    __tablename__ = "hub_sector_strength"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hub.hub_id"), primary_key=True)
    sector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sector.sector_id"), primary_key=True)
    strength_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    actor_count: Mapped[Optional[int]] = mapped_column(Integer)
    top_actor_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    narrative_summary: Mapped[Optional[str]] = mapped_column(Text)
    last_computed: Mapped[Optional[datetime]] = mapped_column(DateTime)


class SearchDoc(Base):
    """Derived search document table for full-text and vector retrieval."""
    __tablename__ = "search_doc"

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    entity_type: Mapped[Optional[str]] = mapped_column(Text)
    name: Mapped[Optional[str]] = mapped_column(Text)
    doc_text: Mapped[Optional[str]] = mapped_column(Text)
    embedding: Mapped[Optional[str]] = mapped_column(Vector())
    doc_tsv: Mapped[Optional[str]] = mapped_column(
        TSVector(),
        Computed("to_tsvector('english'::regconfig, COALESCE(doc_text, ''::text))"),
    )


class SearchDoc2(Base):
    """Current richer search document table used by the app."""
    __tablename__ = "search_doc_2"

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(Text)
    doc_text: Mapped[Optional[str]] = mapped_column(Text)
    embedding: Mapped[Optional[str]] = mapped_column(Vector())
    website: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[str]] = mapped_column(Text)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    doc_tsv: Mapped[Optional[str]] = mapped_column(
        TSVector(),
        Computed(
            "(setweight(to_tsvector('simple'::regconfig, COALESCE(name, ''::text)), 'A'::char) || "
            "setweight(to_tsvector('english'::regconfig, COALESCE(name, ''::text)), 'A'::char)) || "
            "setweight(to_tsvector('english'::regconfig, COALESCE(doc_text, ''::text)), 'B'::char)"
        ),
    )


# ============================================================
# INSTITUTIONAL PARTNER EXTENSIONS
# Added for UN Mapping and future partner-organization spreadsheets.
# ============================================================

class OrganizationHierarchy(Base):
    """Parent-child relationships between actors. Supports nested institutional
    structures like UN General Assembly -> Funds and Programmes -> UNDP."""
    __tablename__ = "organization_hierarchy"

    parent_actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True
    )
    child_actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True
    )
    relationship_type: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PartnershipProfile(Base):
    """Partnership-evaluation sidecar for institutional actors.
    1:1 with actor. Holds the rich partnership-relevant fields that apply
    to UN agencies, federal agencies, foundations — but not to technical
    actors like university labs or startups."""
    __tablename__ = "partnership_profile"

    partnership_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), unique=True, nullable=False
    )
    thematic_focus: Mapped[Optional[str]] = mapped_column(Text)
    strategic_plan: Mapped[Optional[str]] = mapped_column(Text)
    africa_specific_mandate: Mapped[Optional[str]] = mapped_column(Text)
    africa_specific_details: Mapped[Optional[str]] = mapped_column(Text)
    why_valuable_for_um6p: Mapped[Optional[str]] = mapped_column(Text)
    budget_overview: Mapped[Optional[str]] = mapped_column(Text)
    partners_with_universities: Mapped[Optional[bool]] = mapped_column(Boolean)
    university_programmes: Mapped[Optional[str]] = mapped_column(Text)
    university_partnership_examples: Mapped[Optional[str]] = mapped_column(Text)
    key_entry_points: Mapped[Optional[str]] = mapped_column(Text)
    funding_delivery: Mapped[Optional[bool]] = mapped_column(Boolean)
    funding_delivery_mechanisms: Mapped[Optional[str]] = mapped_column(Text)
    key_constraints: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id")
    )
    verification_status: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class EventScoring(Base):
    """Strategic scoring sidecar for events.
    1:1 with event. Same pattern as partnership_profile for actors.
    Captures the 6-criterion scoring methodology from UM6P Dashboard v8."""
    __tablename__ = "event_scoring"

    event_scoring_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event.event_id"), unique=True, nullable=False
    )
    longevity_description: Mapped[Optional[str]] = mapped_column(Text)
    recognition_description: Mapped[Optional[str]] = mapped_column(Text)
    scale_description: Mapped[Optional[str]] = mapped_column(Text)
    audience_profile_description: Mapped[Optional[str]] = mapped_column(Text)
    organizer_credibility_description: Mapped[Optional[str]] = mapped_column(Text)
    geographic_reach_description: Mapped[Optional[str]] = mapped_column(Text)
    longevity_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    recognition_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    scale_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    audience_profile_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    organizer_profile_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    geographic_reach_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    total_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    tier: Mapped[Optional[str]] = mapped_column(String(20))
    tier_raw: Mapped[Optional[str]] = mapped_column(String(120))
    scoring_methodology_version: Mapped[Optional[str]] = mapped_column(String(20))
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id")
    )
    scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ActorMergeLog(Base):
    """Audit + reversibility for actor merges."""
    __tablename__ = "actor_merge_log"

    merge_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    winner_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    loser_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_by: Mapped[Optional[str]] = mapped_column(String(120))
    decided_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    pre_merge_state: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), server_default="applied", nullable=False)
    reverted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReviewQueue(Base):
    """Human-in-the-loop entity resolution review queue."""
    __tablename__ = "review_queue"
    __table_args__ = (
        UniqueConstraint("actor_id_a", "actor_id_b", name="uq_review_pair"),
    )

    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id_a: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    actor_id_b: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    model: Mapped[Optional[str]] = mapped_column(String(60))
    features: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), server_default="pending", nullable=False)
    decided_by: Mapped[Optional[str]] = mapped_column(String(120))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    merge_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("actor_merge_log.merge_id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Proposal(Base):
    """Pending field-level change proposals surfaced for review."""
    __tablename__ = "proposal"

    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[Optional[str]] = mapped_column(Text)
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QueryLog(Base):
    """Application query telemetry."""
    __tablename__ = "query_log"

    query_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    question: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[Optional[str]] = mapped_column(Text)
    retrieved_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    found_by: Mapped[Optional[dict]] = mapped_column(JSONB)
    top_distance: Mapped[Optional[float]] = mapped_column(Float)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    answer: Mapped[Optional[str]] = mapped_column(Text)
    helpful: Mapped[Optional[bool]] = mapped_column(Boolean)
