"""The package for migration 820 (topic becomes sector; nine more tables go) stays consistent.

See migrations/proposed/topic_cleanup_820/README.md.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations" / "proposed" / "deferred"
PACKAGE = ROOT / "migrations" / "proposed" / "topic_cleanup_820"
MIGRATION = DEFERRED / "820_topic_into_sector_and_cleanup.sql"
ROLLBACK = DEFERRED / "rollback" / "820_topic_into_sector_and_cleanup.sql"
FILES = [MIGRATION, ROLLBACK, *(PACKAGE / n for n in ("preflight.sql", "ledger.sql", "verify.sql"))]
REMOVED = ["topic", "actor_topic", "event_topic", "actor_location", "actor_relevance", "challenge",
           "person_discovery_profile", "event_claim", "architecture_v2_cutover_attestation",
           "architecture_v2_cutover_baseline"]
MOVED_TO_SECTOR = ["actor_fact", "actor_fact_current_pointer", "actor_strategic_connection_check",
                   "actor_verification_event", "collection_request", "entity_edge", "hub_assignment_evidence",
                   "proposed_hub", "record_verification", "review_item"]


def test_ledger_and_verify_carry_the_migration_checksum():
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert f"('820', 'migrations/proposed/deferred/820_topic_into_sector_and_cleanup.sql', '{digest}')" in (
        PACKAGE / "ledger.sql").read_text(encoding="utf-8")
    assert digest in (PACKAGE / "verify.sql").read_text(encoding="utf-8")


def test_files_are_lf_so_checksums_are_the_same_on_every_computer():
    for path in FILES:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_it_drops_exactly_the_ten_tables_and_keeps_sector():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sorted(re.findall(r"^DROP TABLE public\.(\w+);", sql, flags=re.MULTILINE)) == sorted(REMOVED)
    assert "DROP TABLE public.sector;" not in sql
    assert "820 needs 810" in sql and "820 is already applied" in sql


def test_every_topic_link_is_moved_to_sector_and_the_guard_comes_back_on():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in MOVED_TO_SECTOR:
        assert re.search(rf"ALTER TABLE public\.{table} ADD CONSTRAINT \w+ FOREIGN KEY \(topic_id\) "
                         r"REFERENCES public\.sector\(sector_id\)", sql), table
    assert "REFERENCES public.topic" not in sql
    disable = sql.index("DISABLE TRIGGER actor_sector_append_only")
    assert sql.index("ENABLE TRIGGER actor_sector_append_only") > disable
    assert sql.count("DISABLE TRIGGER") == 1
    assert "ADD COLUMN research_area text, ADD COLUMN public_profile_url text" in sql
    assert "CREATE VIEW public.actor_template" in sql and "top.topic" not in sql
    assert sql.count("COMMENT ON COLUMN public.actor_template.") == 20


def test_the_rollback_brings_back_topic_its_rows_ids_links_and_the_template():
    sql = ROLLBACK.read_text(encoding="utf-8")
    for table in REMOVED:
        assert re.search(rf"CREATE TABLE public\.{table} \(", sql), table
    assert sql.count("REFERENCES public.topic(topic_id)") >= len(MOVED_TO_SECTOR)
    assert re.search(r"INSERT INTO public\.topic .* VALUES\n(    \(.*\n){8}", sql)
    assert "INSERT INTO sector_id_back VALUES" in sql and sql.count("::uuid),  -- ") == 7
    assert "DROP COLUMN research_area, DROP COLUMN public_profile_url" in sql
    assert "top.topic" in sql and sql.count("COMMENT ON COLUMN public.actor_template.") == 21
    assert sql.rstrip().endswith("COMMIT;")


def test_no_code_reads_the_removed_tables_directly():
    platform = ROOT.parent
    code = [*platform.joinpath("src").rglob("*.py"), *platform.joinpath("backend").rglob("*.py"),
            *ROOT.joinpath("agents").rglob("*.py")]
    pattern = re.compile(r"\b(FROM|JOIN|INTO|UPDATE)\s+(public\.)?(topic|actor_topic|event_topic|actor_location|"
                         r"actor_relevance|challenge|person_discovery_profile|event_claim)\b")
    offenders = []
    for path in code:
        if "tests" in path.parts or "diagnostics" in path.parts or "evals" in path.parts:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            # the one place that still writes topic, only while the table exists (before 820)
            if "INSERT INTO topic (code, name, description, active)" in line:
                continue
            if pattern.search(line):
                offenders.append(f"{path.relative_to(platform)}: {line.strip()[:90]}")
    assert not offenders, offenders
