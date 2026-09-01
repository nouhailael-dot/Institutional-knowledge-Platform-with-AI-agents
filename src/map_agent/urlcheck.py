"""Layer 2 — URL liveness check. Pure Python, no LLM, no cost.

Confirms the URLs an entity carries (its website + its evidence sources)
actually resolve. Kills dead and hallucinated links before they reach the
user. Runs on demand (phase 2), concurrently across all URLs.

Classification is deliberately forgiving about bot-blocking: a 401/403/405/429
means the server answered, so the site clearly exists — we call that "blocked",
not "dead". Only real "not found" (404/410), server errors, and connection
failures count against a link.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

TIMEOUT = 6          # seconds per request
MAX_WORKERS = 8
_UA = "Mozilla/5.0 (compatible; UM6P-MapBot/1.0; +research)"

# HTTP status -> our verdict. ok=True means "the link is usable".
_BLOCKED = {401, 403, 405, 429}   # server answered but refused the bot


def _check_one(url: str) -> dict:
    """Check a single URL. Returns {url, ok, status, note}."""
    if not url or not url.strip():
        return {"url": url, "ok": False, "status": None, "note": "empty"}

    target = url.strip()
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    req = Request(target, method="GET", headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.status
            return {"url": url, "ok": True, "status": code, "note": "live"}
    except HTTPError as e:
        if e.code in _BLOCKED:
            return {"url": url, "ok": True, "status": e.code, "note": "blocked"}
        if e.code in (404, 410):
            return {"url": url, "ok": False, "status": e.code, "note": "not found"}
        return {"url": url, "ok": False, "status": e.code, "note": "http error"}
    except URLError as e:
        return {"url": url, "ok": False, "status": None, "note": f"unreachable: {e.reason}"}
    except Exception as e:
        return {"url": url, "ok": False, "status": None, "note": f"error: {e}"}


def check_urls(urls: list[str]) -> dict[str, dict]:
    """Check many URLs concurrently. Returns {url: result}. Deduplicates."""
    unique = list({u for u in urls if u and u.strip()})
    results: dict[str, dict] = {}
    if not unique:
        return results
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for res in pool.map(_check_one, unique):
            results[res["url"]] = res
    return results


def _entity_urls(entity: dict) -> list[str]:
    """All URLs an entity carries: its website + every source URL."""
    urls = []
    web = entity.get("website")
    if web:
        urls.append(web)
    for s in entity.get("sources", []) or []:
        u = s.get("url")
        if u:
            urls.append(u)
    return urls


def verify_links(entities: list[dict]) -> list[dict]:
    """Annotate each entity with link-check results (mutates in place).

    Adds to each entity:
      _link_check: {"website": <result|None>, "sources": [<result>, ...]}
      _links_ok:   True if the website is live OR any source is live.
    """
    # Gather + check every URL across all entities once.
    all_urls = [u for e in entities for u in _entity_urls(e)]
    checked = check_urls(all_urls)

    for e in entities:
        web = e.get("website")
        web_res = checked.get(web) if web else None
        src_res = [checked[s["url"]] for s in (e.get("sources") or [])
                   if s.get("url") and s["url"] in checked]

        e["_link_check"] = {"website": web_res, "sources": src_res}
        e["_links_ok"] = bool(
            (web_res and web_res["ok"]) or any(r["ok"] for r in src_res)
        )
    return entities
