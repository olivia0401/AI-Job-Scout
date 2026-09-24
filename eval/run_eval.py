# -*- coding: utf-8 -*-
"""Resume-to-JD match evaluation: check the scorer's *ranking* against hand labels.

A scorer only has an "accuracy" once it is compared with labelled data. This
script reads eval/dataset.jsonl, scores every row with matching.analyze_job
(0-100), compares the scores with the human labels and prints:

  * Spearman rank correlation - does the score order jobs the way a human
                                would? (-1..1, closer to +1 is better)
  * Precision@k               - of the top-k scored jobs, how many are
                                actually strong/medium?
  * NDCG@k                    - ranking quality with labels as gains
                                (closer to 1 is better)

It is fully offline: no network, no API keys, no Flask.

Usage:
    python eval/run_eval.py                 # defaults: my_years=2, k=5
    python eval/run_eval.py --years 4 --k 3
    python eval/run_eval.py --data eval/my_labeled.jsonl

Row format (one JSON object per line):
    {"id": "s1",
     "resume_skills": ["python", "pytorch", "llm"],   // or "resume_text"
     "jd_title": "Senior ML Engineer",
     "jd_text": "...job description text...",
     "label": "strong"}                                 // strong|medium|weak|none

Label -> ordinal gain: strong=3, medium=2, weak=1, none=0.
"Relevant" (for Precision@k) means label in {strong, medium}.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matching  # noqa: E402  (pure scoring logic; importing app.py is not needed)

LABEL_GAIN = {"strong": 3, "medium": 2, "weak": 1, "none": 0}
DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset.jsonl")


def load_dataset(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  Skipping line {ln} (invalid JSON): {e}")
    return rows


def score_row(row, my_years):
    if row.get("resume_skills") is not None:
        kws = set(matching._CANON.get(k, k) for k in row["resume_skills"])
    else:
        kws = matching.extract_skills(row.get("resume_text", ""))
    title = row.get("jd_title", "")
    level = matching.classify_level(title)
    res = matching.analyze_job(title, row.get("jd_text", ""), kws, my_years, level)
    return res["score"]


def _rank(values):
    """Average ranks (ties share the mean rank), for Spearman."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    if len(xs) < 2:
        return float("nan")
    rx, ry = _rank(xs), _rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (dx * dy) if dx and dy else float("nan")


def precision_at_k(ranked_labels, k):
    top = ranked_labels[:k]
    if not top:
        return float("nan")
    rel = sum(1 for lab in top if LABEL_GAIN.get(lab, 0) >= 2)
    return rel / len(top)


def ndcg_at_k(ranked_gains, k):
    def dcg(gains):
        return sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
    ideal = sorted(ranked_gains, reverse=True)
    idcg = dcg(ideal)
    return dcg(ranked_gains) / idcg if idcg else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--years", type=int, default=2,
                    help="candidate's years of experience (used for level matching)")
    ap.add_argument("--k", type=int, default=5, help="k for Precision@k / NDCG@k")
    args = ap.parse_args()

    if not os.path.exists(args.data):
        print(f"Dataset not found: {args.data}")
        return 1
    rows = load_dataset(args.data)
    if len(rows) < 2:
        print("Too few rows (<2) to evaluate. Add labelled rows to dataset.jsonl.")
        return 1

    scored = []
    for r in rows:
        lab = r.get("label", "none")
        if lab not in LABEL_GAIN:
            print(f"  Row {r.get('id')} has an invalid label: {lab} "
                  "(expected strong/medium/weak/none)")
            lab = "none"
        scored.append((r.get("id", "?"), score_row(r, args.years), lab, r.get("jd_title", "")))

    print(f"\n=== Details (my_years={args.years}, N={len(scored)}) ===")
    print(f"  {'id':<8}{'score':>6}  {'label':<8}jd_title")
    for sid, sc, lab, title in sorted(scored, key=lambda x: x[1], reverse=True):
        print(f"  {sid:<8}{sc:>6}  {lab:<8}{title[:44]}")

    scores = [s[1] for s in scored]
    gains = [LABEL_GAIN[s[2]] for s in scored]
    by_score = sorted(scored, key=lambda x: x[1], reverse=True)
    ranked_labels = [s[2] for s in by_score]
    ranked_gains = [LABEL_GAIN[s[2]] for s in by_score]

    k = min(args.k, len(scored))
    print("\n=== Metrics ===")
    print(f"  Spearman rank corr : {spearman(scores, gains):+.3f}   (closer to +1 is better)")
    print(f"  Precision@{k}       : {precision_at_k(ranked_labels, k):.3f}   "
          f"(share of strong/medium in the top {k})")
    print(f"  NDCG@{k}            : {ndcg_at_k(ranked_gains, k):.3f}   (closer to 1 is better)")
    n_rel = sum(1 for g in gains if g >= 2)
    print(f"\n  Note: N={len(scored)} labelled rows ({n_rel} relevant). With this few "
          "labels the metrics are a smoke test, not a measurement.")
    print("        Extend to 30-50 real resume + JD + label rows before tuning weights on them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
