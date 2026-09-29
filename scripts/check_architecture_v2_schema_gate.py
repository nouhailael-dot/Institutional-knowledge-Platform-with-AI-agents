"""Block merging Architecture V2 until schema and matching code are deployed together."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "migrations" / "proposed" / "architecture_v2_schema_gate.json"
REQUIRED_FLAGS = (
    "schema_owner_approved",
    "additive_schema_deployed",
    "deferred_breaking_schema_deployed",
    "matching_application_code_deployed",
)


def main() -> None:
    state = json.loads(GATE.read_text(encoding="utf-8"))
    unmet = [name for name in REQUIRED_FLAGS if state.get(name) is not True]
    evidence = state.get("deployment_evidence")
    if not isinstance(evidence, list) or not evidence:
        unmet.append("deployment_evidence")
    if unmet:
        joined = ", ".join(unmet)
        raise SystemExit(
            "Architecture V2 schema gate is unmet; refusing merge into main. "
            f"Unmet conditions: {joined}"
        )
    print("Architecture V2 schema gate is met.")


if __name__ == "__main__":
    main()
