"""Every error the platform shows, in words a person without technical training understands.

Messages from the backend, the database, websites and the AI service arrive
in their own vocabulary - "HTTPStatusError: Client error '403 Forbidden' for
url ...", "psycopg.errors.ConnectionTimeout", "UndefinedColumn". The screens
show whatever ``detail`` or ``error`` says, so this is the one place they are
translated, for every page at once (see backend.app):

    explain("X could not be checked: HTTPStatusError: Client error '403 Forbidden'")
    -> "X could not be checked: the website refused automated access, so it could not
       be read."

A message that is already plain is returned unchanged. The original text is
never lost: the API keeps it beside the plain one, under ``technical``.
"""

from __future__ import annotations

import re

# Signs that a message is written for programmers, not for the people using the app.
_TECHNICAL = re.compile(
    r"Traceback|\b[A-Z][A-Za-z]+(Error|Exception|Timeout)\b|\berrno\b|\bstatus code\b|"
    r"psycopg|sqlalchemy|httpx|Client error '|Server error '|developer\.mozilla|"
    r"\bat 0x[0-9a-f]+|File \"|\bNoneType\b|\bKeyError\b|\[Errno|\bSQL\b|"
    r"UndefinedColumn|UndefinedTable|stderr|exit code|returncode|ECONN|ETIMEDOUT",
    re.IGNORECASE)

# (pattern, plain sentence). The first that matches explains the message.
_RULES: list[tuple[re.Pattern, str]] = [(re.compile(p, re.IGNORECASE), s) for p, s in [
    (r"robots\.txt", "the website asks automated tools not to read this page, and we "
                     "respect that"),
    (r"\b403\b|forbidden", "the website refused automated access, so it could not be read"),
    (r"\b401\b|unauthori[sz]ed|authentication|api[_ ]key|invalid x-api-key",
     "the service refused the request because its access key is missing or not accepted"),
    (r"\b429\b|too many requests|rate.?limit", "the service asked us to slow down; please "
                                                "try again in a few minutes"),
    (r"\b(529|503)\b|overloaded|service unavailable", "the service is busy or unavailable "
                                                      "right now; please try again shortly"),
    (r"\b404\b|not found\b", "the page or record was not found; it may have moved or been "
                             "removed"),
    (r"certificate|ssl", "the website's security certificate is broken, so it was not read"),
    (r"psycopg|postgres|operationalerror|connection timeout expired|database|"
     r"could not connect to server", "the database is not answering right now; please try "
                                     "again in a minute"),
    (r"undefinedcolumn|undefinedtable|does not exist|no such table|no such column",
     "the database is missing a part this feature needs (an update to the database has not "
     "been applied yet)"),
    (r"timeout|timed out|etimedout", "the service took too long to answer; please try again"),
    (r"getaddrinfo|name or service not known|nodename|connecterror|connection refused|"
     r"econnrefused|network is unreachable", "the service could not be reached; check the "
                                             "address or try again later"),
    (r"budget|spend(ing)? (limit|ceiling)|cost cap|max_usd", "it reached its spending limit, "
                                                              "so it stopped"),
    (r"jsondecodeerror|expecting value|invalid json", "the service sent back an answer that "
                                                      "could not be read"),
    (r"permissionerror|access is denied|permission denied", "the app was not allowed to open "
                                                            "a file it needs"),
    (r"validation|field required|value is not a valid|missing", "some information in the "
                                                                "request is missing or not "
                                                                "valid"),
]]

GENERIC = "Something went wrong on our side. Nothing was changed, and the details were " \
          "recorded for support."


def is_technical(text: str | None) -> bool:
    return bool(text) and bool(_TECHNICAL.search(str(text)))


def explain(text: str | None) -> str | None:
    """The message in plain words; a plain message is returned as it is."""
    if text is None:
        return None
    text = str(text).strip()
    if not text or not is_technical(text):
        return text
    plain = next((sentence for pattern, sentence in _RULES if pattern.search(text)), None)
    # Keep what the message said in plain words before the technical part:
    # "CPower Energy could not be checked: HTTPStatusError ..." keeps its subject.
    first = _TECHNICAL.search(text)
    lead = text[:first.start()].rstrip(" :;,-(") if first else ""
    lead = re.sub(r"\s+", " ", lead)
    if lead and len(lead.split()) >= 3 and not is_technical(lead):
        if plain:
            return f"{lead}: {plain}."
        return f"{lead}. {GENERIC}"
    if plain:
        return plain[0].upper() + plain[1:] + "."
    return GENERIC


# Fields of a successful answer that carry a reason something did not work.
REASON_KEYS = frozenset({"error", "status_reason", "related_error", "refusal", "admission_error"})


def explain_payload(value, *, depth: int = 0):
    """Translate every reason field in a JSON answer, keeping the original beside it."""
    if depth > 12:
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in REASON_KEYS and isinstance(item, str) and is_technical(item):
                out[key] = explain(item)
                out.setdefault(f"{key}_technical", item)
            else:
                out[key] = explain_payload(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [explain_payload(item, depth=depth + 1) for item in value]
    return value
