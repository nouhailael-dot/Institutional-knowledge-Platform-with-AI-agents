"""Streamlit UI. Two tabs:

  • Ask    — one question box, routed to SQL (counts) or RAG (meaning), cited.
  • Browse — walk the map: filter actors/hubs/events by structured fields.

Run from the project root:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

from src.retrieve import retrieve
from src.generate import stream_answer
from src.router import plan, run_sql, format_sql_answer
from src import browse

st.set_page_config(page_title="UM6P Intelligence", page_icon="🔎", layout="wide")


# --- cached data loads (read-only; the DB is never modified) ---------------
# Browse re-reads on every widget change, so cache the underlying queries.
# Clearing the Streamlit cache (press "C") reloads after the colleague edits data.
@st.cache_data(ttl=600)
def _actors():
    return browse.load_actors()


@st.cache_data(ttl=600)
def _hubs():
    return browse.load_hubs()


@st.cache_data(ttl=600)
def _events():
    return browse.load_events()


st.title("🔎 UM6P Intelligence")

ask_tab, browse_tab = st.tabs(["Ask", "Browse"])


# ===========================================================================
# ASK TAB — unchanged behavior: router picks SQL (exact) or RAG (cited).
# ===========================================================================
with ask_tab:
    st.caption("Plain-English search over the UM6P Global Hubs research database. "
               "Counting questions are answered exactly from the database; "
               "everything else is answered from the map with cited sources.")

    question = st.text_input(
        "Your question",
        placeholder="e.g. Who works on phosphogypsum?  ·  How many actors are at TRL 6+?",
    )

    if question:
        with st.spinner("Understanding your question…"):
            mode, sql = plan(question)

        if mode == "sql":
            try:
                cols, rows = run_sql(sql)
                answer = format_sql_answer(question, sql, cols, rows)
                st.subheader("Answer")
                st.markdown(answer)
                st.caption("⚡ Computed directly from the database — exact, not estimated.")
                with st.expander("SQL query used"):
                    st.code(sql, language="sql")
            except Exception:
                st.info("Falling back to map search…")
                mode = "semantic"

        if mode == "semantic":
            with st.spinner("Searching the map…"):
                hits = retrieve(question)

            if not hits:
                st.warning("No matching entities found in the map.")
            else:
                st.subheader("Answer")
                st.write_stream(stream_answer(question, hits))
                with st.expander(f"Sources ({len(hits)} entities retrieved)"):
                    for i, h in enumerate(hits, 1):
                        st.markdown(f"**{i}. {h['name']}**  ·  _{h['entity_type']}_")
                        preview = h["doc_text"][:300]
                        st.caption(preview + ("…" if len(h["doc_text"]) > 300 else ""))


# ===========================================================================
# BROWSE TAB — structured, filterable lists. No LLM; straight from the data.
# ===========================================================================
def _render_actor_detail(a: dict) -> None:
    """The drill-in card for one actor."""
    st.markdown(f"### {a['name']}")
    meta = []
    if a["actor_type"]:
        meta.append(a["actor_type"].replace("_", " "))
    loc = ", ".join(p for p in (a["city"], a["state"], a["country_raw"]) if p)
    if loc:
        meta.append(loc)
    if a["trl"] is not None:
        meta.append(f"TRL {a['trl']}")
    if meta:
        st.caption("  ·  ".join(meta))
    if a["website"]:
        st.markdown(f"🔗 [{a['website']}]({a['website']})")
    if a["description"]:
        st.write(a["description"])
    if a["hubs"]:
        st.caption("**In hubs:** " + " · ".join(a["hubs"]))


def _browse_actors() -> None:
    actors = _actors()
    opts = browse.actor_filter_options(actors)

    st.caption(f"{len(actors)} live actors in the map. Filter below.")

    c1, c2, c3 = st.columns(3)
    with c1:
        hub = st.selectbox("Hub", ["Any"] + opts["hubs"])
        hub = None if hub == "Any" else hub
    with c2:
        types = st.multiselect("Type", opts["types"],
                               format_func=lambda t: t.replace("_", " "))
    with c3:
        country = st.selectbox("Country", ["Any"] + opts["countries"])
        country = None if country == "Any" else country

    c4, c5, c6 = st.columns(3)
    with c4:
        state = st.selectbox("State", ["Any"] + opts["states"])
        state = None if state == "Any" else state
    with c5:
        min_trl = st.slider("Minimum TRL", 0, 9, 0,
                            help="0 = any. Only ~8% of actors carry a TRL rating, "
                                 "so a value above 0 narrows to that profiled set.")
    with c6:
        profiled_only = st.checkbox(
            "Deeply-profiled only",
            help="Show only actors with a 'why valuable for UM6P' write-up — the "
                 "hand-curated, richest records.")

    text = st.text_input("Search name / description",
                         placeholder="e.g. water, phosphate, Stanford")

    matches = browse.filter_actors(
        actors, hub=hub, types=types, country=country, state=state,
        min_trl=min_trl or None, profiled_only=profiled_only, text=text or None)

    st.markdown(f"**{len(matches)} actor{'s' if len(matches) != 1 else ''} match**")
    if not matches:
        st.info("No actors match these filters. Try widening them.")
        return

    df = pd.DataFrame([{
        "Name": a["name"],
        "Type": (a["actor_type"] or "").replace("_", " "),
        "Country": a["country"] or "—",
        "State": a["state"] or "—",
        # str, not int, so the column is one type (else Arrow errors on the "—").
        "TRL": str(a["trl"]) if a["trl"] is not None else "—",
    } for a in matches])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    names = [a["name"] for a in matches]
    chosen = st.selectbox("View full details for", names, key="actor_detail")
    picked = next(a for a in matches if a["name"] == chosen)
    _render_actor_detail(picked)


# Hub columns intentionally hidden from Browse: internal ids/bookkeeping and
# fields that are empty or unhelpful for browsing.
_HIDDEN_HUB_COLUMNS = {
    "hub_id", "region", "latitude", "longitude", "upstream_inputs",
    "downstream_outputs", "integrated_flow_description", "cross_hub_themes",
    "secondary_sectors", "source_id", "verification_status",
}


def _browse_hubs() -> None:
    hubs = _hubs()
    st.caption(f"{len(hubs)} hubs. Scroll the table sideways to see all columns, "
               "or open one below for a readable view.")

    # Full table: name and actor_count first, then the remaining hub columns
    # (minus the hidden ones).
    lead = ["name", "actor_count"]
    ordered = lead + [c for c in browse.hub_columns()
                      if c not in lead and c not in _HIDDEN_HUB_COLUMNS]
    df = pd.DataFrame(hubs)
    df = df[[c for c in ordered if c in df.columns]]
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    chosen = st.selectbox("View full details for", [h["name"] for h in hubs],
                          key="hub_detail")
    h = next(x for x in hubs if x["name"] == chosen)
    st.markdown(f"### {h['name']}")
    st.caption(f"{h['actor_count']} live actors")
    # Every populated column, labeled — the readable form of "all columns".
    for col in ordered:
        if col in ("name", "actor_count"):
            continue
        val = h.get(col)
        if val is None or str(val).strip() == "":
            continue
        st.markdown(f"**{col.replace('_', ' ')}**")
        st.write(val)


def _browse_events() -> None:
    events = _events()
    lo, hi = browse.event_date_bounds(events)
    n_dated = sum(1 for e in events if e["next_date"] is not None)

    c1, c2 = st.columns([3, 2])
    with c1:
        location = st.text_input("Location contains",
                                 placeholder="e.g. New York, USA, Switzerland")
    with c2:
        # "Any date" (default) keeps the 134 dateless events in view; the range
        # mode filters, but can only match the events that carry a date.
        date_mode = st.selectbox("Date", ["Any date", "Within a range…"],
                                 disabled=lo is None)

    date_from = date_to = None
    if date_mode == "Within a range…" and lo is not None:
        picked = st.date_input("Date range", value=(lo, hi),
                               min_value=lo, max_value=hi)
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            date_from, date_to = picked
        st.caption(f"Only {n_dated} of {len(events)} events have a scheduled date; "
                   "a range lists just those. Switch back to “Any date” to include "
                   f"the other {len(events) - n_dated}.")

    matches = browse.filter_events(events, location=location or None,
                                   date_from=date_from, date_to=date_to)

    st.markdown(f"**{len(matches)} event{'s' if len(matches) != 1 else ''} match**")
    if not matches:
        st.info("No events match these filters. Try widening them.")
        return

    df = pd.DataFrame([{
        "Event": e["name"],
        "Type": e["event_type"] or "—",
        "Location": e["location"] or "—",
        "Next date": str(e["next_date"]) if e["next_date"] else "—",
    } for e in matches])
    st.dataframe(df, use_container_width=True, hide_index=True)


with browse_tab:
    kind = st.radio("Browse", ["Actors", "Hubs", "Events"],
                    horizontal=True, label_visibility="collapsed")
    if kind == "Actors":
        _browse_actors()
    elif kind == "Hubs":
        _browse_hubs()
    else:
        _browse_events()
