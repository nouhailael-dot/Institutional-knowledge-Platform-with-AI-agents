"""The versioned mapping between Data Feed template columns and the V2 schema.

One ``Field`` per template column: its exact header, the canonical key it is
staged under, whether it is required, its controlled vocabulary, and where an
admitted record keeps it (``target``). The templates, the parser, the
validator, the manual forms and the Field Guide are all made from this list,
so a column cannot mean one thing in the spreadsheet and another on the form.

Only user-editable import fields are here. Database ids, audit timestamps, fact
pointers, verification events, run ids and status are never columns: the
system sets them, and a record always starts waiting for Review.

Changing a column changes ``TEMPLATE_VERSION``; files made from an older
version are refused with a message to download the current template.
"""

from __future__ import annotations

from dataclasses import dataclass

TEMPLATE_VERSION = "2026-10-26.3"
RECORD_TYPES = ("actor", "person", "event")
TYPE_LABELS = {"actor": "Actors / Organizations", "person": "People", "event": "Events"}
SHEET_NAMES = {"actor": "Actors", "person": "People", "event": "Events"}
FILE_STEMS = {"actor": "GHUS_Actors_Template", "person": "GHUS_People_Template",
              "event": "GHUS_Events_Template"}
REQUIRED_MARK = " *"
LIST_SEPARATOR = ";"
EXAMPLE_PREFIX = "EXAMPLE"


@dataclass(frozen=True)
class Field:
    key: str
    header: str
    kind: str                      # text, long_text, url, date, enum, multi_enum, list
    description: str
    example: str = ""
    required: bool = False
    vocab: str | None = None       # a list in reference.vocabularies()
    max_length: int | None = 255
    target: str = ""               # where an admitted record keeps it
    category: str | None = None    # actor Light Pull box for one category only
    strict: bool = True            # dropdown refuses other values

    @property
    def template_header(self) -> str:
        return self.header + (REQUIRED_MARK if self.required else "")


def _box(key, header, category, description, example="", kind="text"):
    """One category-specific Light Pull box (Architecture V2 section 5.2)."""
    return Field(key, header, kind, description, example, category=category, max_length=1000,
                 target=f"actor_fact (Light Pull, layer 1): {key}")


ACTOR_FIELDS: tuple[Field, ...] = (
    Field("name", "Official name", "text", "The organization's official name, as it writes it.",
          "Prairie Water Lab", required=True, target="actor.name"),
    Field("alternate_names", "Other names", "list",
          "Former names or abbreviations, separated by ';'.", "PWL; Prairie Water Laboratory",
          max_length=1000, target="actor.alt_names"),
    Field("website", "Website", "url", "Its official website (https://...).",
          "https://prairiewaterlab.org", max_length=500, target="actor.website"),
    Field("actor_category", "Actor Category", "enum",
          "What the organization IS (one of the 12 GHUS categories) - never its sector.",
          "Company / Corporate Actor", required=True, vocab="actor_categories",
          target="actor.actor_category"),
    Field("category_type", "Category Type", "enum",
          "Which kind of that category. Leave empty when unknown: it stays Pending "
          "Classification for enrichment. 'Not Applicable' needs a Category note.",
          "Small / Mid-Size Company", vocab="category_types", target="actor.category_type"),
    Field("category_note", "Category note", "text",
          "One line explaining a doubt about the category or type.", "", max_length=500,
          target="actor.category_note"),
    Field("description", "Description", "long_text",
          "1-3 plain, factual sentences: what it is and what it mainly does. Review's "
          "classification check reads it as the evidence of the organization's main job.",
          "A company that builds low-cost water-quality sensors for farms.", required=True,
          max_length=1000, target="actor.description; classification evidence (main job)"),
    Field("primary_sector", "Sector", "enum", "The GHUS sector it was added for.", "Water",
          required=True, vocab="sectors", target="actor_sector (primary)"),
    Field("topic", "Topic", "enum",
          "The controlled topic its facts are kept under. Empty: the sector's own topic.",
          "Water", vocab="topics", target="actor_topic / fact topic"),
    Field("additional_sectors", "Additional sectors", "multi_enum",
          "Other sectors it also fits, separated by ';'.", "Agriculture", vocab="sectors",
          max_length=200, target="actor_sector"),
    Field("city", "City", "text", "City of its headquarters or this location.", "Wichita",
          max_length=120, target="actor.city"),
    Field("state_code", "State", "enum", "US state (name or two-letter code).", "Kansas",
          vocab="states", target="actor.state_code"),
    Field("region", "Region", "enum",
          "Set automatically from the state. Leave empty; if filled it must match the state.",
          "", vocab="regions", target="actor.region_code (derived)"),
    Field("country", "Country", "enum", "Country. Use 'United States' for US organizations.",
          "United States", vocab="countries", strict=False, max_length=80,
          target="actor.country"),
    Field("parent_name", "Parent organization", "text",
          "The organization it belongs to, if any: its exact name or website on the map.",
          "", max_length=255, target="entity_edge (unit_of / operated_by)"),
    Field("parent_relationship", "Relationship to parent", "enum",
          "How it belongs to the parent. Required when a parent is given.", "",
          vocab="parent_links", target="entity_edge.relationship_type"),
    Field("source_url", "Source URL", "url",
          "Where this information can be checked. A Website or a Source URL is required.",
          "https://prairiewaterlab.org/about", max_length=1000, target="source.url"),
    Field("recent_activity", "Recent activity", "long_text",
          "One dated, documented project or development (give its date in the next column).",
          "Opened a sensor pilot with Kansas State University.", max_length=1000,
          target="actor_fact (Light Pull): recent_activity"),
    Field("recent_activity_date", "Recent activity date", "date",
          "The date of that activity (MM/DD/YYYY).", "05/14/2026", max_length=None,
          target="actor_fact (Light Pull): recent_activity"),
    Field("funding_signal", "Funding signal", "long_text",
          "One documented grant, award or investment.", "USDA SBIR Phase I, 2025",
          max_length=1000, target="actor_fact (Light Pull): funding_signal"),
    Field("international_connection", "International connection", "long_text",
          "A documented programme, office or partner outside the United States.", "",
          max_length=1000, target="actor_fact (Light Pull): international_connection"),
    Field("um6p_ocp_connection", "UM6P/OCP connection", "long_text",
          "A documented link with UM6P, OCP Group or INNOVX, with its source.", "",
          max_length=1000, target="actor_fact (Light Pull): um6p_ocp_connection"),
    # Category-specific Light Pull boxes. Rankings and a startup's stage or TRL
    # need structured, published evidence and are left to the Light Pull reader.
    _box("topic_unit_and_work", "University: unit and its work on the topic",
         "university_academic", "The school, department or centre working on the topic."),
    _box("institution_control", "University: public or private", "university_academic",
         "Public or private, as it states it.", "Public"),
    _box("land_grant_designation", "University: land-grant designation",
         "university_academic", "Whether it states it is a land-grant institution."),
    _box("relevant_centers_programs", "University: relevant centres and programmes",
         "university_academic", "Named centres or programmes on the topic."),
    _box("parent_and_center_type", "Research centre: parent and type", "research_center",
         "Its parent institution and the kind of centre."),
    _box("topic_research_focus", "Research centre: research focus", "research_center",
         "What it researches on the topic."),
    _box("active_recent_projects", "Research centre: active projects", "research_center",
         "Named current or recent projects."),
    _box("main_funders", "Research centre: main funders", "research_center",
         "Funders it names."),
    _box("sponsoring_agency", "National lab: sponsoring agency", "national_laboratory",
         "The federal agency that sponsors it.", "DOE"),
    _box("formal_national_designation", "National lab: formal designation",
         "national_laboratory", "Its formal designation (e.g. 'DOE national laboratory')."),
    _box("topic_program_area", "National lab: programme area", "national_laboratory",
         "Its programme area on the topic."),
    _box("facility_type_operator", "Facility: type and operator", "applied_facility",
         "What kind of facility and who operates it."),
    _box("testing_demonstration_scope", "Facility: what it tests", "applied_facility",
         "What can be tested or demonstrated there."),
    _box("current_project", "Facility: current project", "applied_facility",
         "A named current project."),
    _box("clinical_research_focus", "Hospital: clinical research focus",
         "hospital_clinical", "Its clinical research focus."),
    _box("parent_academic_link", "Hospital: parent or academic link", "hospital_clinical",
         "Its parent health system or academic link."),
    _box("hospital_type_scale", "Hospital: type and scale", "hospital_clinical",
         "Hospital type and stated scale (beds, sites, patients)."),
    _box("current_initiative", "Hospital: current initiative", "hospital_clinical",
         "A named current initiative."),
    _box("ownership_and_size", "Company: ownership and size", "company",
         "Ownership (public, private, subsidiary of ...) and stated size."),
    _box("topic_business_segment_product", "Company: segment or product on the topic",
         "company", "Its business segment or product on the topic."),
    _box("mapped_geography_operations", "Company: where it operates in the US", "company",
         "Where it operates in the US, as stated."),
    Field("development_stage", "Startup: development stage", "text",
          "Required for a startup: its development stage exactly as it publishes it "
          "(e.g. 'pilot deployments with two utilities'). Never estimated.", "",
          category="startup", max_length=300, target="classification evidence (startup)"),
    _box("technology_and_problem", "Startup: technology and problem", "startup",
         "Its technology and the problem it addresses."),
    _box("founding_year_location", "Startup: founded (year and place)", "startup",
         "Founding year and place, as stated.", "2021, Lawrence KS"),
    _box("funding_stage", "Startup: funding stage", "startup",
         "Its funding stage or latest round, as stated.", "Seed"),
    _box("pilot_customer_evidence", "Startup: pilot or customer", "startup",
         "A named pilot, customer or deployment."),
    _box("platform_type_operator", "Platform: type and operator", "innovation_platform",
         "What kind of platform it is and who runs it."),
    _box("sector_focus", "Platform: sector focus", "innovation_platform",
         "The sectors it focuses on."),
    _box("platform_offerings", "Platform: offerings", "innovation_platform",
         "What it offers participants."),
    _box("scale_indicator", "Platform: scale", "innovation_platform",
         "A stated figure for its scale (startups supported, members...)."),
    _box("investor_type_headquarters", "Investor: type and headquarters", "investor",
         "Investor type and headquarters."),
    _box("sector_stage_focus", "Investor: sector and stage focus", "investor",
         "The sectors and stages it invests in."),
    _box("geographic_focus", "Investor or foundation: geographic focus", "investor",
         "Where it works or invests, as stated."),
    _box("published_fund_size", "Investor: published fund size", "investor",
         "A fund size it publishes."),
    _box("topic_investment_thesis", "Investor: thesis on the topic", "investor",
         "Its investment thesis on the topic."),
    _box("jurisdiction_parent_agency", "Government: jurisdiction and parent agency",
         "government", "Its jurisdiction and parent agency."),
    _box("topic_mandate_program", "Government: mandate or programme", "government",
         "Its mandate or programme on the topic."),
    _box("visible_funding_programs", "Government: funding programmes", "government",
         "Funding programmes it lists (grants, rebates, loans)."),
    _box("mission_sector_focus", "Foundation: mission and focus", "foundation_nonprofit",
         "Its mission and sector focus."),
    _box("relevant_program", "Foundation: relevant programme", "foundation_nonprofit",
         "A named programme relevant to the topic."),
    _box("programs_grant_themes", "Foundation: programme or grant themes",
         "foundation_nonprofit", "Its programme or grant themes."),
    _box("association_type", "Association: type", "association_network",
         "What kind of association or network it is."),
    _box("sector_geographic_scope", "Association: sector and geographic scope",
         "association_network", "The sectors and geography it covers."),
    _box("member_types", "Association: member types", "association_network",
         "The kinds of members it has."),
    _box("current_initiative_working_group", "Association: current initiative",
         "association_network", "A named current initiative or working group."),
    _box("linked_members", "Association: named members", "association_network",
         "Members it names."),
    _box("network_scope_locations", "Association: locations or chapters",
         "association_network", "Locations or chapters of the network."),
)
# geographic_focus is a box for both investors and foundations.
BOX_CATEGORIES = {"geographic_focus": ("investor", "foundation_nonprofit")}

PERSON_FIELDS: tuple[Field, ...] = (
    Field("name", "Full name", "text", "The person's full name.", "Ana Ruiz", required=True,
          target="person.full_name"),
    Field("role", "Professional title", "text", "Their current professional title.",
          "Professor of Hydrology", target="person.title"),
    Field("affiliation", "Organization", "text",
          "The institution they work for, by its full name. Never a department or a role.",
          "University of Arizona", required=True, target="actor_person (affiliation)"),
    Field("department", "Department", "text", "Department, lab, school or unit.",
          "Department of Hydrology and Atmospheric Sciences", target="Review profile fact"),
    Field("bio_url", "Official biography URL", "url",
          "Their profile page on the organization's own site.",
          "https://www.arizona.edu/people/ana-ruiz", max_length=500,
          target="person_discovery_profile.public_profile_url"),
    Field("linkedin_url", "Public LinkedIn URL", "url", "Their public LinkedIn profile.",
          "https://www.linkedin.com/in/ana-ruiz", max_length=500, target="person.linkedin_url"),
    Field("bio", "Short professional bio", "long_text",
          "Up to three sentences of professional biography. Never private details.",
          "Hydrologist working on groundwater recharge in arid regions.", max_length=800,
          target="Review profile fact"),
    Field("expertise", "Expertise", "list", "Research areas or specialisms, separated by ';'.",
          "groundwater; aquifer recharge", max_length=500,
          target="person_discovery_profile.research_area"),
    Field("city", "City", "text", "Where they work (office or campus city).", "Tucson",
          max_length=120, target="Review profile fact (work location)"),
    Field("state_code", "State", "enum", "US state of their workplace.", "Arizona",
          vocab="states", target="Review profile fact (work location)"),
    Field("country", "Country", "enum", "Country of their workplace.", "United States",
          vocab="countries", strict=False, max_length=80, target="Review profile fact"),
    Field("sectors", "Sector", "multi_enum", "GHUS sectors of their work, separated by ';'.",
          "Water", vocab="sectors", max_length=200, target="staged_record.sector_codes"),
    Field("topic", "Topic", "enum", "The controlled topic of their expertise.", "Water",
          vocab="topics", target="person_topic (after review)"),
    Field("source_url", "Source URL", "url",
          "Where this information can be checked. A Source URL, a biography URL or a "
          "LinkedIn URL is required.", "https://www.arizona.edu/people/ana-ruiz",
          max_length=1000, target="source.url"),
)

EVENT_FIELDS: tuple[Field, ...] = (
    Field("name", "Event name", "text", "The event's official name.",
          "Great Plains Water Summit 2027", required=True, target="event.name"),
    Field("event_type", "Event type", "enum", "What kind of event it is.", "Summit",
          required=True, vocab="event_types", target="event.event_type"),
    Field("organizer", "Organizer", "text",
          "Who organizes it, as stated. Leave empty when no host is confirmed.",
          "Kansas Water Office", target="event.sponsoring_orgs"),
    Field("start_date", "Start date", "date", "First day (MM/DD/YYYY).", "04/02/2027",
          required=True, max_length=None, target="event.start_date"),
    Field("end_date", "End date", "date", "Last day (MM/DD/YYYY); empty for one day.",
          "04/03/2027", max_length=None, target="event.end_date"),
    Field("event_format", "Format", "enum", "In person, online or hybrid.", "Hybrid",
          vocab="event_formats", target="event.location / Review"),
    Field("venue", "Venue", "text", "Venue name, if any.", "Century II Convention Hall",
          max_length=200, target="event.location"),
    Field("city", "City", "text", "City where it takes place.", "Wichita", max_length=120,
          target="event.location"),
    Field("state_code", "State", "enum", "US state where it takes place.", "Kansas",
          vocab="states", target="event.location"),
    Field("country", "Country", "enum", "Country where it takes place.", "United States",
          vocab="countries", strict=False, max_length=80, target="event.location"),
    Field("sectors", "Sector", "multi_enum", "GHUS sectors it covers, separated by ';'.",
          "Water; Agriculture", vocab="sectors", max_length=200,
          target="staged_record.sector_codes"),
    Field("topic", "Topic", "enum", "The controlled topic it was added for.", "Water",
          vocab="topics", target="event_topic (after review)"),
    Field("themes", "Themes", "text", "Relevant themes or sessions, as stated.",
          "groundwater policy; irrigation technology", max_length=500,
          target="event.thematic_focus"),
    Field("description", "Description", "long_text", "A short factual description.",
          "A two-day summit on water management in the Great Plains.", max_length=1000,
          target="event.description"),
    Field("website", "Official event URL", "url", "The event's own page.",
          "https://greatplainswatersummit.org", max_length=500, target="event.website"),
    Field("registration_url", "Registration URL", "url", "Where to register.", "",
          max_length=500, target="Review (kept with the record)"),
    Field("recurring_pattern", "Frequency", "enum", "How often it takes place: annual, "
          "recurring or one-time.",
          "Annual", vocab="recurrence", target="event.recurring_pattern"),
    Field("expected_attendance", "Expected attendance", "text",
          "Attendance as the organizer states it.", "About 400", max_length=120,
          target="event.expected_attendance"),
    Field("source_url", "Source URL", "url",
          "Where this can be checked. An Official event URL or a Source URL is required.",
          "https://greatplainswatersummit.org/agenda", max_length=1000, target="source.url"),
)

FIELDS = {"actor": ACTOR_FIELDS, "person": PERSON_FIELDS, "event": EVENT_FIELDS}


def fields(record_type: str) -> tuple[Field, ...]:
    if record_type not in FIELDS:
        raise ValueError(f"unknown record type {record_type!r}")
    return FIELDS[record_type]


def header_key(header: object) -> str:
    """A header as the parser compares it: no required mark, case or spacing."""
    text_ = " ".join(str(header or "").replace("*", " ").split())
    return text_.casefold()


def by_header(record_type: str) -> dict[str, Field]:
    return {header_key(f.header): f for f in fields(record_type)}


def box_categories(field: Field) -> tuple[str, ...]:
    return BOX_CATEGORIES.get(field.key, (field.category,) if field.category else ())


def as_payload() -> dict:
    """The contract for the page: one entry per column, in template order."""
    return {
        "template_version": TEMPLATE_VERSION,
        "types": {
            record_type: {
                "label": TYPE_LABELS[record_type],
                "fields": [{
                    "key": f.key, "header": f.header, "kind": f.kind, "required": f.required,
                    "vocab": f.vocab, "description": f.description, "example": f.example,
                    "max_length": f.max_length, "target": f.target,
                    "categories": list(box_categories(f)), "strict": f.strict,
                } for f in fields(record_type)],
            } for record_type in RECORD_TYPES
        },
    }
