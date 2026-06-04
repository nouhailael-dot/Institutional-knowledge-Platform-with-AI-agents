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
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


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
    estimated_trl: Mapped[Optional[int]] = mapped_column(SmallInteger)
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
    location: Mapped[Optional[str]] = mapped_column(String(255))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    recurring_pattern: Mapped[Optional[str]] = mapped_column(String(60))
    next_date: Mapped[Optional[datetime]] = mapped_column(Date)
    sponsoring_orgs: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# STRATEGIC ALIGNMENT ENTITIES
# ============================================================

class StrategicDocument(Base):
    """Uploaded OCP, UM6P, GHUS strategy documents. Powers RAG (Phase 2 brief, capability C)."""
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
    why_relevant: Mapped[Optional[str]] = mapped_column(Text)
    current_evidence: Mapped[Optional[str]] = mapped_column(Text)
    additional_validation_needed: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source.source_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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