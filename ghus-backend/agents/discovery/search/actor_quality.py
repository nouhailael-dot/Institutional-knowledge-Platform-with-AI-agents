"""Actor quality decision: three bands, decided by score AND by hard gates.

WHY A SCORE ALONE WAS NOT ENOUGH
--------------------------------
Measured on 95 rubric-scored actor candidates (isolated demo database, October
2026), the old 0.30 / 0.70 cut-offs auto-accepted more than a quarter of
everything scored, and the auto-accepted set included:

  * "Texas Medical Center Innovation" at 0.96 - read from edegan.com, a
    third-party wiki, while the organisation's own site is tmcinnovation.org
  * "University of California, Davis" at 0.84 - read from empowerinnovation.net
  * a tourism directory (0.84), an advocates' database (0.70), a meetup page
    (0.86) and a hobbyist mineral club (0.74)

The model marked `own_organisational_page = true` for every one of them, so that
rubric item cannot be trusted to catch this. Raising the threshold alone does
not either: the meetup page scored 0.86. What catches them is a small set of
deterministic checks the model cannot talk its way past.

THE DECISION
------------
    score <  auto_low                  -> reject   (never staged, never reviewed)
    score >= auto_high AND all gates   -> accept   (created as PARKED; see below)
    anything else                      -> review   (a GHUS person decides)

    any REJECT gate fails              -> reject, whatever the score

"Accept" means the actor enters the database as a Parked record with a
verify_actor review item. It never means Verified. Only a GHUS person verifies
(Architecture V2 rule 4), and no score or gate changes that.

Every decision carries its reasons, so a reviewer - and a later audit - can see
exactly why a candidate was accepted, held or dropped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agents.common.geography import REGION_STATES, normalize_state

ACCEPT = "auto_high"
REVIEW = "review"
REJECT = "auto_low"

# Calibrated on the measured distribution (median 0.53, p75 0.72). The old
# values were 0.30 and 0.70.
DEFAULT_AUTO_LOW = 0.45
DEFAULT_AUTO_HIGH = 0.80

DEFAULT_MIN_EVIDENCE_ITEMS = 5
DEFAULT_MIN_DESCRIPTION_CHARS = 60
DEFAULT_ACCEPT_MIN_PRIORITY = 0.70
# 6 Nov 2026: accepting without a person also needs a reliable identity (its own
# page, an operating entity, and its website or place stated) and evidenced
# topic work - each judged on its own, not hidden inside one relevance number.
DEFAULT_MIN_IDENTITY_SCORE = 0.83
DEFAULT_MIN_TOPIC_SCORE = 0.5

# A page on a unit's own sub-site or path (energy.mit.edu, /centers/water) whose
# record names only the parent institution: the unit and its parent are mixed up.
_UNIT_PATH = re.compile(r"/(centers?|centres?|institutes?|labs?|laborator(y|ies)|departments?|"
                        r"schools?|colleges?|programs?|initiatives?|research-centers?)(/|$)",
                        re.IGNORECASE)
_INSTITUTION_ONLY = re.compile(
    r"^(the\s+)?((state\s+)?university\s+of\s+[\w .,&'-]+|[\w .,&'-]+\s+(state\s+)?university"
    r"|[\w .,&'-]+\s+college|[\w .,&'-]+\s+institute\s+of\s+technology)$",
    re.IGNORECASE)
_UNIT_WORDS = re.compile(r"\b(center|centre|institute|lab|laboratory|department|school|program|"
                         r"programme|initiative|office|division|consortium|hub)\b", re.IGNORECASE)

# A page that is a list, a calendar entry or an article is ABOUT organisations;
# it is not one. These are matched against the extracted name and the URL path.
_NOT_AN_ORGANISATION_NAME = re.compile(
    r"\b(directory|database|list of|listing|top \d+|best \d+|ranking of|"
    r"meetup|webinar|conference \d{4}|summit \d{4}|job opening|careers? at|"
    r"press release|news release)\b",
    re.IGNORECASE,
)
_NOT_AN_ORGANISATION_PATH = re.compile(
    r"/(directory|directories|listings?|events?|calendar|news|press|blog|"
    r"jobs|careers|webinars?)(/|$)",
    re.IGNORECASE,
)
# A description of a WEB PAGE, not of an organisation: "A regional web portal
# profiling...", "Overview of NYU student involvement...". Held for a person:
# the organisation behind the page may be real, but this page is not its profile.
# (Both were auto-accepted on the stored candidates of 2026-10-14/15.)
_DESCRIBES_A_PAGE = re.compile(
    r"^(?:(?:an?|the)\s+)?(?:[a-z0-9-]+\s+){0,3}?(?:web\s*)?"
    r"(?:portal|directory|database|listing|overview|webpage|web page|landing page)\b"
    r"|^overview of\b",
    re.IGNORECASE,
)
# Taglines are not descriptions: no verb of substance, mostly adjectives.
_TAGLINE = re.compile(
    r"^(innovating|empowering|building|shaping|driving|creating|leading)\b.{0,40}$",
    re.IGNORECASE,
)

# Multi-part public suffixes that matter for registrable-domain comparison.
_TWO_PART_SUFFIXES = {
    "co.uk", "ac.uk", "gov.uk", "org.uk", "com.au", "edu.au", "co.ma", "ac.ma",
}

# The rubric items that say something concrete about what the actor DOES.
_SUBSTANCE_ITEMS = ("use_cases", "research_development_or_programmes")


@dataclass(frozen=True)
class QualityConfig:
    auto_low: float = DEFAULT_AUTO_LOW
    auto_high: float = DEFAULT_AUTO_HIGH
    min_evidence_items: int = DEFAULT_MIN_EVIDENCE_ITEMS
    min_description_chars: int = DEFAULT_MIN_DESCRIPTION_CHARS
    # Verifying WITHOUT a person also needs high engagement priority. Relevance
    # alone decides keep-or-reject; replayed on 105 candidates it would have
    # verified 32 (30%) unseen, against 5 under the approved policy. With this
    # floor at 0.70: 7. Set 0 to verify on relevance alone.
    accept_min_priority: float = DEFAULT_ACCEPT_MIN_PRIORITY
    min_identity_score: float = DEFAULT_MIN_IDENTITY_SCORE
    min_topic_score: float = DEFAULT_MIN_TOPIC_SCORE

    def __post_init__(self) -> None:
        if not 0.0 <= self.auto_low < self.auto_high <= 1.0:
            raise ValueError(
                "actor quality thresholds must satisfy 0 <= auto_low < auto_high <= 1"
            )
        if self.min_evidence_items < 1:
            raise ValueError("min_evidence_items must be at least 1")


@dataclass(frozen=True)
class Scope:
    """What the user asked for. Empty fields do not constrain."""

    sector_codes: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    region_code: str | None = None
    # The sub-topic. Not a reject gate - pages say "energy storage" where the
    # request said "batteries" - but an actor whose page never touches it is
    # held for a person rather than accepted.
    focus_terms: tuple[str, ...] = ()

    @property
    def allowed_states(self) -> frozenset[str]:
        if self.states:
            return frozenset(s.upper() for s in self.states)
        return frozenset(REGION_STATES.get(self.region_code or "", ()))


@dataclass(frozen=True)
class QualityVerdict:
    band: str
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    gates_failed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def accepted(self) -> bool:
        return self.band == ACCEPT


def quality_config(config: Mapping[str, object] | None) -> QualityConfig:
    """Read the quality settings from open_web_discovery configuration."""

    section = dict((config or {}).get("actor_quality") or {})
    thresholds = dict((config or {}).get("actor_score_thresholds") or {})
    return QualityConfig(
        auto_low=float(thresholds.get("auto_low", DEFAULT_AUTO_LOW)),
        auto_high=float(thresholds.get("auto_high", DEFAULT_AUTO_HIGH)),
        min_evidence_items=int(section.get("min_evidence_items", DEFAULT_MIN_EVIDENCE_ITEMS)),
        min_description_chars=int(
            section.get("min_description_chars", DEFAULT_MIN_DESCRIPTION_CHARS)
        ),
        accept_min_priority=float(
            section.get("accept_min_priority", DEFAULT_ACCEPT_MIN_PRIORITY)
        ),
        min_identity_score=float(
            section.get("min_identity_score", DEFAULT_MIN_IDENTITY_SCORE)
        ),
        min_topic_score=float(section.get("min_topic_score", DEFAULT_MIN_TOPIC_SCORE)),
    )


def unit_named_as_parent(page_url: str, record: Mapping[str, object] | None) -> bool:
    """A unit's page (its own sub-site or a unit path) whose record names only the
    parent institution - "Massachusetts Institute of Technology" read from
    energy.mit.edu - so the unit and its parent are mixed up."""
    name = " ".join(str((record or {}).get("name") or "").split())
    unit_words = re.sub(r"institute\s+of\s+technology", " ", name, flags=re.IGNORECASE)
    if not name or _UNIT_WORDS.search(unit_words) or not _INSTITUTION_ONLY.match(name):
        return False
    parts = urlsplit(page_url or "")
    host = (parts.hostname or "").casefold().removeprefix("www.")
    domain = registrable_domain(page_url) or ""
    on_subsite = bool(domain) and host not in ("", domain)
    return on_subsite or bool(_UNIT_PATH.search(parts.path or ""))


# What a record needs before it is accepted without a person: where it is, and
# what kind of organisation it is (with the website and description checked above).
def missing_record_basics(record: Mapping[str, object] | None) -> list[str]:
    record = record or {}
    missing = []
    if not any(str(record.get(k) or "").strip() for k in ("state", "state_code", "location_city")):
        missing.append("location")
    if not any(str(record.get(k) or "").strip() for k in ("actor_type", "actor_type_raw",
                                                           "actor_category")):
        missing.append("kind of organisation")
    return missing


def registrable_domain(url_or_host: str | None) -> str | None:
    """`https://www.umb.edu/ssl/` -> `umb.edu`. Good enough to compare owners."""

    text = str(url_or_host or "").strip().lower()
    if not text:
        return None
    host = urlsplit(text if "://" in text else f"https://{text}").hostname or ""
    host = host.strip(".")
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _evidenced(item: object) -> bool:
    return (isinstance(item, Mapping) and item.get("present") is True
            and bool(str(item.get("evidence") or "").strip()))


def _present_items(rubric: Mapping[str, object] | None) -> set[str]:
    present: set[str] = set()
    for name, item in (rubric or {}).items():
        if _evidenced(item):
            present.add(str(name))
        # use_cases is a group of eight sub-items, not one item. Until
        # 2026-10-15 it was checked like a single item and so NEVER counted:
        # CPower, with two evidenced use cases, was held for "no concrete
        # programmes".
        elif name == "use_cases" and isinstance(item, Mapping) and any(
            _evidenced(sub) for sub in item.values()
        ):
            present.add("use_cases")
    return present


def _stems(text: str) -> set[str]:
    # Four letters: "tech" must meet "technology", "batteries" "battery". Five
    # letters held The Water Council for not mentioning "water technology".
    return {word[:4] for word in re.findall(r"[a-z0-9]+", text.casefold()) if len(word) >= 3}


def mentions_focus(
    focus_terms: Sequence[str],
    record: Mapping[str, object] | None,
    rubric: Mapping[str, object] | None,
) -> bool:
    """Whether the page's own words touch any requested sub-topic term.

    Word stems, so "batteries" meets "battery storage"; every significant word
    of a term must appear for that term to count.
    """

    text_parts = [str((record or {}).get(key) or "") for key in ("name", "description")]
    for item in (rubric or {}).values():
        if isinstance(item, Mapping):
            text_parts.append(str(item.get("evidence") or ""))
    words = _stems(" ".join(text_parts))
    for term in focus_terms:
        needed = _stems(term)
        if needed and needed <= words:
            return True
    return False


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()])


def assess_actor(
    *,
    score: float,
    page_url: str,
    record: Mapping[str, object] | None,
    rubric: Mapping[str, object] | None,
    config: QualityConfig,
    scope: Scope | None = None,
    record_sector_codes: Sequence[str] = (),
    currency=None,
    priority: float | None = None,
    identity_score: float | None = None,
    topic_score: float | None = None,
) -> QualityVerdict:
    """Decide accept / review / reject for one candidate, with the reasons.

    ``currency`` is an ``actor_currency.CurrencyFinding`` (merged, renamed,
    defunct or outdated), or None when the organisation looks current.
    """

    record = record or {}
    reasons: list[str] = []
    rejects: list[str] = []
    holds: list[str] = []

    name = str(record.get("name") or "").strip()
    path = urlsplit(page_url or "").path or ""

    # ---- REJECT gates: a failure here drops the candidate whatever it scored.
    if not name and not _present_items(rubric):
        # Nothing at all was read: no name and no evidence. That is a page the
        # reader could not see (script-rendered, blocked, empty), not proof that
        # no organisation is there. Still rejected - nothing to judge - but
        # named as such, so the run re-reads the site's own homepage and About
        # page once (phase2 official follow-ups) instead of losing the actor.
        rejects.append("unreadable_page")
        reasons.append("The page could not be read: no organisation name and no evidence "
                       "were found in it (it may be rendered by script).")
    elif not name:
        rejects.append("no_name")
        reasons.append("The page names no organisation.")
    if name and _NOT_AN_ORGANISATION_NAME.search(name):
        rejects.append("not_an_organisation")
        reasons.append(f"'{name}' reads as a list, event or article, not an organisation.")
    elif _NOT_AN_ORGANISATION_PATH.search(path):
        rejects.append("not_an_organisation")
        reasons.append("The page is a listing, event, news or careers page.")

    if scope is not None:
        sectors = {str(code).upper() for code in record_sector_codes if str(code).strip()}
        wanted = {code.upper() for code in scope.sector_codes}
        if wanted and not (sectors & wanted):
            rejects.append("outside_requested_sector")
            reasons.append(
                "The page shows no evidence of the requested sector "
                f"({', '.join(sorted(wanted))})."
            )
        raw_state = record.get("state_code") or record.get("state") or ""
        state = normalize_state(raw_state) or str(raw_state).strip().upper()
        allowed = scope.allowed_states
        if allowed and state and state not in allowed:
            check = record.get("location_check") if isinstance(
                record.get("location_check"), Mapping) else {}
            # 7 Nov 2026: where its head office is does not decide whether it works
            # in the requested area. When its page shows it there - an office, or
            # the state named on its own page - a person decides; only an
            # organisation whose page never places it there is rejected.
            there = [o for o in (check.get("operates_in") or [])
                     if isinstance(o, Mapping) and o.get("state") in allowed]
            if there:
                office = next((o for o in there if o.get("kind") == "office"), None)
                seen = office or there[0]
                holds.append("operates_in_area_based_elsewhere")
                reasons.append(
                    f"Located in {state}, outside the requested area, but its page "
                    + (f"gives an office in {seen.get('state')}" if office
                       else f"describes work in {seen.get('state')}")
                    + f": \"{str(seen.get('text') or '')[:140]}\". A person decides whether "
                      "it operates there.")
            else:
                rejects.append("outside_requested_region")
                reasons.append(f"Located in {state}, outside the requested area."
                               + (f" {check.get('reason')}" if check.get("changed") else ""))

    if currency is not None and currency.rejects:
        rejects.append(currency.code)
        reasons.append(currency.reason)

    if score < config.auto_low:
        rejects.append("below_reject_threshold")
        reasons.append(f"Score {score:.2f} is below the reject threshold {config.auto_low:.2f}.")

    if rejects:
        return QualityVerdict(REJECT, score, tuple(reasons), tuple(rejects))

    # ---- ACCEPT gates: all must hold for auto-accept; a failure holds for review.
    page_domain = registrable_domain(page_url)
    own_domain = registrable_domain(str(record.get("website") or ""))
    if not own_domain:
        holds.append("website_unverified")
        reasons.append("No official website is stated, so the page's ownership is unverified.")
    elif page_domain != own_domain:
        holds.append("third_party_page")
        reasons.append(
            f"Read from {page_domain}, but the organisation's own site is {own_domain}: "
            "the page is about it, not by it."
        )

    present = _present_items(rubric)
    if len(present) < config.min_evidence_items:
        holds.append("thin_evidence")
        reasons.append(
            f"Only {len(present)} rubric criteria are evidenced; "
            f"{config.min_evidence_items} are required to accept without review."
        )
    if "real_operating_entity" not in present:
        holds.append("entity_unconfirmed")
        reasons.append("The page does not establish that this is an operating organisation.")
    if not (present & set(_SUBSTANCE_ITEMS)):
        holds.append("no_substantive_work")
        reasons.append("The page names no concrete programmes, research or use cases.")

    description = str(record.get("description") or "").strip()
    if _DESCRIBES_A_PAGE.search(description):
        holds.append("describes_a_page")
        reasons.append("The description presents this as a web page, portal or overview, "
                       "not as an organisation; a person decides whether an actor is behind it.")
    if (len(description) < config.min_description_chars
            or not 1 <= _sentence_count(description) <= 3
            or _TAGLINE.match(description)):
        holds.append("weak_description")
        reasons.append("The description is missing, too short, or a tagline.")

    if currency is not None and not currency.rejects:
        holds.append(currency.code)
        reasons.append(currency.reason)
    check = record.get("location_check") if isinstance(record.get("location_check"),
                                                        Mapping) else {}
    head = check.get("headquarters") if isinstance(check.get("headquarters"), Mapping) else None
    if head and check.get("kept_state") and head.get("state") != check.get("kept_state"):
        # Said, not held: the place kept is where it works; its head office is elsewhere.
        reasons.append(f"Its page puts its head office in {head.get('state')}: "
                       f"\"{str(head.get('text') or '')[:120]}\"; the location kept is "
                       f"{check.get('kept_state')}.")
    if check.get("basis") == "unconfirmed":
        # The page names a state but never ties it to the organisation
        # (agents/common/location_evidence.py): a person decides where it is.
        holds.append("location_unconfirmed")
        reasons.append(str(check.get("reason") or "Its location is not stated on the page."))
    basics = missing_record_basics(record)
    if basics:
        # Too little to be useful unseen: a person decides, after the Light Pull
        # has looked further for it.
        holds.append("incomplete_record")
        reasons.append("The record does not state its " + " or ".join(basics)
                       + "; it is not accepted without a person.")
    if unit_named_as_parent(page_url, record):
        holds.append("unit_or_parent_unclear")
        reasons.append(f"The page belongs to a unit of '{name}', but the record names the "
                       "institution itself: a person decides which organisation this is.")
    if identity_score is not None and identity_score < config.min_identity_score:
        holds.append("identity_unreliable")
        reasons.append(f"Identity reliability {identity_score:.2f} is below "
                       f"{config.min_identity_score:.2f} (own page, operating organisation, "
                       "website and place stated).")
    if topic_score is not None and topic_score < config.min_topic_score:
        holds.append("weak_topic_evidence")
        reasons.append(f"Topic relevance {topic_score:.2f} is below {config.min_topic_score:.2f}: "
                       "the requested sector and concrete work on it are not both evidenced.")

    if scope is not None and scope.focus_terms and not mentions_focus(
            scope.focus_terms, record, rubric):
        holds.append("focus_unconfirmed")
        reasons.append(
            "The page does not mention the requested sub-topic ("
            + ", ".join(scope.focus_terms) + ")."
        )

    if score < config.auto_high:
        holds.append("below_accept_threshold")
        reasons.append(
            f"Score {score:.2f} is below the accept threshold {config.auto_high:.2f}."
        )
    elif priority is not None and priority < config.accept_min_priority:
        holds.append("below_auto_verify_priority")
        reasons.append(
            f"A relevant organisation (score {score:.2f}), but its engagement priority "
            f"{priority:.2f} is below the {config.accept_min_priority:.2f} needed to verify "
            "it without a person."
        )

    if holds:
        return QualityVerdict(REVIEW, score, tuple(reasons), tuple(holds))
    reasons.append(
        f"Score {score:.2f} meets the accept threshold and every quality gate holds."
    )
    return QualityVerdict(ACCEPT, score, tuple(reasons), ())
