"""Stage 1 — Plan the mapping search.

Single-shot LLM call. Reads the user's description (+ optional document text)
and produces a structured search plan: which entity types to look for and
what web-search queries to run. No loop, no web tools — just reasoning.
"""

import os

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
        "required": ["summary", "tasks", "requirements"],
        "additionalProperties": False,
    },
}

_SYSTEM = """\
You are a research planner for a US innovation-ecosystem mapping platform.

Given a user's description of a domain, venture, or program they want mapped, \
produce a set of web-search tasks that will find relevant entities.

Entity types you can target:
- actor: organizations (startups, labs, accelerators, institutes, companies).
- person: founders, researchers, directors, and other key people. Every person
          must be tied to a named organization.
- event: conferences, summits, workshops, demo days
       ** OPT-IN ONLY — see rule 7. **

Rules:
1. Scope is US only — all queries should target the United States.
2. Produce one to four distinct focused search tasks according to the topic's
   breadth. Avoid near-duplicate queries. Research organizations first; the
   backend separately looks for people in selected organizations if needed.
3. Each query should be a realistic web-search string (what you'd type into Google).
4. If the user's input mentions specific sub-domains, geographies, or roles, \
create targeted queries for those.
5. If a document is provided, extract the key themes and programs to search for.
6. Call submit_plan exactly once with your tasks.
7. NEVER create an `event` task unless the user EXPLICITLY asked for events —
   i.e. they used words like events, conferences, summits, workshops, symposia,
   demo days, or "where does this community meet". A domain that merely happens
   to have conferences is NOT a request for them. When in doubt, leave events
   out; a search task is expensive and unasked-for events waste it.
8. Do not create a separate `person` task. Use one actor task and collect only
   key people encountered in the same bounded research. If the user explicitly
   asks only for people, a person task is allowed instead.

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

ACTOR FOCUS — {focus_rule}

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
- Do not drag it out. If the request is already clear, plan immediately without
  asking anything. If you have asked once and been answered, commit.

NEVER show the user search keywords, query strings, or how the search works. Talk
about the kinds of organizations, labs, and people you will look for. The queries
are internal.

Write `summary` as if speaking to them: "I'll look for university water-management
centres, the national labs working on irrigation, and the researchers leading
them." Then it runs — so phrase it as something happening, not something proposed."""

_ASK_CLARIFICATION = {
    "name": "ask_clarification",
    "description": "Ask the user to resolve a genuine ambiguity BEFORE a plan is "
                   "built. Use sparingly — see the bar in the system prompt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "1-3 short, concrete questions. Each must be one the "
                               "user can answer in a sentence.",
                "items": {"type": "string"},
            },
            "why": {
                "type": "string",
                "description": "One line: what is ambiguous and how the answer would "
                               "change the search plan.",
            },
        },
        "required": ["questions", "why"],
    },
}

# Appended to the system prompt for the conversational entry point.
_CLARIFY_RULE = """

BEFORE PLANNING — you may ask, but the bar is HIGH.
You have two tools: ask_clarification and submit_plan. You must call exactly one.

Call ask_clarification ONLY when the request is genuinely ambiguous AND the answer
would materially change which searches you run. Real examples: the user names a
country other than the US (are we looking for US organizations working on that
problem, or ones already partnered there?); the domain has two unrelated readings;
the request names a document but no topic.

Otherwise call submit_plan. Do NOT ask about things you can reasonably assume, and
do NOT ask the user to narrow a broad-but-clear topic — breadth is fine, that is
what a map is for. If you have already asked once and been answered, commit to a
plan; never ask twice about the same thing.

You cannot reply with prose. Silence is not an option — call one of the two tools."""

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


def plan_search(description: str, doc_text: str | None = None,
                actor_focus: str = "research", run=None) -> tuple[list[dict], dict]:
    """Return (tasks, requirements).

    tasks:        [{entity_type, query, focus}, ...] — what to search for.
    requirements: {hard_filters, preferences, result_limit} — what the user
                  asked for BEYOND the topic, enforced later by select.py.

    `actor_focus` steers what kind of organizations to look for — "research"
    (DEFAULT, ~80/20 academic), "both", or "companies". Not exposed in the UI:
    the academic weighting is the intended behavior, not a per-run choice. Left
    as a parameter so a caller can still override it programmatically.
    """
    out = plan_conversation(description, doc_text, actor_focus=actor_focus,
                            allow_questions=False, run=run)
    return out.get("tasks", []), out.get("requirements", dict(_EMPTY_REQS))


def map_chat(messages: list[dict], doc_text: str | None = None,
             actor_focus: str = "research", run=None) -> dict:
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
    system = _SYSTEM.format(
        focus_rule=_FOCUS_RULES.get(actor_focus, _FOCUS_RULES["research"])) + _CHAT_RULE
    msgs = list(messages or [])
    if doc_text and msgs:
        msgs = [{"role": "user",
                 "content": f"ATTACHED DOCUMENT (excerpt):\n{doc_text[:6000]}"}] + msgs

    # Convergence guard. Prompting alone does not reliably stop the questions —
    # in testing it asked a second round after being told to commit. Past the cap
    # we force the tool, so the conversation cannot loop forever.
    asked = sum(1 for m in msgs if m.get("role") == "assistant")
    force = asked >= MAX_QUESTION_ROUNDS
    kwargs = {"tool_choice": {"type": "tool", "name": "submit_plan"}} if force else {}
    if force:
        system += ("\n\nYou have already asked enough. Commit to a plan now using "
                   "what you know; make reasonable assumptions for anything still open.")

    try:
        resp = paid_message(_get_client(), run, "Planning",
            model=MODEL, max_tokens=MAX_TOKENS, system=system,
            tools=[_SUBMIT_PLAN], messages=msgs, **kwargs,
        )
    except MapStopped:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}

    text = []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "submit_plan":
            reqs = block.input.get("requirements") or {}
            return {"status": "plan",
                    "summary": block.input.get("summary", ""),
                    "tasks": _bounded_tasks(block.input.get("tasks", [])),
                    "requirements": {**_EMPTY_REQS, **reqs}}
        if block.type == "text" and block.text.strip():
            text.append(block.text.strip())

    if text:
        return {"status": "reply", "message": "\n\n".join(text)}
    return {"status": "error", "message": "the planner returned nothing"}


def _opening_message(description: str, doc_text: str | None) -> str:
    parts = [f"DOMAIN TO MAP:\n{description}"]
    if doc_text:
        parts.append(f"\nATTACHED DOCUMENT (excerpt):\n{doc_text[:6000]}")
    parts.append("\nEither ask a clarifying question or produce the search plan.")
    return "\n".join(parts)


def plan_conversation(description: str, doc_text: str | None = None,
                      history: list[dict] | None = None,
                      actor_focus: str = "research",
                      allow_questions: bool = True, run=None) -> dict:
    """Plan a map, asking the user first if the request is genuinely ambiguous.

    A map costs real money and minutes, so it is worth a few cheap turns to get
    the spec right before spending. Returns ONE of:

        {"status": "questions", "questions": [...], "why": str, "history": [...]}
        {"status": "plan", "tasks": [...], "requirements": {...}, "history": [...]}
        {"status": "error", "message": str, "history": [...]}

    `history` is the running exchange as plain {role, content} text turns — kept
    text-only (rather than echoing tool_use blocks) so it round-trips through
    JSON to the browser and back without reconstructing tool-result pairs.

    Pass allow_questions=False to force a plan in one shot (no clarification).
    """
    system = _SYSTEM.format(
        focus_rule=_FOCUS_RULES.get(actor_focus, _FOCUS_RULES["research"]))
    tools = [_SUBMIT_PLAN]
    if allow_questions:
        system += _CLARIFY_RULE
        tools = [_ASK_CLARIFICATION, _SUBMIT_PLAN]

    messages = list(history or [])
    if not messages:
        messages = [{"role": "user", "content": _opening_message(description, doc_text)}]

    try:
        resp = paid_message(_get_client(), run, "Planning",
            model=MODEL, max_tokens=MAX_TOKENS, system=system, tools=tools,
            # Force a tool call: left free, the model answers ambiguous requests
            # with prose, which upstream code silently read as "no plan".
            tool_choice={"type": "any"},
            messages=messages,
        )
    except MapStopped:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e), "history": messages}

    for block in resp.content:
        if block.type != "tool_use":
            continue

        if block.name == "ask_clarification":
            qs = block.input.get("questions") or []
            why = block.input.get("why", "")
            if qs:
                asked = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
                messages = messages + [
                    {"role": "assistant", "content": f"CLARIFYING QUESTIONS:\n{asked}"}]
                return {"status": "questions", "questions": qs, "why": why,
                        "history": messages}

        if block.name == "submit_plan":
            reqs = block.input.get("requirements") or {}
            return {"status": "plan",
                    "tasks": _bounded_tasks(block.input.get("tasks", [])),
                    "requirements": {**_EMPTY_REQS, **reqs},
                    "history": messages}

    return {"status": "error", "message": "planner returned no plan",
            "history": messages}


def answer_clarification(history: list[dict], answers: str,
                         actor_focus: str = "research", run=None) -> dict:
    """Continue a planning conversation with the user's reply. Same return shape.

    After one round of answers the planner must commit, so this call runs with
    questions disabled — no interrogation loops.
    """
    messages = list(history or []) + [
        {"role": "user", "content": f"ANSWERS:\n{answers}\n\nNow produce the plan."}]
    return plan_conversation("", None, history=messages,
                             actor_focus=actor_focus, allow_questions=False, run=run)
