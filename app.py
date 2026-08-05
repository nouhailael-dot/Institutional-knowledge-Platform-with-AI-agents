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
from src.documents.extract import ExtractionError, extract_text
from src.documents.doc_store import STATE_KEY as DOC_STATE_KEY, build_store, search_chunks

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


# --- light global polish -----------------------------------------------------
# Streamlit's design ceiling is real, but a little CSS tightens spacing, gives
# tabs/metrics/expanders more room to breathe, and reads consistently in both
# light and dark mode (no hard-coded backgrounds that fight the theme).
st.markdown("""
<style>
  .block-container { padding-top: 2.5rem; max-width: 1100px; }
  /* Tabs: larger labels, a clear underline on the active one. */
  button[data-baseweb="tab"] { font-size: 1.05rem; font-weight: 600; }
  /* Metric cards: subtle bordered tiles instead of bare numbers. */
  div[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 10px; padding: .75rem 1rem;
  }
  div[data-testid="stMetricLabel"] { opacity: .7; font-size: .8rem; }
  /* Expanders: rounded, lightly separated. */
  div[data-testid="stExpander"] details {
    border-radius: 10px; border-color: rgba(128,128,128,.25);
  }
  /* Section headings a touch tighter to their content. */
  h3, h4 { margin-bottom: .3rem; }
</style>
""", unsafe_allow_html=True)

st.title("🔎 UM6P Intelligence")

ask_tab, browse_tab = st.tabs(["Ask", "Browse"])


# ===========================================================================
# ASK TAB — unchanged behavior: router picks SQL (exact) or RAG (cited).
# ===========================================================================
with ask_tab:
    st.caption("Plain-English search over the UM6P Global Hubs research database. "
               "Counting questions are answered exactly from the database; "
               "everything else is answered from the map with cited sources.")

    with st.expander("📎 Attach a document (optional)"):
        uploaded = st.file_uploader(
            "Ask questions using this document AND the database together. "
            "Nothing here is saved — it's cleared when you remove the file "
            "or close the tab.",
            type=["pdf", "txt", "md"],
            accept_multiple_files=False,
        )

    if uploaded is None:
        for k in ("doc_name", DOC_STATE_KEY, "doc_answer", "doc_sources"):
            st.session_state.pop(k, None)
    elif st.session_state.get("doc_name") != uploaded.name:
        # (Re)build only when the file changes, not on every Streamlit rerun.
        try:
            with st.spinner("Reading the document…"):
                text = extract_text(uploaded.getvalue(), uploaded.name)
        except ExtractionError as exc:
            st.error(str(exc))
            uploaded = None
        else:
            with st.spinner("Indexing the document…"):
                st.session_state[DOC_STATE_KEY] = build_store(text, uploaded.name)
            st.session_state["doc_name"] = uploaded.name
            st.session_state.pop("doc_answer", None)
            st.session_state.pop("doc_sources", None)

    if uploaded is not None:
        st.caption(f"📎 Attached: **{uploaded.name}** — answers below draw on "
                   "this document AND the database. Remove the file above to "
                   "go back to database-only search.")

        # A form (not a live text_input) so opening the Sources expander below
        # doesn't silently trigger a fresh paid answer on every rerun.
        with st.form("doc_ask_form"):
            doc_question = st.text_input(
                "Your question",
                placeholder="e.g. What's the proposed budget, and which of "
                            "our actors could partner on this?",
            )
            asked = st.form_submit_button("Ask", type="primary")

        if asked and doc_question.strip():
            with st.spinner("Searching the document and the map…"):
                map_hits = retrieve(doc_question, top_k=8)
                doc_hits = search_chunks(st.session_state.get(DOC_STATE_KEY), doc_question)
                merged = doc_hits + map_hits
            st.session_state["doc_sources"] = merged
            if merged:
                st.subheader("Answer")
                st.session_state["doc_answer"] = st.write_stream(
                    stream_answer(doc_question, merged))
            else:
                st.session_state.pop("doc_answer", None)
        elif st.session_state.get("doc_answer"):
            st.subheader("Answer")
            st.markdown(st.session_state["doc_answer"])

        if "doc_sources" in st.session_state:
            merged = st.session_state["doc_sources"]
            if not merged:
                st.warning("Nothing matched in the document or the database.")
            else:
                with st.expander(f"Sources ({len(merged)}: document passages "
                                 "+ database entities)"):
                    for i, h in enumerate(merged, 1):
                        tag = ("📄 document" if h["entity_type"] == "uploaded_document"
                              else h["entity_type"])
                        st.markdown(f"**{i}. {h['name']}**  ·  _{tag}_")
                        preview = h["doc_text"][:300]
                        st.caption(preview + ("…" if len(h["doc_text"]) > 300 else ""))

    else:
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

# Longer than this, a field is treated as a narrative write-up (shown in an
# expander) rather than a short value (shown in the field/value table).
_NARRATIVE_MIN_CHARS = 200


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
    chosen = st.selectbox(f"Hub ({len(hubs)})", [h["name"] for h in hubs],
                          key="hub_detail")
    h = next(x for x in hubs if x["name"] == chosen)
    _render_hub_detail(h)


# Fields promoted to the metric row / subtitle, so they aren't repeated in the
# details grid below. Everything else populated shows up there or as a narrative.
_HUB_HEADLINE_FIELDS = {
    "name", "actor_count", "primary_city", "state", "country",
    "primary_sectors", "confidence",
}


def _render_hub_detail(h: dict) -> None:
    """A readable, card-style detail view for one hub."""
    st.markdown(f"### {h['name']}")

    # Location subtitle, e.g. "Phoenix – Tucson · USA".
    loc = " · ".join(p for p in (h.get("primary_city"), h.get("state"),
                                 h.get("country")) if p and str(p).strip())
    if loc:
        st.caption(loc)

    # Metric tiles: the numbers you glance at first.
    m1, m2, m3 = st.columns(3)
    m1.metric("Live actors", h["actor_count"])
    sector = (h.get("primary_sectors") or "").split(",")[0].strip() or "—"
    m2.metric("Primary sector", sector.title() if sector != "—" else "—")
    conf = h.get("confidence")
    m3.metric("Confidence", f"{float(conf):.2f}" if conf not in (None, "") else "—")

    # Split remaining populated fields: short values -> a two-column grid;
    # long write-ups -> collapsible narratives (same split as the colleague's
    # hub explorer, but rendered as a clean grid instead of a raw table).
    short, narratives = [], {}
    for col in ordered_hub_cols():
        if col in _HUB_HEADLINE_FIELDS:
            continue
        val = h.get(col)
        if val is None or str(val).strip() == "":
            continue
        if isinstance(val, str) and len(val) > _NARRATIVE_MIN_CHARS:
            narratives[col] = val
        else:
            short.append((col.replace("_", " "), val))

    if short:
        with st.container(border=True):
            for i in range(0, len(short), 2):
                cols = st.columns(2)
                for slot, (field, val) in zip(cols, short[i:i + 2]):
                    slot.caption(field)
                    slot.markdown(f"**{val}**")

    if narratives:
        st.markdown("#### Narratives")
        for field, text in narratives.items():
            with st.expander(field.replace("_", " "), expanded=False):
                st.markdown(text)

    st.markdown("#### Actors in this hub")
    related = [a for a in _actors() if h["name"] in a["hubs"]]
    if not related:
        st.caption("No live actors linked to this hub yet.")
    else:
        rel_df = pd.DataFrame([{
            "Name": a["name"],
            "Type": (a["actor_type"] or "").replace("_", " "),
            "Country": a["country"] or "—",
            "TRL": str(a["trl"]) if a["trl"] is not None else "—",
        } for a in related])
        with st.container(border=True):
            st.dataframe(rel_df, use_container_width=True, hide_index=True)


def ordered_hub_cols() -> list[str]:
    """Hub columns in display order, minus the hidden bookkeeping ones."""
    lead = ["name", "actor_count"]
    return lead + [c for c in browse.hub_columns()
                   if c not in lead and c not in _HIDDEN_HUB_COLUMNS]


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
