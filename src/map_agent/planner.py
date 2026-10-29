"""Conversational map planning with a bounded number of clarification turns.

map_chat returns a prose reply or a structured, bounded search plan. Each turn
uses one tracked model request without web tools.
"""

import os
from datetime import date

import anthropic
from dotenv import load_dotenv
from src.map_agent.costs import paid_message
from src.map_agent.run_store import MapStopped

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
MAX_QUESTION_ROUNDS = 2      # after this many agent turns, it must commit to a plan

_SUBMIT_PLAN = {
    "name": "submit_plan",
    "description": "Submit the search plan. Call exactly once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "map_type": {
                "type": "string",
                "enum": ["organizations", "people", "events"],
                "description": "What this map is about. Exactly one; every task must "
                               "target this type.",
            },
            "summary": {
                "type": "string",
                "description": "What you will look for, in PLAIN ENGLISH, addressed to "
                               "the user. One or two sentences. Describe the kinds of "
                               "organizations and people — never search keywords, never "
                               "mention queries or how the search works.",
            },
            "tasks": {
                "type": "array",
                "description": "List of search tasks to execute.",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "enum": ["actor", "person", "event"],
                            "description": "Which DB entity type this search targets.",
                        },
                        "query": {
                            "type": "string",
                            "description": "A specific web-search query to find entities of this type.",
                        },
                        "focus": {
                            "type": "string",
                            "description": "One-line note on what to look for in the results.",
                        },
                    },
                    "required": ["entity_type", "query", "focus"],
                    "additionalProperties": False,
                },
            },
            "requirements": {
                "type": "object",
                "description": "What the user actually asked for, beyond the topic. "
                               "The request is a SPECIFICATION, not just a search term.",
                "properties": {
                    "hard_filters": {
                        "type": "array",
                        "description": "Conditions an entity MUST satisfy to belong in "
                                       "the result — geography, entity kind, scale, "
                                       "funding status, technical approach. Empty if none.",
                        "items": {"type": "string"},
                    },
                    "preferences": {
                        "type": "array",
                        "description": "What 'best' or 'most relevant' means here — "
                                       "soft ranking criteria, not exclusions. Empty if none.",
                        "items": {"type": "string"},
                    },
                    "result_limit": {
                        "type": "integer",
                        "description": "How many results the user asked for. Use 0 if "
                                       "they did not ask for a specific number.",
                    },
                },
                "required": ["hard_filters", "preferences", "result_limit"],
                "additionalProperties": False,
            },
        },
        "required": ["map_type", "summary", "tasks", "requirements"],
        "additionalProperties": False,
    },
}

MAP_TYPES = {"organizations": "actor", "people": "person", "events": "event"}

_SYSTEM = """\
You are a research planner for a US innovation-ecosystem mapping platform.
It is Compass, run by GHUS (Global Hubs United States), which maps the US
innovation ecosystem for UM6P (Université Mohammed VI Polytechnique, Morocco)
and OCP Group. You know UM6P and OCP; never ask what they are.


Given a user's description of a domain, venture, or program they want mapped, \
produce a set of web-search tasks that will find relevant entities.

Each search is about exactly ONE type of result, set as `map_type`:
- organizations (entity_type `actor`): universities, labs, companies, startups,
  accelerators, agencies, foundations, associations.
- people (entity_type `person`): experts, researchers, founders, directors —
  each tied to their organization.
- events (entity_type `event`): conferences, summits, workshops, demo days.

Rules:
1. Scope is US only — all queries should target the United States.
2. Produce one to four distinct focused search tasks according to the topic's
   breadth. Avoid near-duplicate queries. Every task's entity_type must match
   map_type; never mix types in one search.
3. Each query should be a realistic web-search string (what you'd type into Google).
4. If the user's input mentions specific sub-domains, geographies, or roles, \
create targeted queries for those.
5. If a document is provided, extract the key themes and programs to search for.
6. Call submit_plan exactly once with your tasks.
7. Choose map_type from the words the user used, WITHOUT asking, whenever one
   type is named:
   - people: experts, researchers, scientists, professors, faculty, founders,
     leaders, directors, speakers, contacts, "who works on", "who is working on"
   - events: conferences, summits, workshops, symposia, webinars, meetings,
     events, demo days
   - organizations: universities, labs, centers, institutes, companies,
     startups, accelerators, agencies, foundations, organizations
   "Find experts on X in Y" is a people map; plan it immediately. Ask which
   type to start with ONLY when none of these is named (e.g. "map phosphogypsum
   in Florida").
   When several types are asked for at once ("research centers, experts and
   upcoming events"), do not ask: plan the first one now, in this order —
   organizations, then people, then events — and end your summary by saying
   which ones you will look for next, e.g. "Once these are in, I can look for
   the experts and the upcoming events."
   Your summary describes only what THIS search looks for. On an organization
   search, never say you will find researchers, faculty or events in it.
8. People and event maps search for people or events directly. Organization
   maps collect only key people already named in the same evidence; deeper people
   research is a separate request made on an organization card.
9. When the user names an area (a state, a region such as "the Northeast", a
   city), EVERY query stays inside it: write the area into every query, and never
   name organizations, labs or places outside it. "national laboratories NREL
   Argonne Oak Ridge" is wrong for a Northeast map; "national laboratories
   Northeast New York Brookhaven" is right.

THE REQUEST IS A SPECIFICATION, NOT JUST A TOPIC. Separate the two:
- The SUBJECT MATTER becomes your search queries.
- Everything else — "only in California", "membrane not thermal", "pilot-scale",
  "the 4-5 best", "exclude corporate-funded" — is a REQUIREMENT. Put it in the
  `requirements` object. A later stage enforces it against the results.
- Requirements that narrow WHERE to look (geography, entity kind, technical
  approach) must ALSO be written into the queries themselves — otherwise we
  search the whole country and throw most of it away. A filter that can shape
  the search belongs in BOTH places.
- Set result_limit only if the user named a number; otherwise 0.
- If the user stated no requirements, return empty arrays and 0. Do not invent
  constraints they did not ask for.

ACTOR FOCUS (organization maps only) — {focus_rule}

Word queries so they actually surface the requested kind of organization. A query \
like "<domain> startups" returns only companies; to reach academia you must ask \
for it explicitly — university labs, national laboratories (e.g. NREL, Berkeley \
Lab, PNNL, Argonne), university research centers, consortia, and testbeds."""

# Chat mode: the user is talking to the planner. Prose = a question back to them;
# calling submit_plan = "I have enough, I'm starting". No approval step — the
# agent announces what it will do (via `summary`) and proceeds.
_CHAT_RULE = """

YOU ARE TALKING WITH THE USER. This is a conversation, not a form.

- To ask something, just WRITE IT — normal prose, warm and brief. Ask about what
  you genuinely need: scope, which sub-areas matter, what kind of organizations.
  One or two questions at a time, never a numbered interrogation.
- When you have enough to search well, call submit_plan. You do NOT need
  permission and must not ask for approval — decide, and say what you are doing
  in `summary`.
- On the FIRST message of a new map you always ask first (see the first-message
  rule). After that, do not drag it out: once you have been answered, commit.
- Only if rule 7 cannot decide the type (no type named at all), ask exactly that
  first: should you start with organizations, people or events? Never ask it when
  the user named one or more types: with several, start with the first (rule 7)
  and offer the others next.

NEVER show the user search keywords, query strings, or how the search works. Talk
about the kinds of organizations, labs, and people you will look for. The queries
are internal.

Write `summary` as if speaking to them: "I'll look for university water-management
centres, the national labs working on irrigation, and the researchers leading
them." Then it runs — so phrase it as something happening, not something proposed."""

FIRST_MESSAGE_RULE = """

FIRST MESSAGE RULE. This is the user's first message for this map. Do not plan
yet: reply in words with one or two short questions that will make the search
better - what kind of results to start with (organizations, people or events)
when they did not say, which area (a state, a region, or the whole US), which
sub-topics matter most, or what the results are for. Ask only what their message
leaves open, acknowledge what they already said, and keep it to two or three
sentences. You will plan after their answer."""

# What the ACTOR FOCUS rule says, per the caller's actor_focus setting.
# "research" is the DEFAULT — this platform maps partners for a university, so
# the academic side of an ecosystem is the point, not an afterthought.
_FOCUS_RULES = {
    "research": "Weight the plan about 80/20 toward ACADEMIA.\n"
                "- ~80% of tasks target RESEARCH organizations: university labs and "
                "departments, national laboratories (NREL, Berkeley Lab, PNNL, "
                "Argonne, Oak Ridge, Sandia...), university-affiliated research "
                "centers, consortia, and testbeds.\n"
                "- The REMAINING ~20% (at most one task) may target companies, and "
                "only where they sit close to that research ecosystem — spin-outs, "
                "consortium members, or named lab/industry partners.\n"
                "- Concretely: with 5 tasks use 4 academic + 1 company; with 4 use "
                "3 + 1; with 3 use 3 academic.",
    "both": "Cover BOTH sides of the ecosystem. At least one task must target "
            "companies/startups AND at least one must target universities, "
            "national labs, or research centers. Do not let one crowd out the other.",
    "companies": "Focus on companies — startups, scale-ups, corporates, and the "
                 "accelerators/investors around them.",
}

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic()
    return _client


_EMPTY_REQS = {"hard_filters": [], "preferences": [], "result_limit": 0}


def _bounded_tasks(tasks: list[dict]) -> list[dict]:
    """Keep distinct, valid search angles within the controlled first-pass scope."""
    bounded = []
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or task.get("entity_type") not in ("actor", "person", "event"):
            continue
        query = " ".join(str(task.get("query") or "").split())[:400]
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        bounded.append({"entity_type": task["entity_type"], "query": query,
                        "focus": str(task.get("focus") or "")[:500]})
        if len(bounded) == 4:
            break
    return bounded


_FOUND_RULE = """

THIS MAP HAS ALREADY BEEN BUILT. Its searches so far looked for: {searched}.
The results below were found and are on the user's screen right now.

Most follow-ups are QUESTIONS ABOUT WHAT IS THERE — "which of these are in
Texas", "why is this one included", "summarise the top three". Answer those from
the list in prose. Do not plan new searching for a question you can already
answer; searching again is slow and spends their budget.

Plan only when they genuinely ask for results that are NOT in the list —
"also look for national labs", "what about New Mexico". Then write tasks for the
NEW ground only; what is already found will be kept and merged, so repeating a
previous search wastes the budget. Say what you are looking for, do not ask
permission.

They may ask for another type than {map_type} — the experts or the events
around these results, or a type you offered to look for next. Plan it: set
map_type to that type (one type per search) and write tasks for it; its results
appear under their message. A short "yes" or "go ahead" after you offered the
next type means: plan that type now. If more types remain after it, end your
summary by offering the next one.

RESULTS ALREADY FOUND:
{found}"""


def _found_summary(result: dict | None, limit: int = 40) -> str:
    """One line per entity the user can already see, for follow-up turns."""
    groups = (result or {}).get("entities") or {}
    lines = []
    for key in ("actor", "person", "event"):
        for entity in (groups.get(key) or [])[:limit]:
            name = entity.get("full_name") or entity.get("name")
            if not name:
                continue
            bits = [b for b in (entity.get("actor_type"), entity.get("state"),
                                entity.get("location_city"), entity.get("title")) if b]
            lines.append(f"- {name}" + (f" ({', '.join(str(b) for b in bits)})" if bits else ""))
    return "\n".join(lines)


def map_chat(messages: list[dict], doc_text: str | None = None,
             actor_focus: str = "research", run=None,
             ask_context: str | None = None, result: dict | None = None) -> dict:
    """One turn of the map-planning conversation.

    `messages` is the running exchange as plain {role, content} text turns, so it
    round-trips through JSON to the browser without reconstructing tool blocks.

    Returns ONE of:
        {"status": "reply", "message": str}   — the agent is asking / talking back
        {"status": "plan", "summary": str, "tasks": [...], "requirements": {...}}
        {"status": "error", "message": str}

    Prose IS the question channel: if the model writes text instead of calling
    submit_plan, that text is what the user should see. (An earlier version forced
    a tool call, so questions were silently swallowed and the map came back empty.)
    """
    today = date.today()
    system = _SYSTEM.format(
        focus_rule=_FOCUS_RULES.get(actor_focus, _FOCUS_RULES["research"])) + _CHAT_RULE + (
        f"\n\nTODAY'S DATE is {today.isoformat()}. Queries that name years must use "
        f"{today.year} or {today.year + 1}, never earlier years, unless the user asked "
        "about the past. For events, search for upcoming editions. When the user names a "
        "period (a year, months, 'next 12 months'), put that period's year or years in "
        "every event query, so the search starts from the dates. Put a date or period "
        "in hard_filters ONLY when the user named one; years in queries are not a "
        "requirement. Keep a period as its own filter, never inside another one.")
    found = _found_summary(result)
    built_type = (result or {}).get("map_type") or "organizations"
    if found:
        searched = ", ".join(dict.fromkeys((result or {}).get("round_types") or [built_type]))
        system += _FOUND_RULE.format(found=found, map_type=built_type, searched=searched)
    msgs = list(messages or [])
    if doc_text and msgs:
        msgs = [{"role": "user",
                 "content": f"ATTACHED DOCUMENT (excerpt):\n{doc_text[:6000]}"}] + msgs
    # Background, never the request: the user's own message stays the thing the
    # map is graded against.
    if ask_context and msgs:
        msgs = [{"role": "user",
                 "content": f"BACKGROUND FROM AN EARLIER CONVERSATION (context "
                            f"only, not the request):\n{ask_context[:4000]}"}] + msgs

    # Convergence guard. Prompting alone does not reliably stop the questions —
    # in testing it asked a second round after being told to commit. Past the cap
    # we force the tool, so the conversation cannot loop forever.
    #
    # It applies only BEFORE a map exists. Once there are results the thread stays
    # open for questions about them, and forcing a plan there would turn "which of
    # these are in Texas" into a paid search once the turns added up.
    asked = sum(1 for m in msgs if m.get("role") == "assistant")
    force = asked >= MAX_QUESTION_ROUNDS and not found
    kwargs = {"tool_choice": {"type": "tool", "name": "submit_plan"}} if force else {}
    if force:
        system += ("\n\nYou have already asked enough. Commit to a plan now using "
                   "what you know; make reasonable assumptions for anything still open.")
    # The first message of a new map always gets questions first (decided 29 Oct
    # 2026): the planner is not given the plan tool on that turn, so it can only
    # answer in words. Follow-ups on a built map are unchanged.
    first = asked == 0 and not found
    if first:
        system += FIRST_MESSAGE_RULE
    tools = {} if first else {"tools": [_SUBMIT_PLAN]}

    try:
        resp = paid_message(_get_client(), run, "Planning",
            model=MODEL, max_tokens=MAX_TOKENS, system=system,
            messages=msgs, **tools, **kwargs,
        )
    except MapStopped:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}

    text = []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "submit_plan":
            reqs = block.input.get("requirements") or {}
            # Each search looks for one type. A follow-up on a built map may look
            # for another type than the first search did (28 Oct 2026).
            map_type = block.input.get("map_type")
            if map_type not in MAP_TYPES:
                map_type = built_type if found else "organizations"
            tasks = [t for t in _bounded_tasks(block.input.get("tasks", []))
                     if t["entity_type"] == MAP_TYPES[map_type]]
            if not tasks:
                return {"status": "reply", "message":
                        "I couldn't turn that into a search. Say which organizations, "
                        "people or events you'd like me to look for."}
            return {"status": "plan", "map_type": map_type,
                    "summary": block.input.get("summary", ""),
                    "tasks": tasks,
                    "requirements": {**_EMPTY_REQS, **reqs}}
        if block.type == "text" and block.text.strip():
            text.append(block.text.strip())

    if text:
        return {"status": "reply", "message": "\n\n".join(text)}
    return {"status": "error", "message": "the planner returned nothing"}
