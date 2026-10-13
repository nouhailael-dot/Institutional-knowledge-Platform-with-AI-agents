"""Turn retrieved entities + a question into a CITED answer.

Runs on the Claude API — the decided stack (CLAUDE.md). The LLM is isolated to
this one file: to trade quality for cost, change MODEL to "claude-sonnet-5" or
"claude-haiku-4-5"; to fall back to the free Groq path, restore the Groq client.

The non-negotiable rules from CLAUDE.md are enforced in the system prompt:
  - Every fact must cite the entity it came from.
  - If the retrieved context doesn't answer the question, SAY SO — never guess.
    A confidently-wrong answer destroys the team's trust in the map.
"""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-4-8"   # most capable; -> claude-sonnet-5 / -haiku-4-5 to cut cost
MAX_TOKENS = 2048
CONDENSE_MODEL = "claude-haiku-4-5"   # cheap: only rewrites a follow-up into a standalone Q
# The Ask -> Build the Map handoff runs once per click and decides which filters a
# paid map enforces. On Haiku a constraint set early in the thread was dropped in
# 1 of 3 runs; on Sonnet it held 5 of 5. Reliability is worth the cents here.
HANDOFF_MODEL = "claude-sonnet-5"

_client = None


_CONDENSE_SYSTEM = """\
You rewrite a follow-up question into a single, self-contained question using the \
conversation so far. Resolve references like "those", "them", "that hub" to the \
specific entities discussed, and carry over any filters implied by context \
(location, TRL, sector). Preserve the user's intent exactly. Output ONLY the \
rewritten question — no preamble. If the follow-up already stands on its own, \
return it unchanged."""


def condense_question(history: list[dict], question: str) -> str:
    """Turn a follow-up into a standalone query. `history` = [{'q':..,'a':..}, ...].

    Runs on a cheap model. Returns `question` unchanged when there's no history
    or on any error (fail open — a literal search beats a crash).
    """
    if not history:
        return question
    convo = "\n\n".join(f"User: {h.get('q','')}\nAssistant: {h.get('a','')}"
                        for h in history[-3:])
    user = f"{convo}\n\nFollow-up: {question}\n\nStandalone question:"
    try:
        resp = _get_client().messages.create(
            model=CONDENSE_MODEL, max_tokens=256,
            system=_CONDENSE_SYSTEM, messages=[{"role": "user", "content": user}])
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        return out or question
    except Exception:
        return question


_HANDOFF_SYSTEM = """\
An Ask conversation ran out of database coverage and the user now wants to \
research the topic on the open web. Read the WHOLE conversation and separate what \
they narrowed to, so none of it has to be retyped.

A constraint set at any point in the conversation counts, even if it was never \
repeated.

Constraints come ONLY from what the USER wrote. The DATABASE ANSWER lines show \
what the database happened to contain - never turn them into a filter. If the \
answers mention organizations in one state and the user asks about another, the \
geography is only the one the user asked about. Use the answers solely to \
understand what the user's words refer to ("those", "them").

Only a stated restriction is must_be or exclude ("startups only", "not \
corporate labs", "in Ohio"). Something the user merely ASKED about ("do any of them \
have EU funding?") shows interest, not a requirement — it is at most \
a prefer entry.

- topic: the subject matter alone, as a short noun phrase. Do not repeat anything \
that belongs in must_be, exclude or prefer.
- must_be: pass/fail conditions the user stated - organization kind, geography. \
One condition per entry.
- exclude: what the user ruled out.
- prefer: what the user leaned toward without requiring it.
- result_limit: only if the user named a number, else 0.
- known_actors: organizations the database answers cited. These are background, \
not part of the request.

in_scope is false only when the topic is not about research organizations, \
people or events at all. Running out of database coverage is exactly when this \
helps, so that alone is never out of scope."""

_HANDOFF_TOOL = {
    "name": "submit_handoff",
    "description": "Report what the conversation established. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "in_scope": {"type": "boolean"},
            "topic": {"type": "string"},
            "must_be": {"type": "array", "items": {"type": "string"}},
            "exclude": {"type": "array", "items": {"type": "string"}},
            "prefer": {"type": "array", "items": {"type": "string"}},
            "result_limit": {"type": "integer"},
            "known_actors": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string",
                       "description": "One sentence, only when in_scope is false."},
        },
        "required": ["in_scope", "topic"],
    },
}


def ask_handoff(history: list[dict]) -> dict:
    """What an Ask conversation established, for Build a Map to start from.

    `history` = [{'q':..,'a':..,'sources':[names]}, ...] — the WHOLE thread, not a
    recent window: a constraint set early and never repeated still counts.

    Returns the editable rows plus background. Raises rather than guessing: a
    silently empty handoff would send the user to the map page with nothing.
    """
    convo = "\n\n".join(
        f"USER: {turn.get('q','')}\nDATABASE ANSWER (context only, never a filter): {turn.get('a','')}"
        + (f"\n[cited from database: {', '.join(turn.get('sources') or [])}]"
           if turn.get("sources") else "")
        for turn in (history or []))
    resp = _get_client().messages.create(
        model=HANDOFF_MODEL, max_tokens=2048, system=_HANDOFF_SYSTEM,
        tools=[_HANDOFF_TOOL],
        messages=[{"role": "user", "content": convo[:24000]}])
    for block in resp.content:
        if block.type == "tool_use" and block.name == "submit_handoff":
            data = block.input
            rows = {key: [str(v).strip() for v in (data.get(key) or []) if str(v).strip()]
                    for key in ("must_be", "exclude", "prefer", "known_actors")}
            limit = data.get("result_limit") or 0
            return {"in_scope": bool(data.get("in_scope")),
                    "topic": str(data.get("topic") or "").strip(),
                    "result_limit": limit if isinstance(limit, int) and 0 < limit <= 50 else 0,
                    "reason": str(data.get("reason") or "").strip(), **rows}
    raise RuntimeError("no handoff returned")


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env.")
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


SYSTEM_PROMPT = """\
You are the UM6P Global Hubs research assistant. You answer questions about a \
verified database of US institutions, national labs, funders, ventures, and events \
that the team tracks for partnership-building.

You will be given a numbered list of SOURCE entities retrieved from the verified \
database, followed by a question. Follow these rules exactly:

1. Answer ONLY from the provided sources. Do not use outside knowledge.
2. Cite the source for every fact, by the entity's name, like: \
(source: Savannah River National Laboratory).
3. If the sources do not contain the answer, say plainly: "The verified database \
doesn't contain enough information to answer this." Do not guess or fabricate. \
When you list what the database holds on a subject, say it is what the database \
holds, not everything that exists.
4. Be concise and factual. Lead with the direct answer, then supporting detail.
5. When several entities are relevant, group or list them clearly.
6. Never explain how the search or retrieval worked — no commentary on query \
matching, text patterns, false positives, or why certain results were included \
or excluded. Just answer the question.
7. Some sources may be marked PARKED: organizations a teammate set aside in a \
saved map that are not in the verified database. Give the verified database \
answer first. Then, only if parked sources are relevant, add a short separate \
part headed "Parked, not verified", naming each one and the map it came from.
"""


def _format_context(entities: list[dict]) -> str:
    """Render retrieved entities into a numbered block for the prompt."""
    blocks = []
    for i, e in enumerate(entities, 1):
        label = (f" — PARKED, not verified; from the saved map \"{e.get('map') or 'untitled'}\""
                 if e.get("parked") else "")
        blocks.append(f"[SOURCE {i}] {e['name']} ({e['entity_type']}){label}\n"
                      f"{e['doc_text']}")
    return "\n\n".join(blocks)


def _build_messages(question: str, entities: list[dict]) -> list[dict]:
    context = _format_context(entities) if entities else "(no sources retrieved)"
    user_content = f"SOURCES:\n\n{context}\n\n---\n\nQUESTION: {question}"
    return [{"role": "user", "content": user_content}]


def answer_question(question: str, entities: list[dict]) -> str:
    """Non-streaming: return the full cited answer as a string."""
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=_build_messages(question, entities),
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def stream_answer(question: str, entities: list[dict]):
    """Streaming: yield answer text chunks as they arrive (used by the UI)."""
    with _get_client().messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=_build_messages(question, entities),
    ) as stream:
        for text in stream.text_stream:
            yield text


if __name__ == "__main__":
    import sys
    from src.retrieve import retrieve

    q = " ".join(sys.argv[1:]) or "Who works on phosphogypsum?"
    hits = retrieve(q)
    print(f"Q: {q}\n")
    print(answer_question(q, hits))
    print("\nSources:", ", ".join(h["name"] for h in hits))
