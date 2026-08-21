"""
Actor enrichment candidate pipeline.

This job targets sparse actors created from ecosystem-map narratives. The
spreadsheet usually gives actor names but not per-actor websites, descriptions,
or locations. This pipeline searches trusted structured APIs, adds conservative
candidates from the hub website text, applies deterministic matches first, and
only calls Claude when explicitly enabled and the row passes cost gates.
Database updates happen only with --apply.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.ai.client import SONNET, UsageTracker, structured_json
from src.db.models import Actor, ActorRelevance, Challenge, Hub, HubActor, Source


logger = logging.getLogger(__name__)

AUDIT_LOG = "data/interim/actor_enrichment_candidates.csv"
AI_CONFIDENCE = 0.7
DEFAULT_APPLY_THRESHOLD = 0.85
HTTP_TIMEOUT = 12.0
USER_AGENT = "GHUS-Ecosystem-Intelligence/0.1 (actor-enrichment)"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
OPENALEX_MAX_RETRY_AFTER = 300.0
DB_RETRY_ATTEMPTS = 6
DB_RETRY_SLEEP_SECONDS = 10.0
DEFAULT_MISSING_FIELD_FILTERS = ("description", "website", "location_city", "country")
ENRICHMENT_TARGET_FIELDS = ("description", "website", "location_city", "state", "country")
MISSING_FIELD_ALIASES = {
    "description": "description",
    "website": "website",
    "city": "location_city",
    "location_city": "location_city",
    "state": "state",
    "country": "country",
}
CANDIDATE_FIELD_BY_ACTOR_FIELD = {
    "description": "description",
    "website": "website",
    "location_city": "city",
    "state": "state",
    "country": "country",
}
BLOCKED_WEB_RESULT_DOMAINS = {
    "wikipedia.org",
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "crunchbase.com",
    "pitchbook.com",
    "bloomberg.com",
    "reuters.com",
    "sec.gov",
    "nlr.gov",
}
WEB_AUTO_APPLY_MIN_SCORE = 0.95
WEB_AUTO_APPLY_MAX_RANK = 2
WEB_RESULT_TITLE_BLOCKLIST = {
    "news",
    "newsroom",
    "press release",
    "careers",
    "jobs",
    "login",
    "support",
    "contact us",
    "dashboard",
    "facebook",
    "linkedin",
    "wikipedia",
    "youtube",
}
WEB_AUTO_APPLY_GENERIC_TOKENS = {
    "bodies",
    "commission",
    "commissions",
    "facilities",
    "firms",
    "groups",
    "initiatives",
    "labs",
    "plants",
    "producers",
    "programs",
    "projects",
    "refinery",
    "research",
    "smelter",
    "studios",
}

NON_ENTITY_LABELS = {
    "academic anchors",
    "academic medical anchors",
    "industry anchors",
    "corporate anchors",
    "clinical anchors",
    "research anchors",
}

GENERIC_ENTITY_TERMS = {
    "anchors",
    "agencies",
    "accelerator",
    "accelerators",
    "association",
    "associations",
    "authority",
    "authorities",
    "bodies",
    "boards",
    "clusters",
    "cluster",
    "commissions",
    "companies",
    "cooperative",
    "cooperatives",
    "department",
    "developer",
    "developers",
    "ecosystem",
    "facilities",
    "firms",
    "funds",
    "groups",
    "initiative",
    "initiatives",
    "institute",
    "institutes",
    "labs",
    "manufacturers",
    "network",
    "networks",
    "operations",
    "operator",
    "operators",
    "plant",
    "plants",
    "platform",
    "platforms",
    "producer",
    "producers",
    "programs",
    "projects",
    "provider",
    "providers",
    "centers",
    "centres",
    "departments",
    "stations",
    "offices",
    "startups",
    "stakeholders",
    "partners",
    "institutions",
    "laboratory",
    "section",
    "training",
    "organizations",
}

CATEGORY_DESCRIPTOR_TERMS = {
    "academic",
    "advanced",
    "agricultural",
    "agrochemical",
    "ai",
    "atmospheric",
    "bio",
    "biohealth",
    "biotech",
    "biotechnology",
    "brackish",
    "cancer",
    "capture",
    "carbon",
    "chemistry",
    "clean",
    "clinical",
    "commodity",
    "corporate",
    "crop",
    "dairy",
    "desalination",
    "digital",
    "energy",
    "engineering",
    "enterprise",
    "expert",
    "field",
    "focused",
    "formulation",
    "food",
    "functional",
    "green",
    "groundwater",
    "health",
    "horticulture",
    "industry",
    "intergovernmental",
    "management",
    "manufacturing",
    "material",
    "materials",
    "medical",
    "medicine",
    "mission",
    "modeling",
    "offshore",
    "pilot",
    "planning",
    "polymer",
    "plant",
    "science",
    "sciences",
    "regional",
    "research",
    "robotics",
    "saas",
    "soil",
    "specialty",
    "specialized",
    "startup",
    "sustainability",
    "technology",
    "testing",
    "venture",
    "water",
}

CORPORATE_UNIT_TERMS = {
    "research laboratories",
    "research laboratory",
    "laboratories",
    "laboratory",
    "labs",
    "lab",
    "r&d",
    "rd",
    "research center",
    "research centre",
}

KNOWN_OFFICIAL_ORGS = [
    {
        "names": ("Commission for Social Development",),
        "website": "https://social.desa.un.org/issues/social-development/csocd",
        "description": "The Commission for Social Development is a functional commission of the United Nations Economic and Social Council focused on social development policy.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("Commission on Population and Development",),
        "website": "https://www.un.org/development/desa/pd/content/commission-population-and-development",
        "description": "The Commission on Population and Development is a United Nations commission that reviews population and development issues.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("Commission on Science and Technology for Development",),
        "website": "https://unctad.org/topic/commission-on-science-and-technology-for-development",
        "description": "The Commission on Science and Technology for Development is a United Nations body focused on science, technology, and development policy.",
        "city": "Geneva",
        "country": "Switzerland",
    },
    {
        "names": ("Commission on the Status of Women",),
        "website": "https://www.unwomen.org/en/csw",
        "description": "The Commission on the Status of Women is the United Nations intergovernmental body dedicated to gender equality and women's empowerment.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("Development Coordination Office",),
        "website": "https://unsdg.un.org/about/development-coordination-office",
        "description": "The United Nations Development Coordination Office supports the UN resident coordinator system and UN development coordination.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("ECONOMIC AND SOCIAL COUNCIL", "Economic and Social Council"),
        "website": "https://ecosoc.un.org",
        "description": "The United Nations Economic and Social Council coordinates economic, social, and related work across the UN system.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("Food and Agriculture Organization", "FAO"),
        "website": "https://www.fao.org",
        "description": "The Food and Agriculture Organization is a United Nations specialized agency focused on food security, agriculture, forestry, fisheries, and rural development.",
        "city": "Rome",
        "country": "Italy",
    },
    {
        "names": ("International Bank for Reconstruction and development", "International Bank for Reconstruction and Development", "IBRD"),
        "website": "https://www.worldbank.org/en/who-we-are/ibrd",
        "description": "The International Bank for Reconstruction and Development is the World Bank institution that provides lending and advisory support to middle-income and creditworthy lower-income countries.",
        "city": "Washington",
        "country": "United States",
    },
    {
        "names": ("International Development Association", "IDA"),
        "website": "https://ida.worldbank.org",
        "description": "The International Development Association is the World Bank fund that provides concessional financing and grants to the world's poorest countries.",
        "city": "Washington",
        "country": "United States",
    },
    {
        "names": ("International Finance corporation", "International Finance Corporation", "IFC"),
        "website": "https://www.ifc.org",
        "description": "The International Finance Corporation is a World Bank Group institution focused on private-sector development in emerging markets.",
        "city": "Washington",
        "country": "United States",
    },
    {
        "names": ("International Fund for Agricultural Development", "IFAD"),
        "website": "https://www.ifad.org",
        "description": "The International Fund for Agricultural Development is a United Nations specialized agency and international financial institution focused on rural development.",
        "city": "Rome",
        "country": "Italy",
    },
    {
        "names": ("International Telecommunication Union", "ITU"),
        "website": "https://www.itu.int",
        "description": "The International Telecommunication Union is the United Nations specialized agency for information and communication technologies.",
        "city": "Geneva",
        "country": "Switzerland",
    },
    {
        "names": ("Break Through Tech AI Program (Cornell Tech)", "Break Through Tech's AI Program"),
        "website": "https://tech.cornell.edu/impact/break-through-tech/",
        "description": "Break Through Tech's AI Program is a Cornell Tech-linked program that prepares undergraduate students for artificial intelligence careers through machine learning coursework, industry projects, and professional readiness support.",
        "city": "New York",
        "state": "New York",
        "country": "United States",
    },
    {
        "names": ("Cornell AI Initiative",),
        "website": "https://ai.cornell.edu/",
        "description": "The Cornell AI Initiative is a university-wide Cornell effort focused on artificial intelligence research, education, and responsible AI applications across the university.",
        "city": "Ithaca",
        "state": "New York",
        "country": "United States",
    },
    {
        "names": ("ExxonMobil Baytown Technology & Engineering Complex",),
        "website": "https://corporate.exxonmobil.com/locations/united-states/baytown",
        "description": "ExxonMobil's Baytown area operations include a global technology center within its Baytown refining and petrochemical complex.",
        "city": "Baytown",
        "state": "Texas",
        "country": "United States",
    },
    {
        "names": ("Harvard Chemistry & Chemical Biology",),
        "website": "https://www.chemistry.harvard.edu/",
        "description": "Harvard's Department of Chemistry and Chemical Biology is an academic department focused on chemistry and chemical biology research and education.",
        "city": "Cambridge",
        "state": "Massachusetts",
        "country": "United States",
    },
    {
        "names": ("Johns Hopkins Precision Medicine initiatives", "Johns Hopkins inHealth"),
        "website": "https://www.hopkinsmedicine.org/inhealth/",
        "description": "Johns Hopkins inHealth is a strategic Johns Hopkins Medicine initiative to advance precision medicine through data, analytics, and disease-specific expertise.",
        "city": "Baltimore",
        "state": "Maryland",
        "country": "United States",
    },
    {
        "names": ("Lawrence Livermore National Laboratory", "LLNL"),
        "website": "https://www.llnl.gov",
        "description": "Lawrence Livermore National Laboratory is a U.S. Department of Energy national laboratory focused on science and technology for national security.",
        "city": "Livermore",
        "state": "California",
        "country": "United States",
    },
    {
        "names": ("NASA Jet Propulsion Laboratory (JPL)", "Jet Propulsion Laboratory", "JPL"),
        "website": "https://www.jpl.nasa.gov",
        "description": "NASA's Jet Propulsion Laboratory is a federally funded research and development center focused on robotic space and Earth science missions.",
        "city": "Pasadena",
        "state": "California",
        "country": "United States",
    },
    {
        "names": ("National Renewable Energy Laboratory", "National Renewable Energy Laboratory (energy-mineral link)", "NREL"),
        "website": "https://www.nrel.gov",
        "description": "The National Renewable Energy Laboratory is a U.S. Department of Energy national laboratory focused on renewable energy and energy efficiency research.",
        "city": "Golden",
        "state": "Colorado",
        "country": "United States",
    },
    {
        "names": ("NCAR", "National Center for Atmospheric Research"),
        "website": "https://ncar.ucar.edu",
        "description": "The National Center for Atmospheric Research is a U.S. research center focused on atmospheric and Earth system science.",
        "city": "Boulder",
        "state": "Colorado",
        "country": "United States",
    },
    {
        "names": ("Materials Research Science and Engineering Centers", "MRSEC"),
        "website": "https://www.nsf.gov/mps/materials-research-science-engineering-centers",
        "description": "The U.S. National Science Foundation Materials Research Science and Engineering Centers are university-based centers supporting interdisciplinary materials research, education, and shared research infrastructure.",
        "city": "Alexandria",
        "state": "Virginia",
        "country": "United States",
    },
    {
        "names": ("Michigan State University",),
        "website": "https://msu.edu/",
        "description": "Michigan State University is a public research university in East Lansing, Michigan.",
        "city": "East Lansing",
        "state": "Michigan",
        "country": "United States",
    },
    {
        "names": ("MIT Media Lab",),
        "website": "https://www.media.mit.edu/",
        "description": "The MIT Media Lab is an interdisciplinary research laboratory at the Massachusetts Institute of Technology.",
        "city": "Cambridge",
        "state": "Massachusetts",
        "country": "United States",
    },
    {
        "names": ("Northwestern University Chemistry", "Northwestern Chemistry"),
        "website": "https://chemistry.northwestern.edu/",
        "description": "Northwestern University's Department of Chemistry is an academic department for chemistry education and research.",
        "city": "Evanston",
        "state": "Illinois",
        "country": "United States",
    },
    {
        "names": ("NYC Mayor's Climate Office", "NYC Mayor’s Climate Office"),
        "website": "https://www.nyc.gov/site/cpp/our-programs/programs.page",
        "description": "The NYC Mayor's Office of Climate Policy and Programs develops and delivers climate policy initiatives for New York City.",
        "city": "New York",
        "state": "New York",
        "country": "United States",
    },
    {
        "names": ("Office for Digital and Emerging Technologies",),
        "website": "https://www.un.org/digital-emerging-technologies/",
        "description": "The United Nations Office for Digital and Emerging Technologies is the UN system-wide focal point for digital issues and digital cooperation.",
        "city": "New York",
        "state": "New York",
        "country": "United States",
    },
    {
        "names": ("Office of the Special Adviser on Africa",),
        "website": "https://www.un.org/osaa/",
        "description": "The Office of the Special Adviser on Africa is a United Nations office supporting international action and advocacy for African development priorities.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("Rice Baker Institute Energy Program", "Rice Baker Institute Center for Energy Studies"),
        "website": "https://www.bakerinstitute.org/center/center-energy-studies",
        "description": "The Center for Energy Studies at Rice University's Baker Institute for Public Policy conducts energy-market, policy, technology, and geopolitics research.",
        "city": "Houston",
        "state": "Texas",
        "country": "United States",
    },
    {
        "names": ("Rice University Chemistry",),
        "website": "https://chemistry.rice.edu/",
        "description": "Rice University's Department of Chemistry is an academic department for chemistry education and research.",
        "city": "Houston",
        "state": "Texas",
        "country": "United States",
    },
    {
        "names": ("SECRETARIAT", "United Nations Secretariat"),
        "website": "https://www.un.org/en/about-us/secretariat",
        "description": "The United Nations Secretariat carries out the day-to-day work of the United Nations as mandated by the General Assembly and the organization's other main organs.",
        "city": "New York",
        "state": "New York",
        "country": "United States",
    },
    {
        "names": ("Stanford Chemistry", "Stanford Department of Chemistry"),
        "website": "https://chemistry.stanford.edu/",
        "description": "Stanford University's Department of Chemistry is an academic department focused on chemical sciences research and education.",
        "city": "Stanford",
        "state": "California",
        "country": "United States",
    },
    {
        "names": ("UN Women",),
        "website": "https://www.unwomen.org",
        "description": "UN Women is the United Nations entity dedicated to gender equality and the empowerment of women.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("UNGA Second Committee (Economic and Financial)", "Second Committee"),
        "website": "https://www.un.org/en/ga/second/",
        "description": "The Second Committee is the Economic and Financial Committee of the United Nations General Assembly.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("UNIDO", "United Nations Industrial Development Organization"),
        "website": "https://www.unido.org",
        "description": "The United Nations Industrial Development Organization is a UN specialized agency focused on inclusive and sustainable industrial development.",
        "city": "Vienna",
        "country": "Austria",
    },
    {
        "names": ("U.S. Ventures", "U.S. Venture", "US Venture"),
        "website": "https://www.usventure.com/",
        "description": "U.S. Venture is a private company with energy, transportation, and sustainability-related business lines.",
        "city": "Appleton",
        "state": "Wisconsin",
        "country": "United States",
    },
    {
        "names": ("UC Berkeley Chemistry", "Berkeley Chemistry"),
        "website": "https://chemistry.berkeley.edu/chem",
        "description": "UC Berkeley's Department of Chemistry is an academic department in the College of Chemistry focused on chemistry education and research.",
        "city": "Berkeley",
        "state": "California",
        "country": "United States",
    },
    {
        "names": ("University of Illinois Urbana-Champaign", "University of Illinois Urbana Champaign"),
        "website": "https://illinois.edu/",
        "description": "The University of Illinois Urbana-Champaign is a public research university in Champaign-Urbana, Illinois.",
        "city": "Champaign",
        "state": "Illinois",
        "country": "United States",
    },
    {
        "names": ("University of Washington",),
        "website": "https://www.washington.edu/",
        "description": "The University of Washington is a public research university with campuses in Seattle, Bothell, and Tacoma.",
        "city": "Seattle",
        "state": "Washington",
        "country": "United States",
    },
    {
        "names": ("United Nations Academic Impact",),
        "prefix_names": ("United Nations Academic Impact",),
        "website": "https://www.un.org/en/academic-impact/page/about-unai",
        "description": "United Nations Academic Impact is a UN initiative that aligns higher education institutions with United Nations principles and goals.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("United Nations Children's Fund", "UNICEF"),
        "website": "https://www.unicef.org",
        "description": "The United Nations Children's Fund is a UN agency that provides humanitarian and development assistance for children.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("United Nations Development Programme", "UNDP"),
        "website": "https://www.undp.org",
        "description": "The United Nations Development Programme is the UN development agency working on poverty reduction, governance, resilience, and sustainable development.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("United Nations Educational, Scientific and Cultural Organization", "UNESCO"),
        "website": "https://www.unesco.org",
        "description": "UNESCO is the United Nations specialized agency for education, science, culture, communication, and information.",
        "city": "Paris",
        "country": "France",
    },
    {
        "names": ("United Nations Environment Programme", "UNEP"),
        "website": "https://www.unep.org",
        "description": "The United Nations Environment Programme is the UN authority for environmental agenda-setting, science, and coordination.",
        "city": "Nairobi",
        "country": "Kenya",
    },
    {
        "names": ("UNITED NATIONS GENERAL ASSEMBLY", "United Nations General Assembly"),
        "website": "https://www.un.org/en/ga/",
        "description": "The United Nations General Assembly is the main deliberative, policymaking, and representative organ of the United Nations.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("United Nations Institute for Training and research", "United Nations Institute for Training and Research", "UNITAR"),
        "website": "https://unitar.org",
        "description": "The United Nations Institute for Training and Research provides training and capacity-building services for the UN system and member states.",
        "city": "Geneva",
        "country": "Switzerland",
    },
    {
        "names": ("United Nations Research Institute for Social Development", "UNRISD"),
        "website": "https://www.unrisd.org",
        "description": "The United Nations Research Institute for Social Development is an autonomous UN research institute focused on the social dimensions of development.",
        "city": "Geneva",
        "country": "Switzerland",
    },
    {
        "names": ("United Nations Youth Office",),
        "website": "https://www.un.org/youthaffairs/en",
        "description": "The United Nations Youth Office coordinates and advances UN work on youth affairs and youth engagement.",
        "city": "New York",
        "country": "United States",
    },
    {
        "names": ("World Food Programme", "WFP"),
        "website": "https://www.wfp.org",
        "description": "The World Food Programme is the United Nations humanitarian organization focused on food assistance and food security.",
        "city": "Rome",
        "country": "Italy",
    },
    {
        "names": ("World Health Organization", "WHO"),
        "website": "https://www.who.int",
        "description": "The World Health Organization is the United Nations specialized agency responsible for international public health.",
        "city": "Geneva",
        "country": "Switzerland",
    },
]


@dataclass
class ApiCandidate:
    provider: str
    name: str
    website: Optional[str] = None
    description: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    source_url: Optional[str] = None
    evidence: Optional[str] = None

    def as_prompt_dict(self) -> dict:
        return {
            "provider": self.provider,
            "name": self.name,
            "website": self.website,
            "description": self.description,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "source_url": self.source_url,
            "evidence": self.evidence,
        }


@dataclass
class RunStats:
    actors_seen: int = 0
    candidates_found: int = 0
    decisions_made: int = 0
    no_candidates: int = 0
    no_match: int = 0
    needs_review: int = 0
    would_apply: int = 0
    applied: int = 0
    skipped_low_confidence: int = 0
    api_failures: int = 0
    ai_failures: int = 0
    claude_skipped: int = 0
    claude_budget_skipped: int = 0
    claude_weak_candidate_skipped: int = 0
    stopped_early: bool = False

    def summary(self) -> str:
        text = (
            f"  Actors processed:       {self.actors_seen}\n"
            f"  Source candidates found:{self.candidates_found}\n"
            f"  Decisions made:         {self.decisions_made}\n"
            f"  No candidates:          {self.no_candidates}\n"
            f"  No verified match:      {self.no_match}\n"
            f"  Human review flagged:   {self.needs_review}\n"
            f"  Would apply:            {self.would_apply}\n"
            f"  Applied:                {self.applied}\n"
            f"  Low-confidence skipped: {self.skipped_low_confidence}\n"
            f"  API failures:           {self.api_failures}\n"
            f"  AI failures:            {self.ai_failures}\n"
            f"  Claude skipped:         {self.claude_skipped}\n"
            f"  Claude budget skipped:  {self.claude_budget_skipped}\n"
            f"  Weak-candidate skipped: {self.claude_weak_candidate_skipped}"
        )
        if self.stopped_early:
            text += "\n  Stopped early:          yes"
        return text


def normalize_text(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def normalize_missing_fields(fields: Optional[list[str]]) -> tuple[str, ...]:
    if not fields or "any" in fields:
        return DEFAULT_MISSING_FIELD_FILTERS

    normalized: list[str] = []
    for raw_field in fields:
        key = (raw_field or "").strip().lower()
        field = MISSING_FIELD_ALIASES.get(key)
        if not field:
            raise ValueError(f"Unsupported missing field: {raw_field}")
        if field not in normalized:
            normalized.append(field)
    return tuple(normalized or DEFAULT_MISSING_FIELD_FILTERS)


def acronym_candidates(name: str) -> set[str]:
    values = set(re.findall(r"\(([A-Z][A-Z0-9&.-]{1,12})\)", name or ""))
    words = re.findall(r"\b[A-Z][A-Za-z&]+\b", name or "")
    if len(words) >= 2:
        values.add("".join(w[0] for w in words if w[0].isupper()))
    return {v.strip(".-") for v in values if 2 <= len(v.strip(".-")) <= 12}


def is_placeholder_actor_name(name: str) -> bool:
    normalized = normalize_text(name)
    if normalized in NON_ENTITY_LABELS:
        return True
    tokens = normalized.split()
    if not tokens:
        return True
    # Labels like "Academic Anchors" are category buckets from narratives, not
    # organizations that should be enriched from public APIs.
    return len(tokens) <= 4 and any(term in tokens for term in GENERIC_ENTITY_TERMS)


def has_specific_name_signal(name: str) -> bool:
    generic_acronyms = {"AI", "R&D", "RD"}
    for token in re.findall(r"\b[A-Z0-9&.-]{2,}\b", name or ""):
        cleaned = token.strip(".-&")
        if cleaned not in generic_acronyms:
            return True
    if re.search(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b", name or ""):
        return True
    if re.search(r"\d", name or ""):
        return True
    return False


def is_aggregate_actor_name(name: str, actor_type: Optional[str] = None) -> bool:
    normalized = normalize_text(name)
    tokens = normalized.split()
    if re.search(r"(^|[\s(])(e\.g\.|eg|for example)([\s,.)]|$)", name or "", flags=re.I):
        return True
    if is_placeholder_actor_name(name):
        return True
    if not tokens:
        return False
    if any(term in tokens for term in ("anchors", "ecosystem", "firms", "startups")):
        return True
    if has_specific_name_signal(name):
        return False
    if actor_type == "consortium" and len(tokens) <= 6:
        return True
    generic_terms = GENERIC_ENTITY_TERMS | {
        "labs", "centers", "centres", "institutions", "organizations",
    }
    if not any(term in tokens for term in generic_terms):
        return False
    connective_terms = {"and", "or", "in", "across", "with", "for", "e", "g", "eg"}
    descriptive = [
        t for t in tokens
        if t not in generic_terms and t not in connective_terms
    ]
    return bool(descriptive) and all(t in CATEGORY_DESCRIPTOR_TERMS for t in descriptive)


def search_name_variants(name: str) -> list[str]:
    variants = [name]
    parenthetical = re.findall(r"\(([^)]+)\)", name or "")
    variants.extend(parenthetical)
    variants.append(re.sub(r"\([^)]*\)", "", name or "").strip())

    lowered = normalize_text(name)
    if any(normalize_text(term) in lowered for term in CORPORATE_UNIT_TERMS):
        stripped = name
        for term in sorted(CORPORATE_UNIT_TERMS, key=len, reverse=True):
            stripped = re.sub(r"\b" + re.escape(term) + r"\b", "", stripped, flags=re.I)
        variants.append(re.sub(r"\s+", " ", stripped).strip(" -,:;"))

    out = []
    seen = set()
    for variant in variants:
        cleaned = re.sub(r"\s+", " ", (variant or "")).strip()
        key = normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out[:5]


def distinctive_tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "of", "for", "at", "in", "on", "with", "inc", "incorporated",
        "corp", "corporation", "co", "company", "ltd", "llc", "plc", "sa", "ag",
        "research", "laboratories", "laboratory", "labs", "lab", "r", "d",
    }
    return {w for w in normalize_text(value).split() if len(w) > 1 and w not in stop}


def name_similarity(left: str, right: str) -> float:
    ltokens = distinctive_tokens(left)
    rtokens = distinctive_tokens(right)
    if not ltokens or not rtokens:
        return 0.0
    overlap = ltokens & rtokens
    return max(
        len(overlap) / max(1, len(ltokens)),
        len(overlap) / max(1, len(rtokens)),
    )


def _join_names(values: list[str], limit: int = 3) -> str:
    clean = [v for v in values if v]
    if not clean:
        return "linked hub context"
    if len(clean) <= limit:
        return ", ".join(clean)
    return ", ".join(clean[:limit]) + f", and {len(clean) - limit} more hubs"


def _clean_context_snippet(value: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    text = text.replace("â€¢", ";").replace("•", ";")
    text = text.replace("â€“", "-").replace("–", "-")
    return text[:limit].rstrip(" .;,-")


def _safe_location_value(value: Optional[str], *, country: bool = False) -> Optional[str]:
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return None
    if any(mark in text for mark in ("|", "(", ")", ",")):
        return None
    if "â€“" in text or "–" in text:
        return None
    if country:
        common = {
            "usa", "us", "united states", "united states of america",
            "canada", "mexico", "united kingdom", "uk", "morocco",
            "france", "germany", "italy", "spain", "china", "japan",
            "india", "brazil", "australia",
        }
        if text.lower() not in common:
            return None
    return text[:120]


def _shared_hub_location(hubs: list[Hub]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not hubs:
        return None, None, None
    if len(hubs) == 1:
        hub = hubs[0]
        country = _safe_location_value(hub.country, country=True)
        if not country:
            return None, None, None
        return (
            _safe_location_value(hub.primary_city),
            _safe_location_value(hub.state),
            country,
        )
    countries = {
        _safe_location_value(hub.country, country=True)
        for hub in hubs
        if _safe_location_value(hub.country, country=True)
    }
    if len(countries) == 1:
        return None, None, next(iter(countries))
    return None, None, None


def build_aggregate_actor_decision(actor: Actor, hubs: list[Hub]) -> dict:
    hub_names = [hub.name for hub in hubs]
    city, state, country = _shared_hub_location(hubs)
    hub_label = _join_names(hub_names)
    focus_bits = [
        hub.core_topic_strengths.strip()
        for hub in hubs
        if hub.core_topic_strengths and hub.core_topic_strengths.strip()
    ]
    focus = ""
    if focus_bits:
        focus = " The linked hub context emphasizes " + _clean_context_snippet(focus_bits[0]) + "."
    description = (
        f"{actor.name} is an aggregate actor label used for a group of related "
        f"organizations in {hub_label}, not a single named legal entity."
        f"{focus}"
    )
    return {
        "matched": True,
        "confidence": 0.88,
        "needs_human_review": False,
        "description": description,
        "website": None,
        "location_city": city,
        "state": state,
        "country": country,
        "source_url": f"hub_context://aggregate_actor/{actor.actor_id}",
        "evidence_summary": (
            "Generated from linked hub context because the actor name is a "
            "category/group label rather than a concrete organization."
        ),
    }


def build_name_context_aggregate_actor_decision(actor: Actor) -> dict:
    description = (
        f"{actor.name} is an aggregate actor label used for a category or group "
        "of related organizations, not a single named legal entity."
    )
    return {
        "matched": True,
        "confidence": 0.86,
        "needs_human_review": False,
        "description": description,
        "website": None,
        "location_city": None,
        "state": None,
        "country": None,
        "source_url": f"name_context://aggregate_actor/{actor.actor_id}",
        "evidence_summary": (
            "Generated from the actor name because it is a category/group label; "
            "no website or location was inferred."
        ),
    }


def build_hub_context_actor_decision(
    actor: Actor,
    hubs: list[Hub],
    reason: str,
) -> dict:
    hub_names = [hub.name for hub in hubs]
    hub_label = _join_names(hub_names)
    focus_bits = [
        hub.core_topic_strengths.strip()
        for hub in hubs
        if hub.core_topic_strengths and hub.core_topic_strengths.strip()
    ]
    focus = ""
    if focus_bits:
        focus = " The linked hub context emphasizes " + _clean_context_snippet(focus_bits[0]) + "."
    description = (
        f"{actor.name} is a hub-linked actor referenced in {hub_label}. "
        f"No high-confidence structured API match was confirmed, so this "
        f"record is enriched from hub context only."
        f"{focus}"
    )
    return {
        "matched": True,
        "confidence": 0.86,
        "needs_human_review": False,
        "description": description,
        "website": None,
        "location_city": None,
        "state": None,
        "country": None,
        "source_url": f"hub_context://actor/{actor.actor_id}",
        "evidence_summary": reason,
    }


def build_unresolved_actor_decision(reason: str) -> dict:
    return {
        "matched": False,
        "confidence": 0.0,
        "needs_human_review": True,
        "description": None,
        "website": None,
        "location_city": None,
        "state": None,
        "country": None,
        "source_url": None,
        "evidence_summary": reason,
    }


def known_official_record(name: str) -> Optional[dict]:
    normalized = normalize_text(name)
    for record in KNOWN_OFFICIAL_ORGS:
        for official_name in record.get("names", ()):
            if normalized == normalize_text(official_name) or _parenthetical_annotation_compatible(name, official_name):
                return record
        for prefix in record.get("prefix_names", ()):
            prefix_key = normalize_text(prefix)
            if normalized.startswith(prefix_key):
                return record
    return None


def build_known_official_actor_decision(actor: Actor) -> Optional[dict]:
    record = known_official_record(actor.name)
    if not record:
        return None
    return {
        "matched": True,
        "confidence": 0.96,
        "needs_human_review": False,
        "description": record["description"],
        "website": record["website"],
        "location_city": record.get("city"),
        "state": record.get("state"),
        "country": record.get("country"),
        "source_url": record["website"],
        "evidence_summary": "Exact curated official organization match.",
    }


def _canonical_url_key(url: Optional[str]) -> str:
    text = (url or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    return text.rstrip("/")


def _name_without_parentheticals(value: str) -> str:
    return normalize_text(re.sub(r"\([^)]*\)", "", value or ""))


def _parenthetical_annotations(value: str) -> list[str]:
    return [
        normalize_text(match)
        for match in re.findall(r"\(([^)]+)\)", value or "")
        if normalize_text(match)
    ]


def _parenthetical_annotation_compatible(actor_name: str, official_name: str) -> bool:
    if _name_without_parentheticals(actor_name) != _name_without_parentheticals(official_name):
        return False

    actor_annotations = _parenthetical_annotations(actor_name)
    official_annotations = _parenthetical_annotations(official_name)
    if not actor_annotations or not official_annotations:
        return False

    return any(
        actor_note == official_note
        or actor_note.startswith(f"{official_note} ")
        or official_note.startswith(f"{actor_note} ")
        for actor_note in actor_annotations
        for official_note in official_annotations
    )


def _official_label_directly_names_actor(actor_name: str, label: str) -> bool:
    actor_key = normalize_text(actor_name)
    label_key = normalize_text(label)
    if not actor_key or not label_key:
        return False
    if actor_key == label_key:
        return True
    if _parenthetical_annotation_compatible(actor_name, label):
        return True
    # Accept labels that add an institutional prefix, e.g.
    # "UC Davis Center for Watershed Sciences".
    return len(actor_key.split()) >= 3 and actor_key in label_key


def build_exact_official_website_decision(
    actor: Actor,
    candidates: list[ApiCandidate],
) -> Optional[dict]:
    if is_aggregate_actor_name(actor.name, actor.actor_type):
        return None

    matches = [
        candidate
        for candidate in candidates
        if candidate.provider == "hub_official_websites"
        and candidate.website
        and candidate.source_url
        and _official_label_directly_names_actor(actor.name, candidate.name)
    ]
    if not matches:
        return None

    by_url = {
        _canonical_url_key(candidate.source_url or candidate.website): candidate
        for candidate in matches
    }
    if len(by_url) != 1:
        return None

    candidate = next(iter(by_url.values()))
    return {
        "matched": True,
        "confidence": 0.9,
        "needs_human_review": False,
        "description": (
            f"{actor.name} is an organization or program identified through "
            "an exact official website listing in GHUS ecosystem context."
        ),
        "website": candidate.website,
        "location_city": None,
        "state": None,
        "country": None,
        "source_url": candidate.source_url,
        "evidence_summary": (
            f"Exact official website listing label '{candidate.name}' matches the actor."
        ),
    }


def _candidate_can_fill_missing_field(
    actor: Actor,
    candidate: ApiCandidate,
    target_fields: Optional[tuple[str, ...]] = None,
) -> bool:
    fields = target_fields or ENRICHMENT_TARGET_FIELDS
    for field in fields:
        candidate_attr = CANDIDATE_FIELD_BY_ACTOR_FIELD[field]
        value = getattr(candidate, candidate_attr)
        existing = getattr(actor, field)
        if value and not existing:
            return True
    return False


def _candidate_match_score(actor: Actor, candidate: ApiCandidate) -> float:
    score = max(
        name_similarity(actor.name, candidate.name),
        name_similarity(_name_without_parentheticals(actor.name), candidate.name),
    )
    if _official_label_directly_names_actor(actor.name, candidate.name):
        score = max(score, 1.0)
    for acronym in acronym_candidates(actor.name):
        if re.search(r"\b" + re.escape(acronym) + r"\b", candidate.name or ""):
            score = max(score, 0.82)
    return score


def _annotation_is_acronym_for_name(annotation: str, name: str) -> bool:
    note = re.sub(r"[^A-Za-z0-9]", "", annotation or "").upper()
    if len(note) < 2 or len(note) > 12:
        return False
    stop = {"and", "of", "the", "for", "at", "in", "on"}
    words = [word for word in normalize_text(name).split() if word not in stop]
    acronym = "".join(word[0].upper() for word in words if word)
    return note == acronym


def _strict_api_candidate_match(actor: Actor, candidate: ApiCandidate) -> bool:
    if candidate.provider not in {"ror", "openalex", "wikidata"}:
        return False

    actor_key = normalize_text(actor.name)
    candidate_key = normalize_text(candidate.name)
    if actor_key and actor_key == candidate_key:
        return True
    if _parenthetical_annotation_compatible(actor.name, candidate.name):
        return True

    actor_annotations = _parenthetical_annotations(actor.name)
    candidate_annotations = _parenthetical_annotations(candidate.name)
    if actor_annotations and not candidate_annotations:
        actor_base = re.sub(r"\([^)]*\)", "", actor.name or "").strip()
        return _name_without_parentheticals(actor.name) == _name_without_parentheticals(candidate.name) and all(
            _annotation_is_acronym_for_name(note, actor_base) for note in actor_annotations
        )

    return (
        not actor_annotations
        and _name_without_parentheticals(actor.name) == _name_without_parentheticals(candidate.name)
    )


def build_high_confidence_api_candidate_decision(
    actor: Actor,
    candidates: list[ApiCandidate],
    target_fields: Optional[tuple[str, ...]] = None,
) -> Optional[dict]:
    matches = [
        candidate
        for candidate in candidates
        if _candidate_can_fill_missing_field(actor, candidate, target_fields)
        and _strict_api_candidate_match(actor, candidate)
    ]
    if not matches:
        return None

    url_keys = {
        _canonical_url_key(candidate.website or candidate.source_url)
        for candidate in matches
        if candidate.website or candidate.source_url
    }
    if len(url_keys) > 1:
        return None

    def priority(candidate: ApiCandidate) -> tuple[int, float]:
        provider_priority = {
            "ror": 0,
            "openalex": 1,
            "wikidata": 2,
            "sec": 3,
        }.get(candidate.provider, 9)
        return provider_priority, -_candidate_match_score(actor, candidate)

    candidate = sorted(matches, key=priority)[0]
    return {
        "matched": True,
        "confidence": 0.9 if candidate.provider == "sec" else 0.88,
        "needs_human_review": False,
        "description": candidate.description,
        "website": candidate.website,
        "location_city": candidate.city,
        "state": candidate.state,
        "country": candidate.country,
        "source_url": candidate.source_url or candidate.website,
        "evidence_summary": (
            f"Exact {candidate.provider} structured candidate '{candidate.name}' "
            "matches the actor without Claude validation."
        ),
    }


def _web_result_rank(candidate: ApiCandidate) -> int:
    match = re.search(r"rank\s+(\d+)", candidate.evidence or "", flags=re.I)
    if not match:
        return 999
    return int(match.group(1))


def _web_result_title_allowed(title: str) -> bool:
    normalized = normalize_text(title)
    return not any(term in normalized for term in WEB_RESULT_TITLE_BLOCKLIST)


def _web_candidate_is_strong_official_match(actor: Actor, candidate: ApiCandidate) -> bool:
    if candidate.provider != "duckduckgo_search" or not candidate.website:
        return False
    actor_tokens = set(normalize_text(actor.name).split())
    if not has_specific_name_signal(actor.name) and actor_tokens & WEB_AUTO_APPLY_GENERIC_TOKENS:
        return False
    if _web_result_rank(candidate) > WEB_AUTO_APPLY_MAX_RANK:
        return False
    if not _web_result_title_allowed(candidate.name):
        return False
    if TrustedApiSearcher._web_result_domain_blocked(candidate.website):
        return False
    if _candidate_match_score(actor, candidate) < WEB_AUTO_APPLY_MIN_SCORE:
        return False

    annotations = _parenthetical_annotations(actor.name)
    if annotations:
        base_name = re.sub(r"\([^)]*\)", "", actor.name or "").strip()
        searchable = normalize_text(f"{candidate.name} {candidate.website}")
        for note in annotations:
            if _annotation_is_acronym_for_name(note, base_name):
                continue
            note_terms = distinctive_tokens(note) - {
                "ai",
                "regional",
                "presence",
                "operations",
                "systems",
                "facilities",
                "facility",
                "hub",
                "space",
            }
            if note_terms and not all(term in searchable for term in note_terms):
                return False
    return True


def build_high_confidence_web_candidate_decision(
    actor: Actor,
    candidates: list[ApiCandidate],
    target_fields: Optional[tuple[str, ...]] = None,
) -> Optional[dict]:
    fields = target_fields or ENRICHMENT_TARGET_FIELDS
    if "website" not in fields or actor.website:
        return None
    if is_aggregate_actor_name(actor.name, actor.actor_type):
        return None

    matches = [
        candidate
        for candidate in candidates
        if _web_candidate_is_strong_official_match(actor, candidate)
    ]
    if not matches:
        return None

    candidate = sorted(
        matches,
        key=lambda item: (_web_result_rank(item), -_candidate_match_score(actor, item)),
    )[0]
    return {
        "matched": True,
        "confidence": 0.88,
        "needs_human_review": False,
        "description": None,
        "website": candidate.website,
        "location_city": None,
        "state": None,
        "country": None,
        "source_url": candidate.source_url or candidate.website,
        "evidence_summary": (
            f"High-confidence DuckDuckGo official website result '{candidate.name}' "
            f"matches the actor at rank {_web_result_rank(candidate)}."
        ),
    }


def _extract_urls(text: str) -> list[str]:
    return [url.rstrip(").,;") for url in re.findall(r"https?://[^\s)]+", text or "")]


def _official_link_for_actor(actor_name: str, source_links: str) -> Optional[str]:
    for match in re.finditer(r"https?://[^\s)]+", source_links or ""):
        url = match.group(0).rstrip(").,;")
        context_start = max(0, match.start() - 180)
        context = source_links[context_start:match.start()]
        if "official" in context.lower() or name_similarity(actor_name, context) >= 0.8:
            return url
    return None


def compact_json(data: object, limit: int = 6000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return text[:limit]


class TrustedApiSearcher:
    """Search trusted structured organization APIs."""

    def __init__(
        self,
        sleep_seconds: float = 0.2,
        openalex_sleep_seconds: float = 2.0,
        web_search_sleep_seconds: float = 0.5,
        web_search_result_limit: int = 3,
        use_wikidata: bool = False,
        use_openalex: bool = True,
        use_web_search: bool = False,
    ):
        self.sleep_seconds = sleep_seconds
        self.openalex_sleep_seconds = openalex_sleep_seconds
        self.web_search_sleep_seconds = max(0.0, web_search_sleep_seconds)
        self.web_search_result_limit = max(1, min(5, web_search_result_limit))
        self.use_wikidata = use_wikidata
        self.use_openalex = use_openalex
        self.use_web_search = use_web_search
        self._openalex_blocked_until = 0.0
        self._sec_companies: Optional[list[dict]] = None
        self.client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def search(self, actor: Actor, hubs: list[Hub]) -> tuple[list[ApiCandidate], int]:
        failures = 0
        candidates: list[ApiCandidate] = []
        for query_name in search_name_variants(actor.name):
            search_fns = [self._search_ror]
            if self.use_openalex and time.time() >= self._openalex_blocked_until:
                search_fns.append(self._search_openalex)
            search_fns.append(self._search_sec)
            if self.use_wikidata:
                search_fns.append(self._search_wikidata)
            for fn in search_fns:
                try:
                    candidates.extend(fn(query_name))
                except httpx.HTTPStatusError as err:
                    failures += 1
                    if fn.__name__ == "_search_wikidata" and err.response.status_code == 403:
                        self.use_wikidata = False
                        logger.warning("Wikidata returned 403; disabling Wikidata for the rest of this run")
                        continue
                    logger.warning("API search failed for %s via %s: %s",
                                   query_name, fn.__name__, err)
                except httpx.HTTPError as err:
                    failures += 1
                    logger.warning("API search failed for %s via %s: %s",
                                   query_name, fn.__name__, err)
                delay = self.openalex_sleep_seconds if fn.__name__ == "_search_openalex" else self.sleep_seconds
                time.sleep(delay)

        if self.use_web_search and not is_aggregate_actor_name(actor.name, actor.actor_type):
            try:
                candidates.extend(self._search_web(actor.name))
            except httpx.HTTPError as err:
                failures += 1
                logger.warning("Web search failed for %s: %s", actor.name, err)
            time.sleep(self.web_search_sleep_seconds)

        candidates.extend(self._hub_website_candidates(actor.name, hubs))
        return self._dedupe(candidates), failures

    def _get_json(
        self,
        url: str,
        *,
        params: dict,
        provider: str,
        retries: int = 2,
        rate_limit_delay: float = 20.0,
    ) -> dict:
        last_response = None
        for attempt in range(retries + 1):
            response = self.client.get(url, params=params)
            last_response = response
            if response.status_code == 429 and attempt < retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else rate_limit_delay * (attempt + 1)
                except ValueError:
                    delay = rate_limit_delay * (attempt + 1)
                if provider == "OpenAlex" and delay > OPENALEX_MAX_RETRY_AFTER:
                    self._openalex_blocked_until = time.time() + delay
                    logger.warning(
                        "OpenAlex requested %.0fs cooldown; skipping OpenAlex for the rest of this run",
                        delay,
                    )
                    response.raise_for_status()
                logger.warning("%s rate-limited; sleeping %.1fs before retry", provider, delay)
                time.sleep(delay)
                continue
            if response.status_code >= 500 and attempt < retries:
                delay = min(15.0, 3.0 * (attempt + 1))
                logger.warning("%s returned %s; sleeping %.1fs before retry",
                               provider, response.status_code, delay)
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response.json()

        assert last_response is not None
        last_response.raise_for_status()
        return {}

    def _search_web(self, actor_name: str) -> list[ApiCandidate]:
        queries: list[str] = []
        for variant in (
            actor_name,
            re.sub(r"\([^)]*\)", "", actor_name or "").strip(),
        ):
            cleaned = re.sub(r"\s+", " ", variant or "").strip(" -,:;")
            key = normalize_text(cleaned)
            if cleaned and key and key not in {normalize_text(q) for q in queries}:
                queries.append(cleaned)

        out: list[ApiCandidate] = []
        for query_name in queries[:2]:
            payload = self.client.get(
                DUCKDUCKGO_HTML_URL,
                params={"q": f"{query_name} official website"},
                headers={"User-Agent": f"Mozilla/5.0 {USER_AGENT}"},
            )
            payload.raise_for_status()
            out.extend(self._duckduckgo_result_candidates(query_name, payload.text))
            time.sleep(self.web_search_sleep_seconds)
            if len(out) >= self.web_search_result_limit:
                break
        return out[: self.web_search_result_limit]

    def _duckduckgo_result_candidates(self, query_name: str, text: str) -> list[ApiCandidate]:
        out: list[ApiCandidate] = []
        for rank, match in enumerate(
            re.finditer(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                text or "",
                flags=re.S,
            ),
            1,
        ):
            raw_url = html.unescape(match.group(1))
            url = self._duckduckgo_result_url(raw_url)
            if not url or self._web_result_domain_blocked(url):
                continue
            title = html.unescape(re.sub(r"<.*?>", "", match.group(2))).strip()
            if not title:
                continue
            out.append(ApiCandidate(
                provider="duckduckgo_search",
                name=title[:250],
                website=url[:500],
                source_url=url[:1000],
                evidence=(
                    f"DuckDuckGo result rank {rank} for query "
                    f"'{query_name} official website'."
                ),
            ))
            if len(out) >= self.web_search_result_limit:
                break
        return out

    @staticmethod
    def _duckduckgo_result_url(raw_url: str) -> Optional[str]:
        url = (raw_url or "").strip()
        if not url:
            return None
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "uddg" in params and params["uddg"]:
            url = params["uddg"][0]
        if not url.startswith(("http://", "https://")):
            return None
        return url.rstrip(").,;")

    @staticmethod
    def _web_result_domain_blocked(url: str) -> bool:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == domain or host.endswith("." + domain) for domain in BLOCKED_WEB_RESULT_DOMAINS)

    def _search_ror(self, name: str) -> list[ApiCandidate]:
        payload = self._get_json(
            "https://api.ror.org/organizations",
            params={"query": name},
            provider="ROR",
            retries=2,
            rate_limit_delay=10.0,
        )
        items = payload.get("items", [])[:5]
        out: list[ApiCandidate] = []
        for item in items:
            names = item.get("names") or []
            display = self._ror_display_name(names) or item.get("name") or ""
            links = item.get("links") or []
            website = self._first_link(links)
            locations = item.get("locations") or []
            city = state = country = None
            if locations:
                geo = (locations[0] or {}).get("geonames_details") or {}
                city = geo.get("name")
                state = geo.get("admin1_name")
                country = geo.get("country_name")
            aliases = [
                n.get("value") for n in names
                if isinstance(n, dict) and n.get("types") and "alias" in n.get("types", [])
            ]
            out.append(ApiCandidate(
                provider="ror",
                name=display,
                website=website,
                city=city,
                state=state,
                country=country,
                source_url=item.get("id"),
                evidence=f"ROR record aliases={', '.join(a for a in aliases if a)[:250]}",
            ))
        return out

    def _search_wikidata(self, name: str) -> list[ApiCandidate]:
        search_payload = self._get_json(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "type": "item",
                "search": name,
                "limit": 5,
            },
            provider="Wikidata",
            retries=1,
            rate_limit_delay=20.0,
        )
        search_items = search_payload.get("search", [])
        ids = [item.get("id") for item in search_items if item.get("id")]
        if not ids:
            return []

        entity_payload = self._get_json(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "languages": "en",
                "props": "labels|descriptions|claims|sitelinks",
                "ids": "|".join(ids),
            },
            provider="Wikidata",
            retries=1,
            rate_limit_delay=20.0,
        )
        entities = entity_payload.get("entities", {})

        out: list[ApiCandidate] = []
        for item in search_items:
            qid = item.get("id")
            entity = entities.get(qid, {})
            claims = entity.get("claims") or {}
            website = self._wikidata_string_claim(claims, "P856")
            label = (
                ((entity.get("labels") or {}).get("en") or {}).get("value")
                or item.get("label")
                or ""
            )
            description = (
                ((entity.get("descriptions") or {}).get("en") or {}).get("value")
                or item.get("description")
            )
            out.append(ApiCandidate(
                provider="wikidata",
                name=label,
                website=website,
                description=description,
                source_url=f"https://www.wikidata.org/wiki/{qid}" if qid else None,
                evidence=f"Wikidata entity {qid}: {description or ''}",
            ))
        return out

    @staticmethod
    def _wikidata_string_claim(claims: dict, prop: str) -> Optional[str]:
        for claim in claims.get(prop, []):
            mainsnak = claim.get("mainsnak") or {}
            datavalue = mainsnak.get("datavalue") or {}
            value = datavalue.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _ror_display_name(names: list[dict]) -> Optional[str]:
        for wanted in ("ror_display", "label"):
            for item in names:
                if isinstance(item, dict) and wanted in item.get("types", []):
                    return item.get("value")
        return None

    @staticmethod
    def _first_link(links: list) -> Optional[str]:
        for link in links:
            if isinstance(link, dict) and link.get("type") in ("website", "homepage"):
                return link.get("value")
            if isinstance(link, str):
                return link
        return None

    def _search_openalex(self, name: str) -> list[ApiCandidate]:
        payload = self._get_json(
            "https://api.openalex.org/institutions",
            params={"search": name, "per-page": 5},
            provider="OpenAlex",
            retries=3,
            rate_limit_delay=30.0,
        )
        items = payload.get("results", [])[:5]
        out: list[ApiCandidate] = []
        for item in items:
            geo = item.get("geo") or {}
            out.append(ApiCandidate(
                provider="openalex",
                name=item.get("display_name") or "",
                website=item.get("homepage_url"),
                city=geo.get("city"),
                state=geo.get("region"),
                country=geo.get("country"),
                source_url=item.get("id"),
                evidence=(
                    f"OpenAlex institution type={item.get('type')}; "
                    f"works_count={item.get('works_count')}"
                ),
            ))
        return out

    def _load_sec_companies(self) -> list[dict]:
        if self._sec_companies is not None:
            return self._sec_companies
        payload = self._get_json(
            SEC_COMPANY_TICKERS_URL,
            params={},
            provider="SEC",
            retries=2,
            rate_limit_delay=10.0,
        )
        self._sec_companies = list(payload.values()) if isinstance(payload, dict) else []
        return self._sec_companies

    def _search_sec(self, name: str) -> list[ApiCandidate]:
        out: list[ApiCandidate] = []
        for item in self._load_sec_companies():
            title = item.get("title") or ""
            ticker = item.get("ticker") or ""
            score = max(name_similarity(name, title), name_similarity(name, ticker))
            if score < 0.8:
                continue
            cik = str(item.get("cik_str") or "").zfill(10)
            out.append(ApiCandidate(
                provider="sec",
                name=title,
                description=(
                    f"SEC registrant record for public company {title}"
                    + (f" ({ticker})" if ticker else "")
                    + "."
                ),
                source_url=f"https://www.sec.gov/edgar/browse/?CIK={cik}" if cik else None,
                evidence=f"SEC company ticker registry; ticker={ticker}; cik={cik}",
            ))
        return out[:5]

    def _hub_website_candidates(self, actor_name: str, hubs: list[Hub]) -> list[ApiCandidate]:
        out: list[ApiCandidate] = []
        for hub in hubs:
            for url, label in self._url_label_pairs_v2(hub.official_websites or ""):
                if self._label_matches(actor_name, label):
                    out.append(ApiCandidate(
                        provider="hub_official_websites",
                        name=label or actor_name,
                        website=url,
                        source_url=url,
                        evidence=f"Listed in official websites text for hub: {hub.name}",
                    ))
        return out

    @staticmethod
    def _url_label_pairs_v2(text: str) -> list[tuple[str, str]]:
        url_re = re.compile(r"https?://[^\s]+")
        matches = list(url_re.finditer(text or ""))
        pairs = []
        for idx, match in enumerate(matches):
            url = match.group(0).rstrip(").,;")
            prev_end = matches[idx - 1].end() if idx else 0
            next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            label = TrustedApiSearcher._clean_url_label(text[prev_end:match.start()])
            if not label:
                label = TrustedApiSearcher._clean_url_label(text[match.end():next_start])
            if label:
                pairs.append((url, label[:180]))
        return pairs

    @staticmethod
    def _clean_url_label(text: str) -> str:
        label = re.sub(r"\s+", " ", text or "").strip(" -–—|:;,. \n\r\t")
        if not label or label.startswith("http"):
            return ""
        return label[-180:]

    @staticmethod
    def _url_label_pairs(text: str) -> list[tuple[str, str]]:
        url_re = re.compile(r"https?://[^\s]+")
        matches = list(url_re.finditer(text or ""))
        pairs = []
        for idx, match in enumerate(matches):
            label_start = match.end()
            label_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            url = match.group(0).rstrip(").,;")
            label = text[label_start:label_end].strip(" -–—|:;,. \n\r\t")
            if label:
                pairs.append((url, label[:180]))
        return pairs

    @staticmethod
    def _label_matches(actor_name: str, label: str) -> bool:
        stop = {
            "of", "and", "the", "for", "at", "in", "on", "with",
            "department", "college", "school", "center", "centre",
            "institute", "university",
        }
        actor_terms = {w for w in normalize_text(actor_name).split() if len(w) > 2 and w not in stop}
        label_terms = {w for w in normalize_text(label).split() if len(w) > 2 and w not in stop}
        overlap = actor_terms & label_terms
        if len(overlap) >= 2 and (
            len(overlap) / max(1, len(actor_terms)) >= 0.65
            or len(overlap) / max(1, len(label_terms)) >= 0.65
        ):
            return True
        for acronym in acronym_candidates(actor_name):
            if re.search(r"\b" + re.escape(acronym) + r"\b", label):
                return True
        return False

    @staticmethod
    def _dedupe(candidates: list[ApiCandidate]) -> list[ApiCandidate]:
        seen = set()
        out = []
        for candidate in candidates:
            key = (
                candidate.provider,
                normalize_text(candidate.name),
                candidate.website or "",
                candidate.source_url or "",
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
        return out[:12]


SYSTEM_PROMPT = """You validate organization enrichment candidates for a database.

You are evidence-bound. Use ONLY the supplied candidate records and hub context.
Do not invent a website, description, or location. If no candidate clearly
matches the actor, return matched=false.

Rules:
- The candidate must refer to the same organization as the actor, not merely a
  parent institution, nearby hub, funder, collaborator, or different unit.
- A parent institution is acceptable only when the actor itself is the parent
  institution. For departments/labs/centers, prefer an exact subunit match.
- For corporate R&D/lab names, a clearly matching parent company is acceptable
  for website, location, and company description when the actor name is just the
  company's research unit (for example "3M Research Laboratories" -> "3M").
- Official websites may come from ROR, OpenAlex, Wikidata, DuckDuckGo search
  candidates, or a hub official-websites listing if the label/title clearly
  matches the actor.
- If the actor website is missing and you select a matching candidate that has
  a website, copy that exact candidate website. Do not return matched=true with
  website=null unless no matching candidate has a supported website.
- For DuckDuckGo search candidates, accept only the official organization site,
  not articles, databases, social pages, directories, or unrelated product pages.
  When accepted, use the DuckDuckGo candidate's website as source_url too.
- Description must be a concise, neutral sentence grounded in the candidate
  evidence. If evidence is too thin, return null.
- Location fields must come from the selected candidate, not the hub location.
- Return null for any field not supported by evidence.

Return ONLY JSON with this exact shape:
{
  "matched": true,
  "confidence": 0.0,
  "needs_human_review": true,
  "description": null,
  "website": null,
  "location_city": null,
  "state": null,
  "country": null,
  "source_url": null,
  "evidence_summary": "short reason"
}
"""


def build_user_prompt(actor: Actor, hubs: list[Hub], candidates: list[ApiCandidate]) -> str:
    hub_payload = [
        {
            "name": hub.name,
            "city": hub.primary_city,
            "state": hub.state,
            "country": hub.country,
            "core_topic_strengths": (hub.core_topic_strengths or "")[:800],
        }
        for hub in hubs[:5]
    ]
    actor_payload = {
        "actor_id": str(actor.actor_id),
        "name": actor.name,
        "actor_type": actor.actor_type,
        "existing_description": actor.description,
        "existing_website": actor.website,
        "existing_location_city": actor.location_city,
        "existing_state": actor.state,
        "existing_country": actor.country,
    }
    candidate_payload = [candidate.as_prompt_dict() for candidate in candidates]
    return (
        "Actor to enrich:\n"
        f"{compact_json(actor_payload, 1200)}\n\n"
        "Linked hub context:\n"
        f"{compact_json(hub_payload, 2000)}\n\n"
        "Candidate source records:\n"
        f"{compact_json(candidate_payload, 7000)}\n\n"
        "Validate whether any candidate is the same organization as the actor."
    )


class ActorEnrichmentCandidatePipeline:
    def __init__(
        self,
        project_root: Path,
        session: Session,
        *,
        limit: Optional[int] = None,
        apply: bool = False,
        apply_threshold: float = DEFAULT_APPLY_THRESHOLD,
        commit_every: int = 50,
        model: str = SONNET,
        use_wikidata: bool = False,
        use_openalex: bool = True,
        openalex_sleep_seconds: float = 2.0,
        use_web_search: bool = False,
        web_search_sleep_seconds: float = 0.5,
        web_search_result_limit: int = 3,
        include_unlinked: bool = False,
        deterministic_only: bool = False,
        revisit_missing: bool = False,
        use_claude: bool = False,
        max_claude_calls: Optional[int] = 25,
        max_claude_cost: Optional[float] = 0.50,
        min_claude_candidate_score: float = 0.72,
        missing_fields: Optional[list[str]] = None,
        stop_after_claude_budget: bool = False,
    ):
        self.project_root = project_root
        self.session = session
        self.limit = limit
        self.apply = apply
        self.apply_threshold = apply_threshold
        self.commit_every = max(0, commit_every)
        self.include_unlinked = include_unlinked
        self.deterministic_only = deterministic_only
        self.revisit_missing = revisit_missing
        self.use_claude = use_claude
        self.max_claude_calls = (
            None if max_claude_calls is None or max_claude_calls < 0 else max_claude_calls
        )
        self.max_claude_cost = (
            None if max_claude_cost is None or max_claude_cost < 0 else max_claude_cost
        )
        self.min_claude_candidate_score = max(0.0, min(1.0, min_claude_candidate_score))
        self.missing_fields = normalize_missing_fields(missing_fields)
        self.stop_after_claude_budget = stop_after_claude_budget
        self._stop_requested = False
        self.model = model
        self.tracker = UsageTracker(model=model)
        self.stats = RunStats()
        self._all_hubs_cache: Optional[list[Hub]] = None
        self.searcher = TrustedApiSearcher(
            use_wikidata=use_wikidata,
            use_openalex=use_openalex,
            openalex_sleep_seconds=openalex_sleep_seconds,
            use_web_search=use_web_search,
            web_search_sleep_seconds=web_search_sleep_seconds,
            web_search_result_limit=web_search_result_limit,
        )

        log_path = project_root / AUDIT_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        audit_mode = "a" if apply and log_path.exists() else "w"
        write_header = audit_mode == "w" or log_path.stat().st_size == 0
        self.audit_fh = open(log_path, audit_mode, newline="", encoding="utf-8")
        self.audit_writer = csv.writer(self.audit_fh)
        if write_header:
            self.audit_writer.writerow([
                "actor_id", "actor_name", "actor_type", "hub_names",
                "candidate_count", "matched", "confidence", "needs_human_review",
                "description", "website", "location_city", "state", "country",
                "source_url", "evidence_summary", "action",
            ])

    def close(self) -> None:
        self.searcher.close()
        if not self.audit_fh.closed:
            self.audit_fh.close()

    def _reset_session_after_db_error(self) -> None:
        try:
            self.session.rollback()
        except Exception:
            logger.debug("Rollback failed while recovering from DB error", exc_info=True)
        self.session.close()

    def _load_actor_ids(self) -> list[uuid.UUID]:
        for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
            try:
                return [
                    actor.actor_id
                    for actor in self.session.execute(self._sparse_actor_query()).scalars().all()
                ]
            except OperationalError as err:
                self._reset_session_after_db_error()
                if attempt == DB_RETRY_ATTEMPTS:
                    raise
                sleep_seconds = DB_RETRY_SLEEP_SECONDS * attempt
                logger.warning(
                    "DB connection failed while loading actors; retrying in %.1fs (%d/%d): %s",
                    sleep_seconds,
                    attempt,
                    DB_RETRY_ATTEMPTS,
                    err,
                )
                time.sleep(sleep_seconds)
        return []

    def _missing_target_field_condition(self):
        conditions = []
        for field in self.missing_fields:
            column = Actor.location_city if field == "location_city" else getattr(Actor, field)
            conditions.extend((column.is_(None), column == ""))
        return or_(*conditions)

    def _sparse_actor_query(self):
        has_hub_link = exists(
            select(HubActor.actor_id).where(HubActor.actor_id == Actor.actor_id)
        )
        already_processed_by_pipeline = exists(
            select(Source.source_id).where(
                Source.source_id == Actor.source_id,
                Source.source_type == "ai_inference",
                or_(
                    Source.description.like("AI/API actor enrichment candidate for %"),
                    Source.description.like("Curated official actor enrichment for %"),
                    Source.description.like("Official website actor enrichment for %"),
                    Source.description.like("Web-search official website enrichment for %"),
                    Source.description.like("Name-context aggregate actor enrichment for %"),
                    Source.description.like("Hub-context aggregate actor enrichment for %"),
                    Source.description.like("Hub-context actor enrichment for %"),
                    Source.description.like("Relevance-context actor enrichment for %"),
                ),
            )
        )
        filters = [self._missing_target_field_condition()]
        if not self.revisit_missing:
            filters.append(~already_processed_by_pipeline)
        if not self.include_unlinked:
            filters.append(has_hub_link)
        query = select(Actor).where(and_(*filters)).order_by(Actor.name)
        if self.limit:
            query = query.limit(self.limit)
        return query

    def _actor_hubs(self, actor: Actor) -> list[Hub]:
        return self.session.execute(
            select(Hub)
            .join(HubActor, HubActor.hub_id == Hub.hub_id)
            .where(HubActor.actor_id == actor.actor_id)
            .order_by(Hub.name)
        ).scalars().all()

    def _all_hubs(self) -> list[Hub]:
        if self._all_hubs_cache is None:
            self._all_hubs_cache = self.session.execute(
                select(Hub).where(Hub.official_websites.is_not(None)).order_by(Hub.name)
            ).scalars().all()
        return self._all_hubs_cache

    def _relevance_context_decision(self, actor: Actor) -> Optional[dict]:
        rows = self.session.execute(
            select(ActorRelevance, Challenge)
            .outerjoin(Challenge, Challenge.challenge_id == ActorRelevance.challenge_id)
            .where(ActorRelevance.actor_id == actor.actor_id)
            .order_by(Challenge.name)
        ).all()
        if not rows:
            return None

        challenge_names = []
        evidence_parts = []
        link_parts = []
        for relevance, challenge in rows:
            if challenge and challenge.name:
                challenge_names.append(challenge.name)
            for attr in (
                "current_evidence",
                "why_relevant",
                "challenge_relevance_narrative",
            ):
                value = getattr(relevance, attr, None)
                if value:
                    evidence_parts.append(value)
            if relevance.source_links:
                link_parts.append(relevance.source_links)

        links_text = " ".join(link_parts)
        evidence_text = _clean_context_snippet(" ".join(evidence_parts), 360)
        if not evidence_text and not links_text:
            return None

        challenge_label = _join_names(challenge_names, limit=2)
        actor_type = (actor.actor_type or "actor").replace("_", " ")
        if evidence_text:
            description = (
                f"{actor.name} is tracked as a {actor_type} in the "
                f"{challenge_label} challenge context; evidence notes {evidence_text}."
            )
        else:
            description = (
                f"{actor.name} is tracked as a {actor_type} in the "
                f"{challenge_label} challenge context with supporting source links."
            )
        source_url = (_extract_urls(links_text) or [f"relevance_context://actor/{actor.actor_id}"])[0]
        website = _official_link_for_actor(actor.name, links_text)
        return {
            "matched": True,
            "confidence": 0.88,
            "needs_human_review": False,
            "description": description[:1000],
            "website": website,
            "location_city": None,
            "state": None,
            "country": None,
            "source_url": source_url,
            "evidence_summary": "Actor relevance evidence/source links from the challenge context.",
        }

    def _write_audit_row(
        self,
        actor: Actor,
        hub_names: list[str],
        candidate_count: int,
        decision: dict,
        action: str,
    ) -> None:
        self.audit_writer.writerow([
            actor.actor_id, actor.name, actor.actor_type, " | ".join(hub_names),
            candidate_count, decision["matched"], decision["confidence"],
            decision["needs_human_review"], decision["description"],
            decision["website"], decision["location_city"], decision["state"],
            decision["country"], decision["source_url"],
            decision["evidence_summary"], action,
        ])
        self.audit_fh.flush()

    def _get_or_create_source(self, actor: Actor, decision: dict) -> Source:
        source_url = decision.get("source_url")
        if source_url and str(source_url).startswith("hub_context://aggregate_actor/"):
            description = f"Hub-context aggregate actor enrichment for {actor.name}"
        elif source_url and str(source_url).startswith("name_context://aggregate_actor/"):
            description = f"Name-context aggregate actor enrichment for {actor.name}"
        elif source_url and str(source_url).startswith("hub_context://actor/"):
            description = f"Hub-context actor enrichment for {actor.name}"
        elif str(decision.get("evidence_summary") or "").startswith("Exact curated official"):
            description = f"Curated official actor enrichment for {actor.name}"
        elif str(decision.get("evidence_summary") or "").startswith("Exact official website"):
            description = f"Official website actor enrichment for {actor.name}"
        elif str(decision.get("evidence_summary") or "").startswith(
            "High-confidence DuckDuckGo official website"
        ):
            description = f"Web-search official website enrichment for {actor.name}"
        elif (
            source_url and str(source_url).startswith("relevance_context://actor/")
        ) or str(decision.get("evidence_summary") or "").startswith("Actor relevance"):
            description = f"Relevance-context actor enrichment for {actor.name}"
        else:
            description = (
                f"AI/API actor enrichment candidate for {actor.name} "
                f"({self.model})"
            )
        existing = self.session.execute(
            select(Source).where(
                Source.source_type == "ai_inference",
                Source.url == source_url,
                Source.description == description,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        source = Source(
            source_id=uuid.uuid4(),
            source_type="ai_inference",
            url=source_url,
            retrieved_at=datetime.now(),
            description=description,
            trust_tier="candidate",
        )
        self.session.add(source)
        self.session.flush()
        return source

    @staticmethod
    def _clean_decision(raw: Optional[dict]) -> Optional[dict]:
        if not raw:
            return None
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "matched": bool(raw.get("matched")),
            "confidence": confidence,
            "needs_human_review": bool(raw.get("needs_human_review", True)),
            "description": _optional_str(raw.get("description"), 1000),
            "website": _optional_str(raw.get("website"), 500),
            "location_city": _optional_str(raw.get("location_city"), 120),
            "state": _optional_str(raw.get("state"), 80),
            "country": _optional_str(raw.get("country"), 80),
            "source_url": _optional_str(raw.get("source_url"), 1000),
            "evidence_summary": _optional_str(raw.get("evidence_summary"), 500) or "",
        }

    @staticmethod
    def _stabilize_decision(
        actor: Actor,
        candidates: list[ApiCandidate],
        decision: dict,
    ) -> dict:
        """Apply deterministic confidence rules for exact structured matches."""
        if not decision["matched"] or not decision.get("source_url"):
            return decision

        if decision.get("website"):
            website_key = _canonical_url_key(decision["website"])
            for candidate in candidates:
                if candidate.website and _canonical_url_key(candidate.website) == website_key:
                    decision["source_url"] = candidate.source_url or candidate.website
                    break

        for candidate in candidates:
            if candidate.source_url != decision["source_url"]:
                continue
            if candidate.provider == "duckduckgo_search" and candidate.website:
                score = _candidate_match_score(actor, candidate)
                if score >= 0.85:
                    decision["confidence"] = max(decision["confidence"], 0.86)
                    decision["needs_human_review"] = False
                return decision
            if (
                candidate.provider == "hub_official_websites"
                and candidate.website
                and _official_label_directly_names_actor(actor.name, candidate.name)
            ):
                decision["confidence"] = max(decision["confidence"], 0.88)
                decision["needs_human_review"] = False
                if not decision.get("description"):
                    decision["description"] = (
                        f"{actor.name} is an organization or program identified through "
                        "official GHUS ecosystem website context."
                    )
                return decision
            if (
                candidate.provider in {"ror", "openalex"}
                and candidate.website
                and name_similarity(actor.name, candidate.name) >= 0.95
            ):
                decision["confidence"] = max(decision["confidence"], 0.88)
                decision["needs_human_review"] = False
                if not decision.get("description") and candidate.description:
                    decision["description"] = candidate.description
                return decision
            if candidate.provider != "sec":
                continue
            # SEC records are kept as evidence for Claude/human validation, but
            # are not strong enough alone for deterministic auto-apply: ticker
            # registries can false-match short names and acronyms.
            continue
        return decision

    def _apply_decision(self, actor: Actor, decision: dict) -> str:
        if not decision["matched"]:
            self.stats.no_match += 1
            return "no_match"
        if decision["confidence"] < self.apply_threshold:
            self.stats.skipped_low_confidence += 1
            return "low_confidence"
        if decision["needs_human_review"]:
            self.stats.needs_review += 1
            return "human_review"

        target_fields = ("description", "website", "location_city", "state", "country")
        would_change = any(
            decision.get(attr) and not getattr(actor, attr)
            for attr in target_fields
        )
        if not would_change:
            return "validated_no_update"

        self.stats.would_apply += 1
        if not self.apply:
            return "would_apply"

        changed = False
        for attr in target_fields:
            value = decision.get(attr)
            if value and not getattr(actor, attr):
                setattr(actor, attr, value)
                changed = True

        source = self._get_or_create_source(actor, decision)
        actor.source_id = source.source_id
        actor.verification_status = "ai_inferred"
        actor.confidence = AI_CONFIDENCE
        self.stats.applied += 1
        if not changed:
            return "validated_no_update"
        return "applied"

    def _claude_preflight(
        self,
        actor: Actor,
        candidates: list[ApiCandidate],
    ) -> tuple[bool, str, str]:
        if not self.use_claude:
            return (
                False,
                "Claude validation is disabled for this run; candidates require API-only or human validation.",
                "disabled",
            )
        if self.max_claude_calls is not None and self.tracker.calls >= self.max_claude_calls:
            return (
                False,
                f"Claude call budget exhausted ({self.tracker.calls}/{self.max_claude_calls}).",
                "budget",
            )
        if self.max_claude_cost is not None and self.tracker.cost_estimate() >= self.max_claude_cost:
            return (
                False,
                f"Claude cost budget exhausted (${self.tracker.cost_estimate():.4f}/${self.max_claude_cost:.4f}).",
                "budget",
            )

        useful_scores = [
            _candidate_match_score(actor, candidate)
            for candidate in candidates
            if _candidate_can_fill_missing_field(actor, candidate, self.missing_fields)
        ]
        if not useful_scores:
            return (
                False,
                "No candidate contains values for the actor fields that are still missing.",
                "weak",
            )

        best_score = max(useful_scores)
        if best_score < self.min_claude_candidate_score:
            return (
                False,
                (
                    f"Best candidate score {best_score:.2f} is below the Claude gate "
                    f"{self.min_claude_candidate_score:.2f}."
                ),
                "weak",
            )

        return True, "", ""

    def _write_claude_skip(
        self,
        actor: Actor,
        hubs: list[Hub],
        hub_names: list[str],
        candidates: list[ApiCandidate],
        reason: str,
        kind: str,
    ) -> None:
        self.stats.claude_skipped += 1
        if kind == "budget":
            self.stats.claude_budget_skipped += 1
            if self.stop_after_claude_budget:
                self._stop_requested = True
        elif kind == "weak":
            self.stats.claude_weak_candidate_skipped += 1

        if hubs:
            decision = build_hub_context_actor_decision(
                actor,
                hubs,
                f"{reason} Applied hub-context-only enrichment without Claude.",
            )
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, len(candidates), decision, action)
            return

        decision = build_unresolved_actor_decision(reason)
        self._write_audit_row(
            actor,
            hub_names,
            len(candidates),
            decision,
            "claude_skipped_cost_control",
        )

    def _process_actor(self, actor: Actor) -> None:
        hubs = self._actor_hubs(actor)
        hub_names = [hub.name for hub in hubs]

        decision = build_known_official_actor_decision(actor)
        if decision:
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, 1, decision, action)
            return

        local_candidates: list[ApiCandidate] = []
        local_hubs = hubs if hubs else (self._all_hubs() if self.include_unlinked else [])
        if local_hubs:
            local_candidates = self.searcher._hub_website_candidates(actor.name, local_hubs)
            decision = build_exact_official_website_decision(actor, local_candidates)
            if decision:
                self.stats.decisions_made += 1
                self.stats.candidates_found += len(local_candidates)
                action = self._apply_decision(actor, decision)
                self._write_audit_row(actor, hub_names, len(local_candidates), decision, action)
                return

        if not hubs:
            decision = self._relevance_context_decision(actor)
            if decision:
                self.stats.decisions_made += 1
                action = self._apply_decision(actor, decision)
                self._write_audit_row(actor, hub_names, 1, decision, action)
                return

        if is_aggregate_actor_name(actor.name, actor.actor_type):
            if not hubs:
                decision = build_name_context_aggregate_actor_decision(actor)
                self.stats.decisions_made += 1
                action = self._apply_decision(actor, decision)
                self._write_audit_row(actor, hub_names, 0, decision, action)
                return
            decision = build_aggregate_actor_decision(actor, hubs)
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, 0, decision, action)
            return

        if self.deterministic_only:
            decision = build_unresolved_actor_decision(
                "Deterministic-only run found no local curated, relevance, aggregate, or exact official-website match."
            )
            self.stats.no_candidates += 1
            self.stats.candidates_found += len(local_candidates)
            self._write_audit_row(
                actor,
                hub_names,
                len(local_candidates),
                decision,
                "needs_api_or_human_validation",
            )
            return

        candidates, failures = self.searcher.search(actor, hubs)
        if local_candidates:
            candidates.extend(local_candidates)
            candidates = self.searcher._dedupe(candidates)
        self.stats.api_failures += failures
        self.stats.candidates_found += len(candidates)

        if not candidates:
            self.stats.no_candidates += 1
            if not hubs:
                decision = build_unresolved_actor_decision(
                    "No trusted structured API candidates were found and no hub context is linked."
                )
                self._write_audit_row(actor, hub_names, 0, decision, "no_candidates")
                return
            decision = build_hub_context_actor_decision(
                actor,
                hubs,
                "No trusted structured API candidates were found; applied hub-context-only enrichment.",
            )
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, 0, decision, action)
            return

        decision = build_exact_official_website_decision(actor, candidates)
        if decision:
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, len(candidates), decision, action)
            return

        decision = build_high_confidence_api_candidate_decision(actor, candidates, self.missing_fields)
        if decision:
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, len(candidates), decision, action)
            return

        decision = build_high_confidence_web_candidate_decision(actor, candidates, self.missing_fields)
        if decision:
            self.stats.decisions_made += 1
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, len(candidates), decision, action)
            return

        can_call_claude, skip_reason, skip_kind = self._claude_preflight(actor, candidates)
        if not can_call_claude:
            self._write_claude_skip(actor, hubs, hub_names, candidates, skip_reason, skip_kind)
            return

        raw = structured_json(
            SYSTEM_PROMPT,
            build_user_prompt(actor, hubs, candidates),
            model=self.model,
            max_tokens=1200,
            tracker=self.tracker,
        )
        decision = self._clean_decision(raw)
        if not decision:
            self.stats.decisions_made += 1
            if not hubs:
                decision = build_unresolved_actor_decision(
                    "Claude returned invalid JSON and no hub context is linked for fallback."
                )
                self._write_audit_row(actor, hub_names, len(candidates), decision, "ai_invalid")
                return
            decision = build_hub_context_actor_decision(
                actor,
                hubs,
                "Claude returned invalid JSON; applied hub-context-only enrichment instead.",
            )
            action = self._apply_decision(actor, decision)
            self._write_audit_row(actor, hub_names, len(candidates), decision, action)
            return

        self.stats.decisions_made += 1
        decision = self._stabilize_decision(actor, candidates, decision)
        if (
            not decision["matched"]
            or decision["confidence"] < self.apply_threshold
            or decision["needs_human_review"]
        ):
            if not hubs:
                action = self._apply_decision(actor, decision)
                self._write_audit_row(actor, hub_names, len(candidates), decision, action)
                return
            decision = build_hub_context_actor_decision(
                actor,
                hubs,
                (
                    "Structured candidate validation did not produce a high-confidence "
                    "auto-apply match; applied hub-context-only enrichment."
                ),
            )
        action = self._apply_decision(actor, decision)
        self._write_audit_row(actor, hub_names, len(candidates), decision, action)

    def run(self) -> RunStats:
        actor_ids = self._load_actor_ids()
        self.stats.actors_seen = len(actor_ids)
        scope = "sparse actors" if self.include_unlinked else "sparse hub-linked actors"
        logger.info("Processing %d %s", len(actor_ids), scope)

        for idx, actor_id in enumerate(actor_ids, 1):
            for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
                try:
                    actor = self.session.get(Actor, actor_id)
                    if actor is None:
                        logger.info("[%d/%d] actor %s no longer exists; skipping",
                                    idx, len(actor_ids), actor_id)
                        break
                    logger.info("[%d/%d] %s", idx, len(actor_ids), actor.name)
                    self._process_actor(actor)
                    if self.apply and self.commit_every and idx % self.commit_every == 0:
                        self.session.commit()
                        self.session.close()
                        logger.info("Committed checkpoint after %d actors", idx)
                    break
                except OperationalError as err:
                    self._reset_session_after_db_error()
                    if attempt == DB_RETRY_ATTEMPTS:
                        raise
                    sleep_seconds = DB_RETRY_SLEEP_SECONDS * attempt
                    logger.warning(
                        "DB connection failed while processing actor %s; retrying in %.1fs (%d/%d): %s",
                        actor_id,
                        sleep_seconds,
                        attempt,
                        DB_RETRY_ATTEMPTS,
                        err,
                    )
                    time.sleep(sleep_seconds)
            if self._stop_requested:
                self.stats.actors_seen = idx
                self.stats.stopped_early = True
                logger.info("Stopping early after Claude budget was reached")
                break
            if idx % 20 == 0:
                logger.info(
                    "Progress %d/%d, Claude calls %d, Claude cost $%.4f",
                    idx,
                    len(actor_ids),
                    self.tracker.calls,
                    self.tracker.cost_estimate(),
                )

        if self.apply:
            self.session.commit()
        else:
            self.session.rollback()
        self.close()
        return self.stats


def _optional_str(value, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text[:limit]
