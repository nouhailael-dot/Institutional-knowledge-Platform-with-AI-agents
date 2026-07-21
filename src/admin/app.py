"""
GHUS Platform — Admin & Browse App (Phase 3)
================================================
A browser over the canonical Supabase database, plus a working review queue.

Design choices (read before changing):
- This app does NOT import from src.db.models. It reflects the live schema with
  SQLAlchemy, so it never depends on exact column names and auto-adapts when
  Phase 4 adds tables. No sys.path juggling, no model drift.
- The ONLY place this app writes is the Review queue, and the only column it
  writes is verification_status (plus updated_at when present). Everything else
  is read-only.
- Provenance is shown everywhere: any *_id foreign key (including source_id)
  is resolved to the referenced row's name, so every row carries its origin.

Run from the repo root with your venv active:
    streamlit run src/admin/app.py
"""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, func, or_, select, update
from sqlalchemy.engine import Engine

load_dotenv()  # reads DATABASE_URL from the .env at the repo root

st.set_page_config(page_title="GHUS Platform", layout="wide", page_icon="🧭")

# Columns we prefer, in order, when picking a human-readable label for a row.
NAME_COL_PRIORITY = ("name", "full_name", "title", "label", "slug", "acronym")


# --------------------------------------------------------------------------- #
# Connection + schema reflection (cached for the whole session)
# --------------------------------------------------------------------------- #
@st.cache_resource
def get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        st.error(
            "DATABASE_URL is not set. Make sure you're running this from the "
            "repo root and that .env contains DATABASE_URL."
        )
        st.stop()
    # pool_pre_ping survives the Supabase pooler dropping idle connections.
    return create_engine(url, pool_pre_ping=True)


@st.cache_resource
def get_metadata() -> MetaData:
    md = MetaData()
    md.reflect(bind=get_engine())
    return md


def run_df(stmt) -> pd.DataFrame:
    """Execute a SQLAlchemy statement and return a DataFrame (version-robust)."""
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Reflection helpers
# --------------------------------------------------------------------------- #
def pk_col(table):
    pk = list(table.primary_key.columns)
    return pk[0].name if pk else None


def is_single_pk(table) -> bool:
    return len(list(table.primary_key.columns)) == 1


def display_col(table) -> str:
    cols = {c.name for c in table.columns}
    for cand in NAME_COL_PRIORITY:
        if cand in cols:
            return cand
    return pk_col(table) or list(cols)[0]


def text_columns(table):
    out = []
    for c in table.columns:
        try:
            if c.type.python_type is str:
                out.append(c)
        except (NotImplementedError, AttributeError):
            pass
    return out


def outbound_fks(table):
    """col_name -> referenced table name (e.g. 'source_id' -> 'source')."""
    out = {}
    for fk in table.foreign_keys:
        out[fk.parent.name] = fk.column.table.name
    return out


def inbound_fks(md, target_name):
    """Tables that point AT this one: list of (child_table, local_col_name)."""
    out = []
    for t in md.tables.values():
        for fk in t.foreign_keys:
            if fk.column.table.name == target_name:
                out.append((t, fk.parent.name))
    return out


@st.cache_data(show_spinner=False)
def label_map(table_name: str) -> dict:
    """Map {pk_value: human_label} for a table, for resolving foreign keys."""
    md = get_metadata()
    t = md.tables[table_name]
    pk, dcol = pk_col(t), display_col(t)
    if pk is None:
        return {}
    df = run_df(select(t.c[pk], t.c[dcol]))
    if df.empty:
        return {}
    return dict(zip(df[pk], df[dcol]))


def resolve_ids(table, df: pd.DataFrame) -> pd.DataFrame:
    """Replace foreign-key id columns with the referenced row's label."""
    if df.empty:
        return df
    df = df.copy()
    for col, tgt in outbound_fks(table).items():
        if col in df.columns:
            m = label_map(tgt)
            df[col] = df[col].map(lambda v: m.get(v, v) if v is not None else None)
    return df


def set_status(table, pk_name: str, pk_values: list, new_status: str) -> int:
    """The app's only write: set verification_status on the given rows.
    Bumps updated_at when the column exists. One auto-committed transaction."""
    values = {"verification_status": new_status}
    if "updated_at" in table.columns.keys():
        values["updated_at"] = func.now()
    stmt = update(table).where(table.c[pk_name].in_(list(pk_values))).values(**values)
    with get_engine().begin() as conn:
        result = conn.execute(stmt)
    return result.rowcount or 0


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_overview(md):
    st.header("Database at a glance")
    st.caption("Live row counts across every table. This is your demo opener.")
    rows = []
    with get_engine().connect() as conn:
        for name in sorted(md.tables):
            n = conn.execute(select(func.count()).select_from(md.tables[name])).scalar()
            rows.append({"table": name, "rows": int(n)})
    df = pd.DataFrame(rows)
    total = df["rows"].sum()
    c1, c2 = st.columns(2)
    c1.metric("Tables", len(df))
    c2.metric("Total rows", f"{total:,}")
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_browse(md):
    st.header("Browse any table")
    name = st.selectbox("Table", sorted(md.tables))
    t = md.tables[name]

    c1, c2, c3 = st.columns([3, 1, 1])
    q = c1.text_input("Search (matches any text column)")
    limit = c2.number_input("Max rows", 10, 5000, 200, step=50)
    resolve = c3.toggle("Resolve IDs → names", value=True)

    stmt = select(t)
    tcols = text_columns(t)
    if q and tcols:
        stmt = stmt.where(or_(*[c.ilike(f"%{q}%") for c in tcols]))
    stmt = stmt.limit(int(limit))

    df = run_df(stmt)
    if df.empty:
        st.info("No rows match.")
        return
    if resolve:
        df = resolve_ids(t, df)
    st.caption(f"Showing {len(df)} row(s).")
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_hub_explorer(md):
    st.header("Hub explorer")
    if "hub" not in md.tables:
        st.warning("No 'hub' table found in the schema.")
        return
    hub = md.tables["hub"]
    pk, dcol = pk_col(hub), display_col(hub)

    hubs = run_df(select(hub.c[pk], hub.c[dcol]).order_by(hub.c[dcol]))
    if hubs.empty:
        st.info("No hubs loaded yet.")
        return
    choice = st.selectbox(f"Hub ({len(hubs)})", hubs[dcol].tolist())
    hub_id = hubs.loc[hubs[dcol] == choice, pk].iloc[0]

    row = run_df(select(hub).where(hub.c[pk] == hub_id)).iloc[0]

    # Split fields: long narratives vs short metadata.
    fk_targets = outbound_fks(hub)
    short, narratives = {}, {}
    for c in hub.columns:
        val = row[c.name]
        if isinstance(val, str) and len(val) > 200:
            narratives[c.name] = val
        else:
            # resolve any foreign key id to its label (incl. source_id provenance)
            if c.name in fk_targets and val is not None:
                val = label_map(fk_targets[c.name]).get(val, val)
            short[c.name] = val

    st.subheader(choice)
    st.dataframe(
        pd.DataFrame(short.items(), columns=["field", "value"]),
        use_container_width=True, hide_index=True,
    )

    if narratives:
        st.markdown("#### Narratives")
        for field, text in narratives.items():
            with st.expander(field, expanded=False):
                st.markdown(text)

    # Everything that points back at this hub: members, funding, scores, etc.
    st.markdown("#### Related records")
    related = inbound_fks(md, "hub")
    if not related:
        st.caption("Nothing references this hub yet.")
    for child, local_col in related:
        sub = run_df(select(child).where(child.c[local_col] == hub_id))
        if sub.empty:
            continue
        sub = resolve_ids(child, sub)
        st.markdown(f"**{child.name}** — {len(sub)} row(s)")
        st.dataframe(sub, use_container_width=True, hide_index=True)


def page_review(md):
    st.header("Review queue")
    targets = [
        t for t in md.tables.values()
        if "verification_status" in {c.name for c in t.columns}
    ]
    if not targets:
        st.info("No tables carry a verification_status column.")
        return

    name = st.selectbox("Table", sorted(t.name for t in targets))
    t = md.tables[name]
    pk = pk_col(t)

    # Status breakdown for this table.
    counts = run_df(
        select(t.c.verification_status, func.count().label("n"))
        .group_by(t.c.verification_status)
    )
    if not counts.empty:
        st.dataframe(counts, use_container_width=True, hide_index=True)

    options = counts["verification_status"].dropna().tolist() if not counts.empty else []
    if not options:
        st.success("Nothing to review here.")
        return
    default = options.index("needs_review") if "needs_review" in options else 0
    status = st.selectbox("Filter by status", options, index=default)

    limit = st.number_input("Max rows to load", 10, 2000, 200, step=50)
    raw = run_df(select(t).where(t.c.verification_status == status).limit(int(limit)))
    if raw.empty:
        st.success(f"Queue clear — nothing with status '{status}'.")
        return

    # Composite-PK tables can't be targeted by this simple write path.
    if pk is None or not is_single_pk(t):
        st.warning("This table has a composite/no primary key, so review writes "
                   "are disabled. Showing rows read-only.")
        st.dataframe(resolve_ids(t, raw), use_container_width=True, hide_index=True)
        return

    st.caption("Tick the rows you've checked, then promote or reject them. "
               "IDs are resolved to names for readability; the underlying keys "
               "are used for the write.")

    display = resolve_ids(t, raw)
    display.insert(0, "select", False)
    edited = st.data_editor(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={"select": st.column_config.CheckboxColumn("✓", help="Tick to act on")},
        disabled=[c for c in display.columns if c != "select"],
        key=f"review_editor_{name}_{status}",
    )

    chosen_idx = edited.index[edited["select"]].tolist()
    chosen_pks = raw.loc[chosen_idx, pk].tolist()
    st.caption(f"{len(chosen_pks)} row(s) selected.")

    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("✓ Mark verified", type="primary", disabled=not chosen_pks):
        n = set_status(t, pk, chosen_pks, "verified")
        st.success(f"Promoted {n} row(s) to verified.")
        st.rerun()
    if c2.button("✗ Mark rejected", disabled=not chosen_pks):
        n = set_status(t, pk, chosen_pks, "rejected")
        st.warning(f"Marked {n} row(s) as rejected.")
        st.rerun()


PAGES = {
    "Overview": page_overview,
    "Browse tables": page_browse,
    "Hub explorer": page_hub_explorer,
    "Review queue": page_review,
}


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def main():
    md = get_metadata()
    st.sidebar.title("GHUS Platform")
    host = os.environ.get("DATABASE_URL", "").split("@")[-1].split("/")[0]
    st.sidebar.caption(f"Connected: {host or 'unknown'}")
    choice = st.sidebar.radio("Page", list(PAGES))
    if st.sidebar.button("↻ Refresh schema cache"):
        get_metadata.clear()
        label_map.clear()
        st.rerun()
    PAGES[choice](md)


if __name__ == "__main__":
    main()