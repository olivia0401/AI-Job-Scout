# -*- coding: utf-8 -*-
"""简历-JD 匹配评估：用人工标注样本验证「排序准确性」。

评分器只有配上标注集才谈得上「准确率」。本脚本读取 eval/dataset.jsonl，
对每条样本跑 app.analyze_job，得到 0–100 分，再和人工标签比对，输出：

  * Spearman 排名相关   —— 分数排序与人工排序的一致性（-1..1，越接近 1 越好）
  * Precision@k          —— 分数最高的 k 个里，有多少真的是 strong/medium
  * NDCG@k               —— 排名质量（把标签当增益，越接近 1 越好）

用法:
    python eval/run_eval.py                 # 默认 my_years=2, k=5
    python eval/run_eval.py --years 4 --k 3
    python eval/run_eval.py --data eval/my_labeled.jsonl

样本格式（每行一个 JSON）:
    {"id": "s1",
     "resume_skills": ["python", "pytorch", "llm"],   // 或用 resume_text
     "jd_title": "Senior ML Engineer",
     "jd_text": "……JD 正文……",
     "label": "strong"}                                 // strong|medium|weak|none

标签 → 序数增益: strong=3, medium=2, weak=1, none=0。
relevant（用于 Precision@k）定义为 label ∈ {strong, medium}。
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

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
                print(f"  跳过第 {ln} 行（JSON 解析失败）: {e}")
    return rows


def score_row(row, my_years):
    if row.get("resume_skills") is not None:
        kws = set(app._CANON.get(k, k) for k in row["resume_skills"])
    else:
        kws = app.extract_skills(row.get("resume_text", ""))
    title = row.get("jd_title", "")
    level = app.classify_level(title)
    res = app.analyze_job(title, row.get("jd_text", ""), kws, my_years, level)
    return res["score"]


def _rank(values):
    """返回平均排名（并列取均值），用于 Spearman。"""
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
    ap.add_argument("--years", type=int, default=2, help="候选人工作年限（职级匹配用）")
    ap.add_argument("--k", type=int, default=5, help="Precision@k / NDCG@k 的 k")
    args = ap.parse_args()

    if not os.path.exists(args.data):
        print(f"找不到样本文件: {args.data}")
        return 1
    rows = load_dataset(args.data)
    if len(rows) < 2:
        print("样本太少（<2 条），无法评估。请在 dataset.jsonl 里补充标注样本。")
        return 1

    scored = []
    for r in rows:
        lab = r.get("label", "none")
        if lab not in LABEL_GAIN:
            print(f"  样本 {r.get('id')} 标签非法: {lab}（应为 strong/medium/weak/none）")
            lab = "none"
        scored.append((r.get("id", "?"), score_row(r, args.years), lab, r.get("jd_title", "")))

    # 明细
    print(f"\n=== 明细（my_years={args.years}, N={len(scored)}）===")
    print(f"  {'id':<8}{'score':>6}  {'label':<8}jd_title")
    for sid, sc, lab, title in sorted(scored, key=lambda x: x[1], reverse=True):
        print(f"  {sid:<8}{sc:>6}  {lab:<8}{title[:44]}")

    scores = [s[1] for s in scored]
    gains = [LABEL_GAIN[s[2]] for s in scored]
    by_score = sorted(scored, key=lambda x: x[1], reverse=True)
    ranked_labels = [s[2] for s in by_score]
    ranked_gains = [LABEL_GAIN[s[2]] for s in by_score]

    k = min(args.k, len(scored))
    print(f"\n=== 指标 ===")
    print(f"  Spearman 排名相关 : {spearman(scores, gains):+.3f}   （越接近 +1 越好）")
    print(f"  Precision@{k}       : {precision_at_k(ranked_labels, k):.3f}   （top{k} 里 strong/medium 占比）")
    print(f"  NDCG@{k}            : {ndcg_at_k(ranked_gains, k):.3f}   （排名质量，越接近 1 越好）")
    n_rel = sum(1 for g in gains if g >= 2)
    print(f"\n  提示: 种子集只有 {len(scored)} 条、{n_rel} 条相关，指标仅作冒烟。")
    print("        请补到 30–50 条真实「简历+JD+标签」再据此调权重。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
