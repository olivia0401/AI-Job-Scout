# Match evaluation set

Checks the scorer's **ranking accuracy** against hand-labelled samples. A scorer only has an "accuracy" once it is compared with labelled data.

## Run it

```
python eval/run_eval.py                                # defaults: my_years=2, k=5
python eval/run_eval.py --years 4 --k 3                # different candidate years / top-k
python eval/run_eval.py --data eval/my_labeled.jsonl   # your own labelled set
```

It is fully offline: standard library plus `matching.py`, no API key, no network. CI runs it on every push.

It prints three metrics:

| Metric | Meaning | Better when |
|---|---|---|
| **Spearman rank correlation** | Agreement between the score order and the human order | Closer to +1 |
| **Precision@k** | Of the k highest-scored jobs, how many are really strong/medium | Closer to 1 |
| **NDCG@k** | Overall ranking quality (labels as gains, with a position discount) | Closer to 1 |

## Row format

`dataset.jsonl`, one JSON object per line. Lines starting with `#` are ignored.

```json
{"id": "s1",
 "resume_skills": ["python", "pytorch", "llm"],
 "jd_title": "Senior ML Engineer",
 "jd_text": "...the real job description text...",
 "label": "strong"}
```

- `resume_skills`: a list of skill terms (synonyms are merged). **Or** put the whole resume in `resume_text` and let `extract_skills` pull the skills out. Use `resume_text` if you also want to evaluate skill extraction.
- `label`: your judgement of the match.
  - `strong` = I fit well, apply first
  - `medium` = partial fit, worth applying
  - `weak` = loosely related
  - `none` = basically irrelevant
- Ordinal gains: strong=3, medium=2, weak=1, none=0. "Relevant" (for Precision) = strong or medium.

## Building a useful evaluation set

1. Pick 30–50 real jobs the tool found, covering all 4 labels (ideally ~10 of each).
2. Use **the same resume** for every row (fixed skills), so you are measuring how well the scorer separates different JDs.
3. Label them `strong/medium/weak/none` yourself (or with someone who knows the field), from your real judgement of the job — don't look at the score.
4. Run `run_eval.py`. If Spearman is low or Precision@k is poor, tune the weights or vocabulary:
   - relevant jobs scoring low → usually missing vocabulary, or the required/preferred split is wrong;
   - irrelevant jobs scoring high → raise the domain weight or add exclusion rules.
5. After changing the weights in `matching.py` (`W_REQUIRED` etc.), rerun and check the metrics improved. That is your regression guard.

> The seed `dataset.jsonl` has only 8 rows. It is a smoke test that the script runs, not a measure of real accuracy.
