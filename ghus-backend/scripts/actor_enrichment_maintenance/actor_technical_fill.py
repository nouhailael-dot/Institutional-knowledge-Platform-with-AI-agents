import argparse
import sys
from collections import Counter, defaultdict

from sqlalchemy import select, text

sys.path.insert(0, r"C:\Users\Ismail\Projects\GHUS-Platform")

from src.db.models import Actor, ActorSector, Hub, HubActor, Sector  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


TARGET_FIELDS = (
    "primary_technical_focus",
    "technical_approach",
    "current_activities",
    "technology_ip_notes",
    "key_constraints",
    "primary_lifecycle_role",
)


KEYWORDS = {
    "ai": (
        " ai ", "artificial intelligence", "machine learning", "robotics",
        "data science", "analytics", "autonomous", "aws", "software", "digital",
    ),
    "health": (
        "health", "medical", "medicine", "clinical", "hospital", "biomedical",
        "genomics", "cancer", "cardiovascular", "neuroscience",
        "precision medicine", "pharma", "therapeutic",
    ),
    "agriculture": (
        "agri", "crop", "farm", "fertilizer", "plant science", "soil",
        "dairy", "apple", "wine", "specialty crop", "food", "livestock",
        "nutrient",
    ),
    "water": (
        "water", "desalination", "groundwater", "aquifer", "irrigation",
        "freshwater", "hydrology", "water reuse", "wastewater",
    ),
    "materials": (
        "chemistry", "chemical", "catalysis", "polymer", "materials",
        "manufacturing", "formulation", "reaction engineering", "synchrotron",
    ),
    "mining": (
        "mining", "mine", "mineral", "rare earth", "critical mineral",
        "lithium", "copper", "zinc", "smelting", "metallurgy", "tailings",
        "geology", "ore", "phosphate",
    ),
    "energy": (
        "energy", "hydrogen", "battery", "storage", "solar", "wind", "grid",
        "ammonia", "lng", "fuel cell", "nuclear", "power",
    ),
    "climate": (
        "carbon", "climate", "sustainability", "green", "esg",
        "decarbonization", "ccus", "co2", "resilience",
    ),
    "waste": (
        "waste", "remediation", "reclamation", "radioactive", "radionuclide",
        "tenorm", "norm", "phosphogypsum", "pg ", "cleanup", "contaminant",
    ),
    "finance": (
        "venture", "capital", "fund", "investment", "finance", "bond",
        "accelerator", "incubator",
    ),
    "policy": (
        "agency", "commission", "office", "programme", "program",
        "united nations", "unesco", "who", "fao", "regulatory", "standards",
        "governance",
    ),
}


DOMAIN = {
    "ai": (
        "AI, machine learning, data infrastructure, robotics, and applied digital systems for the linked ecosystem use case.",
        "Uses model development, data engineering, software platforms, computational experimentation, and applied deployment partnerships.",
    ),
    "health": (
        "Biomedical research, clinical translation, health data, diagnostics, therapeutics, and patient-facing innovation.",
        "Uses clinical research infrastructure, translational studies, data-driven validation, institutional research programs, and partner pilots.",
    ),
    "agriculture": (
        "Agricultural science, crop systems, fertilizer and nutrient management, soil health, and field validation.",
        "Uses field trials, agronomic testing, extension networks, biological/chemical formulation work, and grower or commodity partnerships.",
    ),
    "water": (
        "Water systems, desalination and reuse, hydrology, water quality, and infrastructure resilience.",
        "Uses monitoring, treatment process evaluation, basin or facility-scale planning, pilot testing, and regulatory/utility coordination.",
    ),
    "materials": (
        "Chemistry, catalysis, advanced materials, polymers, manufacturing, and process engineering.",
        "Uses laboratory R&D, materials characterization, formulation/process design, pilot-scale validation, and manufacturing partnerships.",
    ),
    "mining": (
        "Critical minerals, mineral processing, extractive metallurgy, mine waste, tailings, and geological characterization.",
        "Uses beneficiation, hydrometallurgy, geochemical characterization, separation flowsheets, site data, and pilot-scale processing.",
    ),
    "energy": (
        "Energy systems, hydrogen, storage, renewables, grid technologies, nuclear-adjacent systems, and industrial decarbonization.",
        "Uses engineering analysis, demonstration projects, facility data, applied R&D, techno-economic assessment, and deployment partnerships.",
    ),
    "climate": (
        "Climate technology, carbon management, sustainability analytics, environmental risk reduction, and low-carbon transition pathways.",
        "Uses climate/data modeling, carbon accounting or removal methods, sustainability frameworks, pilots, and stakeholder implementation pathways.",
    ),
    "waste": (
        "Environmental remediation, radiological/TENORM management, contaminant characterization, industrial by-product reuse, and waste valorization.",
        "Uses contaminant characterization, treatment or stabilization pathways, environmental monitoring, risk assessment, and regulatory validation.",
    ),
    "finance": (
        "Financing, venture development, commercialization support, investment strategy, and ecosystem scaling for technology actors.",
        "Uses capital formation, portfolio support, market diligence, partner networks, and commercialization guidance.",
    ),
    "policy": (
        "Policy, standards, regulation, convening, public programs, and implementation support for the relevant ecosystem.",
        "Uses public mandates, guidance, convening authority, technical programs, grants, standards, and stakeholder coordination.",
    ),
    "general": (
        "Applied research, translational R&D, ecosystem coordination, and technical support in the linked GHUS context.",
        "Uses existing institutional capabilities, partnerships, data gathering, applied research, and staged validation around the relevant use case.",
    ),
}


CONSTRAINTS = {
    "waste": "Requires feedstock characterization, radiological/environmental compliance, disposal or reuse pathway clarity, and regulator engagement.",
    "mining": "Requires representative mineral/feedstock data, processing economics, permitting clarity, and alignment with operators or site owners.",
    "water": "Requires site-specific water chemistry, permitting, utility/operator access, and pilot data under realistic operating conditions.",
    "agriculture": "Requires crop/soil validation, seasonality-aware trials, grower participation, safety thresholds, and regulatory acceptance.",
    "health": "Requires data access, clinical governance, privacy compliance, institutional approvals, and clear translational use cases.",
    "ai": "Requires high-quality data access, model validation, integration with user workflows, security/privacy review, and deployment ownership.",
    "energy": "Requires project finance, interconnection or facility access, offtake/market alignment, safety review, and permitting.",
    "climate": "Requires credible measurement, reporting, verification, economics, policy alignment, and durable demand signals.",
    "finance": "Requires investable company pipeline, diligence-quality evidence, clear commercialization path, and aligned risk/return profile.",
    "policy": "Requires mandate fit, stakeholder consensus, procurement or grant pathway clarity, and realistic implementation authority.",
    "materials": "Requires scale-up data, material performance validation, supply-chain fit, EHS review, and manufacturability evidence.",
    "general": "Requires clearer use-case definition, partner alignment, funding, and validation evidence before prioritization.",
}


def blank(value):
    return value is None or str(value).strip() == ""


def norm(value):
    return (value or "").lower()


def short_description(text, limit=220):
    value = " ".join((text or "").replace("\n", " ").split())
    if not value:
        return ""
    cut = min(len(value), limit)
    for sep in (". ", "; "):
        idx = value.find(sep)
        if 40 <= idx <= limit:
            cut = idx + 1
            break
    out = value[:cut].strip().rstrip(" ,;")
    if len(value) > len(out) and not out.endswith("."):
        out += "."
    return out


def classify(actor, hubs, sectors):
    text_value = " ".join(
        [
            actor.name or "",
            actor.actor_type or "",
            actor.description or "",
            actor.website or "",
            " ".join(hubs),
            " ".join(sectors),
        ]
    ).lower()
    scores = Counter()
    for category, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_value:
                scores[category] += 1
    return scores.most_common(1)[0][0] if scores else "general"


def is_aggregate(actor):
    name = norm(actor.name)
    description = norm(actor.description)
    if "aggregate actor label" in description or "category or group of related organizations" in description:
        return True
    generic_terms = (
        "companies", "startups", "labs", "programs", "initiatives", "centers",
        "firms", "operators", "plants", "facilities", "projects", "anchors",
        "partners", "institutes", "agencies", "bodies", "manufacturers", "funds",
    )
    return any(name.endswith(term) or f" {term} " in name for term in generic_terms)


def lifecycle_role(actor, category):
    actor_type = norm(actor.actor_type)
    name = norm(actor.name)
    if any(k in name for k in ("venture", "fund", "accelerator", "incubator", "association", "ecosystem")):
        return "scaling"
    if any(k in name for k in ("operator", "plant", "facility", "complex", "mine", "manufacturer", "manufacturing", "utility", "farm bureau")):
        return "deployment"
    if any(k in name for k in ("pilot", "demonstration", "project developer", "project")):
        return "demonstration"
    if any(k in name for k in ("agency", "commission", "office", "regulatory", "standard", "governance", "water board")):
        return "validation"
    if actor_type in ("venture_capital", "accelerator", "industry_association", "consortium", "nonprofit"):
        return "scaling"
    if actor_type in ("industrial_partner", "company", "project_developer"):
        return "deployment"
    if actor_type in (
        "government_agency", "state_agency", "federal_agency", "un_agency",
        "un_programme", "un_committee", "un_secretariat",
        "intergovernmental_organization",
    ):
        return "validation"
    if actor_type in ("startup", "corporate_rd_lab", "national_research_lab", "national_research_center", "federal_research_system"):
        return "demonstration"
    if actor_type in ("university", "university_lab", "research_organization"):
        return "discovery"
    return "validation" if category in ("policy", "waste") else "discovery"


def current_activity(actor, aggregate, hubs, sectors):
    actor_type = norm(actor.actor_type)
    if aggregate:
        current = "Existing GHUS context uses this row as a category for related organizations rather than one legal entity."
    elif actor_type in ("university", "university_lab", "research_organization"):
        current = "Existing GHUS context positions this actor as a research and talent anchor for applied studies, technical validation, and collaboration."
    elif actor_type == "startup":
        current = "Existing GHUS context positions this actor as a technology developer moving products, processes, or platforms toward pilot and commercial validation."
    elif actor_type in ("corporate_rd_lab", "company"):
        current = "Existing GHUS context positions this actor as an industry R&D or operating company with potential applied research, partnership, and deployment capacity."
    elif actor_type in ("industrial_partner", "project_developer"):
        current = "Existing GHUS context positions this actor as an operating or project-development partner with assets, feedstocks, deployment settings, or market access."
    elif actor_type in ("national_research_lab", "national_research_center", "federal_research_system"):
        current = "Existing GHUS context positions this actor as a public research and validation platform with specialized facilities, scientific staff, and translational programs."
    elif actor_type in ("federal_agency", "state_agency", "government_agency", "un_agency", "un_programme", "un_committee", "un_secretariat", "intergovernmental_organization"):
        current = "Existing GHUS context positions this actor as a public or intergovernmental program actor shaping policy, standards, funding, implementation, or oversight."
    elif actor_type in ("venture_capital", "accelerator", "industry_association", "consortium", "nonprofit"):
        current = "Existing GHUS context positions this actor as an ecosystem, financing, convening, or commercialization support actor."
    else:
        current = "Existing GHUS context identifies this actor as relevant to the linked hub and technical domain."

    description = short_description(actor.description)
    if description:
        current += f" Existing description: {description}"
    context = []
    if hubs:
        context.append("linked hub context: " + ", ".join(hubs[:3]))
    if sectors:
        context.append("sector tags: " + ", ".join(sectors[:3]))
    if context:
        current += " Context used: " + "; ".join(context) + "."
    return current


def ip_note(actor, aggregate):
    actor_type = norm(actor.actor_type)
    if aggregate:
        return "Aggregate/category row; no single IP owner is identified. IP position depends on the specific member organizations selected for engagement."
    if actor_type in ("startup", "corporate_rd_lab", "company", "industrial_partner", "project_developer"):
        return "Potential IP is most likely in proprietary process know-how, product design, datasets, operating methods, or protected platform technology; no specific patent claim is asserted from the existing GHUS record."
    if actor_type in ("university", "university_lab", "research_organization", "national_research_lab", "national_research_center", "federal_research_system"):
        return "Potential IP may include publishable methods, datasets, software, materials, or patentable inventions managed through institutional technology-transfer channels; no specific license position is asserted here."
    if actor_type in ("federal_agency", "state_agency", "government_agency", "un_agency", "un_programme", "un_committee", "un_secretariat", "intergovernmental_organization"):
        return "Not primarily an IP-generating commercial actor; value is in public mandates, standards, data, funding, convening power, or regulatory guidance."
    if actor_type in ("venture_capital", "accelerator", "industry_association", "consortium", "nonprofit"):
        return "Not usually the core technology/IP owner; value is in capital, networks, program design, convening, and access to portfolio or member organizations."
    return "No specific public IP position is identified from the existing GHUS record."


def key_constraint(actor, category, aggregate):
    if aggregate:
        return "Requires identification of the specific constituent organizations, decision makers, assets, and IP owners before partnership or technical fit can be assessed."
    actor_type = norm(actor.actor_type)
    value = CONSTRAINTS.get(category, CONSTRAINTS["general"])
    if actor_type in ("university", "university_lab", "research_organization"):
        return value + " Translation usually needs sponsored funding and an industrial or public-sector deployment partner."
    if actor_type == "startup":
        return value + " Startup execution also depends on capital, customer validation, and credible scale-up milestones."
    if actor_type in ("corporate_rd_lab", "company", "industrial_partner", "project_developer"):
        return value + " Corporate engagement also depends on strategic priority, liability allocation, and business-unit sponsorship."
    return value


def build_values(actor, hubs, sectors):
    aggregate = is_aggregate(actor)
    category = classify(actor, hubs, sectors)
    focus, approach = DOMAIN[category]
    return {
        "primary_technical_focus": focus,
        "technical_approach": approach,
        "current_activities": current_activity(actor, aggregate, hubs, sectors),
        "technology_ip_notes": ip_note(actor, aggregate),
        "key_constraints": key_constraint(actor, category, aggregate),
        "primary_lifecycle_role": lifecycle_role(actor, category),
    }, category, aggregate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=25)
    parser.add_argument("--statement-timeout", default="10min")
    args = parser.parse_args()

    with SessionLocal() as session:
        session.execute(text(f"set statement_timeout to '{args.statement_timeout}'"))
        actors = session.execute(select(Actor).order_by(Actor.name)).scalars().all()
        actor_ids = [actor.actor_id for actor in actors]

        hubs = defaultdict(list)
        sectors = defaultdict(list)
        for actor_id, hub_name in session.execute(
            select(HubActor.actor_id, Hub.name)
            .join(Hub, Hub.hub_id == HubActor.hub_id)
            .where(HubActor.actor_id.in_(actor_ids))
        ):
            hubs[actor_id].append(hub_name)
        for actor_id, sector_name in session.execute(
            select(ActorSector.actor_id, Sector.name)
            .join(Sector, Sector.sector_id == ActorSector.sector_id)
            .where(ActorSector.actor_id.in_(actor_ids))
        ):
            sectors[actor_id].append(sector_name)

        mappings = []
        field_counts = Counter()
        categories = Counter()
        aggregates = 0
        for actor in actors:
            values, category, aggregate = build_values(actor, hubs[actor.actor_id], sectors[actor.actor_id])
            categories[category] += 1
            aggregates += int(aggregate)
            mapping = {"actor_id": actor.actor_id}
            for field in TARGET_FIELDS:
                if blank(getattr(actor, field)) and values.get(field):
                    mapping[field] = values[field]
                    field_counts[field] += 1
            if len(mapping) > 1:
                mappings.append(mapping)

        if not args.dry_run:
            for start in range(0, len(mappings), max(1, args.chunk_size)):
                session.bulk_update_mappings(Actor, mappings[start:start + args.chunk_size])
                session.commit()

    print(f"dry_run={args.dry_run}")
    print(f"updated_rows={0 if args.dry_run else len(mappings)}")
    print(f"candidate_rows={len(mappings)}")
    print(f"field_counts={dict(field_counts)}")
    print(f"category_counts={dict(categories)}")
    print(f"aggregate_count={aggregates}")


if __name__ == "__main__":
    main()
