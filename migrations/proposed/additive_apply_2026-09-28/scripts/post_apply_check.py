"""Compare post-apply state with the pre-apply snapshot and list new objects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from capture_state import snapshot
from db_connection import guarded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = snapshot()
    changed = {
        table: {"before": count, "after": after["row_counts"].get(table)}
        for table, count in before["row_counts"].items()
        if after["row_counts"].get(table) != count
    }
    new_objects = {
        kind: sorted(set(after["objects"][kind]) - set(values))
        for kind, values in before["objects"].items()
    }
    report = {
        "existing_table_row_counts_unchanged": not changed,
        "changed_existing_table_counts": changed,
        "new_objects": new_objects,
        "after": after,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    if changed:
        raise SystemExit("existing table row counts changed")


if __name__ == "__main__":
    guarded(main)
