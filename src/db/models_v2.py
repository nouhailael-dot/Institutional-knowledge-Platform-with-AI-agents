"""Architecture V2 ORM models.

The authoritative DDL remains the detached canonical proposals under
``migrations/proposed`` and platform SQL under ``agents/sql/190+``. This module
is imported only by tests and isolated database tooling until the rename phase.
Its metadata is intentionally separate from application/Alembic metadata.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class V2Base(DeclarativeBase):
    """Metadata isolated from the application's ``src.db.base.Base``."""


class ActorV2(V2Base):
    """Post-migration actor mapping used until the Phase 5 application cutover."""

    __tablename__ = "actor"

    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(Text)
    actor_category: Mapped[str | None] = mapped_column(Text)
    actor_type_raw: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    location_city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    primary_technical_focus: Mapped[str | None] = mapped_column(Text)
    technical_approach: Mapped[str | None] = mapped_column(Text)
    current_activities: Mapped[str | None] = mapped_column(Text)
    technology_ip_notes: Mapped[str | None] = mapped_column(Text)
    key_constraints: Mapped[str | None] = mapped_column(Text)
    funding_summary: Mapped[str | None] = mapped_column(Text)
    estimated_trl: Mapped[int | None] = mapped_column(Integer)
    merged_into_actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    primary_lifecycle_role: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    record_status: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    alternate_names: Mapped[list[str]] = mapped_column(ARRAY(Text))
    category_type: Mapped[str | None] = mapped_column(Text)
    category_note: Mapped[str | None] = mapped_column(Text)
    category_needs_review: Mapped[bool] = mapped_column(Boolean)
    website_domain: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    region_code: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    is_multi_location: Mapped[bool] = mapped_column(Boolean)
    source_origin: Mapped[str] = mapped_column(Text)
    ghus_notes: Mapped[str | None] = mapped_column(Text)


class PersonV2(V2Base):
    __tablename__ = "person"

    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    orcid: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    tel_num: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    record_status: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    source_origin: Mapped[str] = mapped_column(Text)


class EventV2(V2Base):
    __tablename__ = "event"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    thematic_focus: Mapped[str | None] = mapped_column(Text)
    expected_attendance: Mapped[str | None] = mapped_column(Text)
    access_type: Mapped[str | None] = mapped_column(Text)
    recurring_pattern: Mapped[str | None] = mapped_column(Text)
    next_date: Mapped[datetime | None] = mapped_column(Date)
    sponsoring_orgs: Mapped[str | None] = mapped_column(Text)
    host_actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    record_status: Mapped[str] = mapped_column(Text)
    source_origin: Mapped[str] = mapped_column(Text)
    date_status: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    ghus_notes: Mapped[str | None] = mapped_column(Text)


class HubV2(V2Base):
    __tablename__ = "hub"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    primary_city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    description: Mapped[str | None] = mapped_column(Text)
    official_websites: Mapped[str | None] = mapped_column(Text)
    strategic_value_summary: Mapped[str | None] = mapped_column(Text)
    core_topic_strengths: Mapped[str | None] = mapped_column(Text)
    composition_narrative: Mapped[str | None] = mapped_column(Text)
    programs_and_labs_narrative: Mapped[str | None] = mapped_column(Text)
    talent_narrative: Mapped[str | None] = mapped_column(Text)
    research_infrastructure_narrative: Mapped[str | None] = mapped_column(Text)
    industry_integration_narrative: Mapped[str | None] = mapped_column(Text)
    international_engagement_narrative: Mapped[str | None] = mapped_column(Text)
    upstream_inputs: Mapped[str | None] = mapped_column(Text)
    downstream_outputs: Mapped[str | None] = mapped_column(Text)
    integrated_flow_description: Mapped[str | None] = mapped_column(Text)
    constraints_summary: Mapped[str | None] = mapped_column(Text)
    funding_summary: Mapped[str | None] = mapped_column(Text)
    cross_hub_themes: Mapped[str | None] = mapped_column(Text)
    primary_sectors: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    secondary_sectors: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verification_status: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    center_city: Mapped[str | None] = mapped_column(Text)
    center_state_code: Mapped[str | None] = mapped_column(Text)
    center_latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    center_longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    radius_miles: Mapped[float] = mapped_column(Numeric(7, 2))
    center_frozen: Mapped[bool] = mapped_column(Boolean)
    center_method: Mapped[str] = mapped_column(Text)
    center_method_version: Mapped[str | None] = mapped_column(Text)
    center_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(Text)
    phase1_definition: Mapped[str | None] = mapped_column(Text)
    source_origin: Mapped[str] = mapped_column(Text)


class HubActorV2(V2Base):
    __tablename__ = "hub_actor"

    hub_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    relationship_type: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    distance_miles: Mapped[float | None] = mapped_column(Numeric(8, 2))
    assignment_outcome: Mapped[str] = mapped_column(Text)
    outside_radius: Mapped[bool] = mapped_column(Boolean)
    overlap_flag: Mapped[bool] = mapped_column(Boolean)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class HubAssignmentEvidence(V2Base):
    __tablename__ = "hub_assignment_evidence"

    hub_assignment_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False
    )
    hub_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hub.hub_id"), nullable=False
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    topic_matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    location_evaluated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    distance_miles: Mapped[float | None] = mapped_column(Numeric(8, 2))
    radius_miles: Mapped[float | None] = mapped_column(Numeric(7, 2))
    outside_radius: Mapped[bool] = mapped_column(Boolean, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActorCategoryDefinition(V2Base):
    __tablename__ = "actor_category_definition"

    category_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ActorCategoryTypeDefinition(V2Base):
    __tablename__ = "actor_category_type_definition"

    category_code: Mapped[str] = mapped_column(
        Text, ForeignKey("actor_category_definition.category_code"), primary_key=True
    )
    type_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    is_other: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RegionDefinition(V2Base):
    __tablename__ = "region_definition"

    region_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, unique=True)


class RegionState(V2Base):
    __tablename__ = "region_state"

    state_code: Mapped[str] = mapped_column(Text, primary_key=True)
    state_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    region_code: Mapped[str] = mapped_column(
        Text, ForeignKey("region_definition.region_code"), nullable=False
    )
    is_district: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UsCityCoord(V2Base):
    __tablename__ = "us_city_coord"

    geoid: Mapped[str] = mapped_column(Text, primary_key=True)
    state_code: Mapped[str] = mapped_column(
        Text, ForeignKey("region_state.state_code"), nullable=False
    )
    place_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_city: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    lsad: Mapped[str] = mapped_column(Text, nullable=False)
    function_status: Mapped[str] = mapped_column(Text, nullable=False)
    gazetteer_year: Mapped[int] = mapped_column(nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceOriginDefinition(V2Base):
    __tablename__ = "source_origin_definition"

    origin_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class Topic(V2Base):
    __tablename__ = "topic"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActorTopic(V2Base):
    __tablename__ = "actor_topic"

    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), primary_key=True
    )
    match_strength: Mapped[str] = mapped_column(Text, nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActorLocation(V2Base):
    __tablename__ = "actor_location"
    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "country",
            "state_code",
            "city",
            "location_name",
            name="actor_location_actor_id_country_state_code_city_location_name_key",
        ),
    )

    actor_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False
    )
    location_name: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    state_code: Mapped[str | None] = mapped_column(Text, ForeignKey("region_state.state_code"))
    city: Mapped[str] = mapped_column(Text, nullable=False)
    region_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("region_definition.region_code")
    )
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecordVerification(V2Base):
    __tablename__ = "record_verification"

    verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id")
    )


class ActorFact(V2Base):
    __tablename__ = "actor_fact"

    actor_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    fact_value: Mapped[dict | None] = mapped_column(JSONB)
    collection_state: Mapped[str] = mapped_column(Text, default="found", nullable=False)
    layer: Mapped[int] = mapped_column(nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    source_origin: Mapped[str] = mapped_column(
        Text, ForeignKey("source_origin_definition.origin_code"), nullable=False
    )
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    semantic_hash: Mapped[str | None] = mapped_column(Text)
    creator_class: Mapped[str | None] = mapped_column(Text)
    lifecycle_state: Mapped[str | None] = mapped_column(Text)
    supersedes_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor_fact.actor_fact_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActorFactCurrentPointer(V2Base):
    __tablename__ = "actor_fact_current_pointer"

    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id"), primary_key=True
    )
    fact_key: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor_fact.actor_fact_id"), nullable=False, unique=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FactCorroboration(V2Base):
    __tablename__ = "fact_corroboration"

    fact_corroboration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor_fact.actor_fact_id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FactResolution(V2Base):
    __tablename__ = "fact_resolution"

    fact_resolution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor_fact.actor_fact_id"), nullable=False
    )
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    related_actor_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor_fact.actor_fact_id")
    )
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntityEdge(V2Base):
    __tablename__ = "entity_edge"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "relationship_type",
            "object_type",
            "object_id",
            "topic_id",
            "source_id",
            name="entity_edge_subject_type_subject_id_relationship_type_obj_key",
        ),
    )

    entity_edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionRequest(V2Base):
    __tablename__ = "collection_request"

    collection_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    request_kind: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id")
    )
    need_text: Mapped[str | None] = mapped_column(Text)
    layer: Mapped[int] = mapped_column(nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionRun(V2Base):
    __tablename__ = "collection_run"

    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_request.collection_request_id"), nullable=False
    )
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="running", nullable=False)
    fetch_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    fetch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))
    spent_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_reason: Mapped[str | None] = mapped_column(Text)


class FetchedDocument(V2Base):
    __tablename__ = "fetched_document"
    __table_args__ = (
        UniqueConstraint(
            "collection_run_id",
            "canonical_url",
            "content_hash",
            name="fetched_document_collection_run_id_canonical_url_content_hash_key",
        ),
    )

    fetched_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_run.collection_run_id"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    page_role: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActorRanking(V2Base):
    __tablename__ = "actor_ranking"

    actor_ranking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False
    )
    context_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id")
    )
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    ranking_name: Mapped[str] = mapped_column(Text, nullable=False)
    ranking_year: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    ranked_entity_name: Mapped[str] = mapped_column(Text, nullable=False)
    position_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonTopic(V2Base):
    __tablename__ = "person_topic"

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.person_id"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), primary_key=True
    )
    expertise_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactCollectionAuthorization(V2Base):
    __tablename__ = "contact_collection_authorization"

    authorization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.person_id")
    )
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    official_public_only: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventTopic(V2Base):
    __tablename__ = "event_topic"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event.event_id"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), primary_key=True
    )
    why_matched: Mapped[str] = mapped_column(Text, nullable=False)
    collection_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_request.collection_request_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventClaim(V2Base):
    __tablename__ = "event_claim"

    event_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event.event_id"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StrategicEntity(V2Base):
    __tablename__ = "strategic_entity"

    strategic_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canonical_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    alternate_names: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    parent_strategic_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategic_entity.strategic_entity_id")
    )
    entity_group: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActorStrategicConnectionCheck(V2Base):
    __tablename__ = "actor_strategic_connection_check"

    connection_check_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    layer: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategic_entity.strategic_entity_id")
    )
    connection_kind: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id")
    )
    fetched_document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HubCenterReview(V2Base):
    __tablename__ = "hub_center_review"

    hub_center_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hub_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hub.hub_id"), nullable=False
    )
    proposed_city: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_state_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("region_state.state_code")
    )
    proposed_latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    proposed_longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    shift_miles: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    trigger_threshold_miles: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProposedHubV2(V2Base):
    __tablename__ = "proposed_hub"

    proposed_hub_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    primary_city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    source_table: Mapped[str] = mapped_column(Text, nullable=False)
    source_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    proposed_by: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    proposal_kind: Mapped[str] = mapped_column(Text, default="legacy_review", nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    center_latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    center_longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    radius_miles: Mapped[float | None] = mapped_column(Numeric(7, 2))
    core_radius_miles: Mapped[float | None] = mapped_column(Numeric(7, 2))
    independent_family_count: Mapped[int | None] = mapped_column(Integer)
    category_count: Mapped[int | None] = mapped_column(Integer)
    membership_fingerprint: Mapped[str | None] = mapped_column(Text)
    final_hub_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hub.hub_id")
    )
    detection_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hub_detection_run.hub_detection_run_id")
    )
    independence_statement: Mapped[str | None] = mapped_column(Text)
    detection_method_version: Mapped[str | None] = mapped_column(Text)
    fingerprint_version: Mapped[str | None] = mapped_column(Text)
    proposal_evidence: Mapped[dict | None] = mapped_column(JSONB)
    trigger_statuses: Mapped[list[str] | None] = mapped_column(JSONB)
    minimum_families_required: Mapped[int | None] = mapped_column(Integer)
    minimum_categories_required: Mapped[int | None] = mapped_column(Integer)


class ProposedHubMemberV2(V2Base):
    __tablename__ = "proposed_hub_member"

    proposed_hub_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_hub.proposed_hub_id"), primary_key=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), primary_key=True
    )
    family_root_actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor.actor_id"), nullable=False
    )
    distance_miles: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    actor_category: Mapped[str] = mapped_column(Text, nullable=False)
    category_type: Mapped[str | None] = mapped_column(Text)
    distance_miles_raw: Mapped[float | None] = mapped_column(Float)
    matched_category: Mapped[str | None] = mapped_column(Text)


class HubDetectionRunV2(V2Base):
    __tablename__ = "hub_detection_run"

    hub_detection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger_statuses: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    eligible_actor_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proposal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suppression_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposedHubDecisionV2(V2Base):
    __tablename__ = "proposed_hub_decision"

    proposed_hub_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    proposed_hub_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_hub.proposed_hub_id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    final_name: Mapped[str | None] = mapped_column(Text)
    final_radius_miles: Mapped[float | None] = mapped_column(Numeric(7, 2))
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewItem(V2Base):
    __tablename__ = "review_item"

    review_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    review_kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    candidate_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic.topic_id")
    )
    priority: Mapped[str] = mapped_column(Text, default="normal", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewItemDecision(V2Base):
    __tablename__ = "review_item_decision"

    review_item_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    review_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_item.review_item_id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CanonicalWriteAudit(V2Base):
    __tablename__ = "canonical_write_audit"

    canonical_write_audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    writer_module: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    collection_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_run.collection_run_id")
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    actor_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actor_fact.actor_fact_id")
    )
    entity_edge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entity_edge.entity_edge_id")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.source_id")
    )
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    performed_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
