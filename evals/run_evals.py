"""Run the eval set and print a retrieval score. No LLM call needed — this
tests RETRIEVAL directly (the layer that caps answer quality). For each
question, it checks whether every expected entity landed in the top-10.

    python -m evals.run_evals

Metric: recall@10 — of the entities that SHOULD have been retrieved, what
fraction actually were. 1.0 means retrieval found everything the team expected.
Without this number, tuning retrieve.py is guesswork.
"""

import json
import os

from src.retrieve import retrieve

HERE = os.path.dirname(__file__)


def load_questions() -> list[dict]:
    with open(os.path.join(HERE, "questions.json")) as f:
        data = json.load(f)
    # Skip unverified placeholder rows so a half-filled file still scores cleanly.
    return [q for q in data["questions"] if q.get("verified_by") != "unverified"]


def main() -> None:
    questions = load_questions()
    if not questions:
        print("No verified questions yet. Fill in evals/questions.json.")
        return

    total_expected = 0
    total_found = 0
    print(f"Running {len(questions)} verified eval questions...\n")

    for q in questions:
        hits = retrieve(q["question"], top_k=10)
        hit_names = [h["name"].lower() for h in hits]
        found, missed = [], []
        for expected in q["expected"]:
            e = expected.lower()
            if any(e in name for name in hit_names):
                found.append(expected)
            else:
                missed.append(expected)
        total_expected += len(q["expected"])
        total_found += len(found)

        status = "PASS" if not missed else "MISS"
        print(f"[{status}] {q['question']}")
        if missed:
            print(f"        missing from top-10: {missed}")

    recall = total_found / total_expected if total_expected else 0.0
    print(f"\nrecall@10 = {total_found}/{total_expected} = {recall:.2f}")


if __name__ == "__main__":
    main()
