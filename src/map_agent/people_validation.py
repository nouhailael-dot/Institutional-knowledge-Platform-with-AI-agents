"""Conservative identity and evidence checks; no model calls."""
import json
import re


class ExtractionError(ValueError):
    pass


def entity_rows(value):
    """Decode bounded JSON wrappers, never execute model-produced text."""
    for _ in range(4):
        if isinstance(value, list):
            return value
        if isinstance(value, str) and len(value) <= 200_000:
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                break
        elif isinstance(value, dict) and "entities" in value:
            value = value["entities"]
        else:
            break
    raise ExtractionError("Extraction returned an invalid record list; raw response was saved.")


def normalized(value):
    return " ".join(re.findall(r"\w+", str(value).casefold()))


def affiliation_matches(affiliation, target):
    name, full = normalized(affiliation), normalized(target)
    if not name or re.search(r"\b(panelist|speaker|visitor|visiting|conference|not specified)\b", name):
        return False
    if name == full:
        return True
    parts = [normalized(x) for x in re.split(r"\s+/\s+", target)]
    # Recognize explicitly named units, not every employee of the parent.
    if len(parts) < 2:
        return False
    prefix = re.split(r"\b(?:water institute|institute|center|centre|department|school)\b", parts[0])[0].strip()
    return any(len(p.split()) >= 3 and name in (p, (prefix + " " + p).strip()) for p in parts)


def check_people_evidence(person, available):
    """Unsupported criterion claims become unknown, not positive matches."""
    allowed = {s["url"] for s in person.get("sources", [])}
    assessments = person.get("criteria_assessment")
    person["criteria_assessment"] = []
    for row in assessments if isinstance(assessments, list) else []:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        url, quote = row.get("source_url", ""), row.get("evidence_quote", "")
        grounded = (url in allowed and isinstance(quote, str) and len(quote.strip()) >= 20
                    and normalized(quote) in normalized(available.get(url, {}).get("text", "")))
        conference_only = (re.search(r"africa|project", str(row.get("criterion", "")), re.I)
                           and re.search(r"conference|panelist|co.conven|symposium", str(quote)+str(row.get("explanation", "")), re.I)
                           and not re.search(r"fieldwork|field work|pilot project|project in|project based|field study", str(quote), re.I))
        if row.get("status") != "supported" or not grounded or conference_only:
            row["status"] = "not established"
            if not grounded or conference_only:
                row["explanation"] = "Insufficient direct evidence for this criterion. " + str(row.get("explanation", ""))
        person["criteria_assessment"].append(row)
