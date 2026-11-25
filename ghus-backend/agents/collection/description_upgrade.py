"""A better description for an organization whose description is weak (GHUS, 25 Nov 2026).

An organization update may be asked to "improve the description when it is
weak". After the update has read the organization's own pages:

``weakness(text)``  says why the recorded description is weak (empty, a few
                    words, a placeholder), or None when it is fine. A good
                    description is never rewritten.
``propose(...)``    asks the model for a 2-4 sentence description built ONLY
                    from what those pages state, with the sentences it rests
                    on quoted. Every quote must be found on the page it names
                    (``light_pull_reader.quote_on_page``); with fewer than two
                    checked quotes, nothing is proposed. Nothing is inferred
                    from the name, the category or outside knowledge.

The proposal is never written over the record: the update raises it in
Review (``decisions.propose_description``) beside the current text, and only a
person's acceptance replaces the description.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

MIN_WORDS = 30          # under this, a description says too little to be useful
MIN_CHARS = 180
MAX_CHARS = 900
MIN_CHECKED_QUOTES = 2
PLACEHOLDERS = re.compile(
    r"^\s*(?:n/?a|none|not provided|not found|no description|tbd|unknown|-+)\s*\.?\s*$", re.I)

SYSTEM = (
    "You write the description of one organization for a directory of an innovation "
    "ecosystem. Use ONLY what the given pages state about THIS organization. Write 2 to 4 "
    "plain, factual sentences (about 50 to 110 words) in the third person: what it is, "
    "what it does and for whom, its main programs or areas of work, and where it is based "
    "when a page says so. No marketing words (leading, world-class, innovative, premier), "
    "no claims a page does not make, nothing from outside knowledge. For each sentence, "
    "quote the words on a page that support it, exactly as written, with that page's URL. "
    "If the pages do not say enough for a better description, set enough=false."
)


def weakness(text: str | None) -> str | None:
    """Why the recorded description is weak, in words a reviewer can read; None if not."""
    value = " ".join(str(text or "").split())
    if not value or PLACEHOLDERS.match(value):
        return "There is no description."
    words = len(re.findall(r"\w+", value))
    if words < MIN_WORDS or len(value) < MIN_CHARS:
        return f"The description is only {words} word{'s' if words != 1 else ''}."
    return None


def _schema(urls) -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "enough": {"type": "boolean"},
            "description": {"type": "string"},
            "quotes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"url": {"type": "string", "enum": list(urls)},
                               "quote": {"type": "string"}},
                "required": ["url", "quote"]}},
        },
        "required": ["enough", "description", "quotes"],
    }


def propose(client, *, name: str, current: str | None, texts: Mapping[str, str],
            topic: str | None = None, max_tokens: int = 1500) -> dict:
    """{"text", "quotes", "source_url", "weakness"} or {"skipped": reason}."""
    from agents.collection.light_pull_reader import quote_on_page, quotes_name

    reason = weakness(current)
    if reason is None:
        return {"skipped": "The description is already detailed enough."}
    pages = {url: text for url, text in (texts or {}).items() if str(text or "").strip()}
    if client is None or not pages:
        return {"skipped": "No page was read to write it from."}
    import json

    answer = client.extract_with_tool(
        system=SYSTEM,
        user=json.dumps({"organization": name, "topic": topic, "current_description": current,
                         "pages": [{"url": u, "text": t} for u, t in pages.items()]},
                        ensure_ascii=False),
        tool_name="write_description", tool_description="A description from these pages only.",
        input_schema=_schema(pages), max_tokens=max_tokens) or {}
    text = " ".join(str(answer.get("description") or "").split())
    if not answer.get("enough") or not text:
        return {"skipped": "Its pages do not say enough for a better description."}
    checked = [q for q in answer.get("quotes") or []
               if isinstance(q, Mapping) and q.get("url") in pages
               and quote_on_page(str(q.get("quote") or ""), pages[q["url"]])]
    if len(checked) < MIN_CHECKED_QUOTES:
        return {"skipped": "Its sentences could not be checked against the pages."}
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        return {"skipped": "The proposed description was too short or too long."}
    if not quotes_name(name, [text]):
        return {"skipped": "The proposed description did not name the organization."}
    if " ".join(str(current or "").split()).casefold() == text.casefold():
        return {"skipped": "The proposed description is the current one."}
    quotes = [{"url": q["url"], "quote": " ".join(str(q["quote"]).split())[:400]}
              for q in checked]
    return {"text": text, "quotes": quotes, "source_url": quotes[0]["url"], "weakness": reason}
