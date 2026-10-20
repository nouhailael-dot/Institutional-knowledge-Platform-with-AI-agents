"""
Eval gate for the actor-type classifier.

Runs the SAME classify_actor() used in production against a hand-labelled
golden set, and reports accuracy. The rule: do not trust an --apply run until
this passes your bar (suggested >= 85% overall, and no class at 0%).

Candidate vocab here is the set of expected labels in the golden file, so the
eval is self-contained and needs no database. IMPORTANT: edit the expected
labels in evals/golden_dataset.jsonl to match the exact actor_type codes your
DB uses (run the enrichment script once to print your real candidate list).

Usage (from the repo root, venv active):
    python evals/run_eval.py
"""

import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root on path

from src.enrichment.claude_client import HAIKU  # noqa: E402
from src.enrichment.extractors.actor_type import classify_actor  # noqa: E402

GOLDEN = pathlib.Path("evals/golden_dataset.jsonl")


def load_golden() -> list[dict]:
    items = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def main():
    items = load_golden()
    candidates = sorted({it["expected_type"] for it in items
                         if it["expected_type"] != "other"})
    print(f"Candidates from golden set ({len(candidates)}): {', '.join(candidates)}\n")

    correct = 0
    per_class = defaultdict(lambda: [0, 0])  # expected -> [correct, total]
    misses = []
    for it in items:
        r = classify_actor(it["actor_name"], it.get("description", ""),
                           candidates, model=HAIKU)
        pred, exp = r["actor_type"], it["expected_type"]
        ok = pred == exp
        correct += ok
        per_class[exp][1] += 1
        per_class[exp][0] += ok
        print(f"{'OK ' if ok else 'XX '}{it['actor_name'][:38]:<38} "
              f"exp={exp:<26} pred={pred:<26} conf={r['confidence']:.2f}")
        if not ok:
            misses.append((it["actor_name"], exp, pred, r["reasoning"]))

    n = len(items)
    print(f"\nOverall: {correct}/{n} = {correct / n:.0%}")
    print("Per class (correct/total):")
    for label, (c, t) in sorted(per_class.items()):
        print(f"  {label:<26} {c}/{t}")
    if misses:
        print("\nMisses:")
        for name, exp, pred, why in misses:
            print(f"  {name}: expected {exp}, got {pred} — {why}")


if __name__ == "__main__":
    main()