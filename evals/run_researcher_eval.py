"""
Eval gate for the researcher extractor (extractor #2).

Runs extract_researchers() against hand-labelled talent narratives and reports
precision / recall / F1 on the set of person names found per snippet. The rule:
do not trust an --apply run until this clears your bar (suggested recall >= 80%,
precision >= 85% — precision matters, a false person is junk to clean up later).

IMPORTANT: the shipped snippets are synthetic. Replace them with real
talent_narrative excerpts from a handful of your hubs for a meaningful number.

Usage (from the repo root, venv active):
    python evals/run_researcher_eval.py
"""

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root on path

from src.enrichment.claude_client import SONNET  # noqa: E402
from src.enrichment.extractors.researchers import extract_researchers  # noqa: E402

GOLDEN = pathlib.Path("evals/golden_researchers.jsonl")


def norm(s: str) -> str:
    s = re.sub(r"\([^)]*\)", "", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def main():
    tp = fp = fn = 0
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        ex = json.loads(line)
        pred = {norm(p["full_name"])
                for p in extract_researchers(ex["hub"], ex["talent_narrative"], model=SONNET)}
        gold = {norm(n) for n in ex["expected_names"]}
        t, f, m = len(pred & gold), len(pred - gold), len(gold - pred)
        tp += t
        fp += f
        fn += m
        print(f"{ex['hub'][:40]:<40} TP={t} FP={f} FN={m}")
        if pred - gold:
            print(f"    extra (false positives): {sorted(pred - gold)}")
        if gold - pred:
            print(f"    missed: {sorted(gold - pred)}")

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    print(f"\nPrecision {prec:.0%}   Recall {rec:.0%}   F1 {f1:.0%}")
    print("Bar before a full --apply run: recall >= 80%, precision >= 85%.")


if __name__ == "__main__":
    main()