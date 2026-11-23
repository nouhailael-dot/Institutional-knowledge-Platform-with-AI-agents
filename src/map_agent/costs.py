"""One gateway for paid map calls; never infer a $0 charge from missing usage.

Prices verified 2026-09-13, standard first-party global API, USD per MTok.
https://platform.claude.com/docs/en/about-claude/pricing
Token counts are estimates. Reservations add headroom, not a billing guarantee.
Only the controlled one-search Claude adapter may use a server tool.
"""
import math
import json
import time
from types import SimpleNamespace

from src.map_agent.run_store import BudgetStopped

PRICING_DATE = "2026-09-13"
PRICES = {
    "claude-sonnet-5": {"input": 2, "output": 10},
    "claude-haiku-4-5-20251001": {"input": 1, "output": 5},
}


def refused_status(exc) -> int | None:
    """The HTTP status when the API answered with an error response, else None.

    An error response (4xx/5xx) means the request was refused, so nothing was
    generated or billed. A timeout or a dropped connection has no response and
    stays uncertain.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and 400 <= status <= 599 and getattr(exc, "response", None) is not None:
        return status
    return None


# The answers that are certainly free: the service refused the request before
# doing any work (rate limited, overloaded, a server error reply).
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
RETRY_WAITS_S = (2, 5, 10, 20, 40)   # about a minute and a half in all
MAX_RETRY_WAIT_S = 60


def _retry_after(exc) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        value = float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def with_refusal_retries(call, run=None, *, sleep=time.sleep):
    """Run ``call``; when the service answers busy or rate limited, wait and try again.

    12 Nov 2026: a map and a Monitor request running together share the team's
    API limits, and the first "too many requests" failed the map. Only answers
    that are certainly free are retried (RETRYABLE_STATUSES), waiting as long as
    the service asks (capped). A timeout or a dropped connection is never
    retried: its cost is unknown and a retry could pay twice. Stop is honoured
    between attempts.
    """
    for attempt, wait in enumerate((*RETRY_WAITS_S, None)):
        try:
            return call()
        except Exception as exc:
            if wait is None or refused_status(exc) not in RETRYABLE_STATUSES:
                raise
            asked = _retry_after(exc)
            sleep(min(MAX_RETRY_WAIT_S, asked if asked is not None else wait))
            if run is not None:
                run.check()


def usage_cost(model, usage):
    rate = PRICES[model]
    if not isinstance(usage, dict) or any(usage.get(k) is None for k in ("input_tokens", "output_tokens")):
        raise ValueError("Token usage unavailable")
    def amount(key, source=usage):
        value = source.get(key) or 0
        if not isinstance(value, int) or value < 0:
            raise ValueError("Invalid usage value")
        return value
    # Cache input buckets are disjoint from base input; detailed creation
    # buckets replace the creation total and must never be counted twice.
    creation = usage.get("cache_creation") or {}
    if creation:
        writes = (amount("ephemeral_5m_input_tokens", creation) * 1.25 +
                  amount("ephemeral_1h_input_tokens", creation) * 2)
        if sum(amount(k, creation) for k in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")) != amount("cache_creation_input_tokens"):
            raise ValueError("Incomplete cache usage")
    else:
        writes = amount("cache_creation_input_tokens") * 2  # conservative if TTL is unknown
    server = usage.get("server_tool_use") or {}
    if any(v for k, v in server.items() if k not in {"web_search_requests", "web_fetch_requests"}):
        raise ValueError("Unpriced server tool usage")
    return math.ceil((amount("input_tokens") + amount("cache_read_input_tokens") * .1 + writes) * rate["input"] +
                     amount("output_tokens") * rate["output"] + amount("web_search_requests", server) * 10_000)


def paid_message(client, run, stage, operation_key=None, **kwargs):
    if run is None:
        raise BudgetStopped("A tracked map session is required before any paid call.")
    run.check()
    if operation_key:
        saved = run.store.operation(run.id, operation_key)
        if saved is not None:
            return SimpleNamespace(id=saved.get("id"), stop_reason=saved.get("stop_reason"),
                                   content=[SimpleNamespace(**b) for b in saved["content"]])
    model = kwargs["model"]
    if model not in PRICES:
        raise BudgetStopped("This model has no configured price; no API call was made.")
    tools = kwargs.get("tools", [])
    server_tools = [tool for tool in tools if tool.get("type", "custom") != "custom"]
    bounded_search = (len(tools) == 1 and len(server_tools) == 1
                      and server_tools[0].get("type") == "web_search_20250305"
                      and server_tools[0].get("name") == "web_search"
                      and server_tools[0].get("max_uses") == 1
                      and server_tools[0].get("allowed_callers") == ["direct"]
                      and not any(k in server_tools[0] for k in ("allowed_domains", "blocked_domains")))
    if server_tools and not bounded_search:
        reason = ("Web research is paused: its current provider-side loop cannot be safely "
                  "budgeted. Only one direct Claude web search per tracked request is allowed.")
        run.store.stop(run.id, "budget_stopped", reason)
        raise BudgetStopped(reason)
    if kwargs.get("thinking") or kwargs.get("service_tier") not in (None, "standard"):
        raise BudgetStopped("Unsupported pricing configuration")
    # No SDK automatic retries: an ambiguous timeout must retain its allowance.
    safe_client = client.with_options(max_retries=0, timeout=90.0)
    count_payload = {k: v for k, v in kwargs.items()
                     if k in ("model", "messages", "system", "tools", "tool_choice")}
    if bounded_search:
        # Claude's count_tokens endpoint rejects all server tools. Estimate this
        # small request locally instead. One token per UTF-8 byte plus 2k tool/
        # message overhead is intentionally conservative; search-result tokens
        # are reserved separately below.
        request_tokens = len(json.dumps(count_payload, ensure_ascii=False).encode("utf-8")) + 2048
    else:
        counted = with_refusal_retries(lambda: safe_client.messages.count_tokens(**count_payload), run)
        request_tokens = counted.input_tokens
    # Token counting is free. Its estimates can vary from message usage; keep
    # headroom, reserve worst-case cache writes, and max output in advance.
    # A bounded basic search includes result text in the model input. Reserve a
    # conservative 20k-token result allowance; actual provider-reported usage is
    # settled afterward and an overrun blocks subsequent work.
    max_input = math.ceil(request_tokens * 1.2) + 1024 + (20_000 if bounded_search else 0)
    rate = PRICES[model]
    reservation = math.ceil(max_input * rate["input"] * 2 + kwargs["max_tokens"] * rate["output"]
                              + (10_000 if bounded_search else 0))
    pricing = {**rate, "date": PRICING_DATE, "web_search_usd": .01,
               "source": "https://platform.claude.com/docs/en/about-claude/pricing"}
    call_id = run.store.reserve(run.id, stage, model, reservation, pricing,
                                operation_key=operation_key, attempt=run.attempt)
    try:
        run.check()
    except Exception:
        run.store.settle(call_id, 0, {}, {"content": [], "stop_reason": "cancelled"}, "Cancelled before dispatch")
        raise
    try:
        response = with_refusal_retries(lambda: safe_client.messages.create(**kwargs), run)
    except Exception as exc:
        status = refused_status(exc)
        if status is not None:
            # 12 Nov 2026: the API answered with an error (rate limited,
            # overloaded, invalid request): nothing was generated or charged.
            # Recording it as uncertain locked the map for good.
            run.store.settle(call_id, 0, {}, None, f"{type(exc).__name__} (HTTP {status}): not charged")
            raise
        # A timeout or a dropped connection is truly ambiguous. Keep reserved
        # funds and require billing reconciliation instead of a retry.
        run.store.settle(call_id, None, None, None, type(exc).__name__)
        raise
    raw_usage = getattr(response, "usage", None)
    usage = raw_usage.model_dump(mode="json") if hasattr(raw_usage, "model_dump") else raw_usage
    content = [b.model_dump(mode="json") if hasattr(b, "model_dump") else b for b in response.content]
    saved = {"id": getattr(response, "id", None), "stop_reason": response.stop_reason, "content": content}
    try:
        cost = usage_cost(model, usage)
        error = None
    except (ValueError, TypeError, KeyError) as exc:
        cost, error = None, str(exc)
    run.store.settle(call_id, cost, usage, saved, error)
    # Return evidence even when the caller pressed Stop during the request.
    # Its next paid operation will be rejected by the store.
    return response
