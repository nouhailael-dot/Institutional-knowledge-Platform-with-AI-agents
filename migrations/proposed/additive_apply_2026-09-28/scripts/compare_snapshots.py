"""Require exact row-count and object equality between two captured states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    actual = json.loads(Path(args.actual).read_text(encoding="utf-8"))
    report = {
        "row_counts_equal": expected["row_counts"] == actual["row_counts"],
        "objects_equal": expected["objects"] == actual["objects"],
        "expected_only_objects": {
            kind: sorted(set(values) - set(actual["objects"][kind]))
            for kind, values in expected["objects"].items()
        },
        "actual_only_objects": {
            kind: sorted(set(actual["objects"][kind]) - set(values))
            for kind, values in expected["objects"].items()
        },
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if not report["row_counts_equal"] or not report["objects_equal"]:
        raise SystemExit("rollback state differs from the fresh production copy")


if __name__ == "__main__":
    main()
