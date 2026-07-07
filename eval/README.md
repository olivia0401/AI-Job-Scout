# 匹配评估集

用人工标注样本验证「排序准确性」——只有配上标注集，评分器才谈得上准确率。

## 跑一次

```
pip install -r requirements.txt          # 只需要标准库 + app.py 的依赖
python eval/run_eval.py                   # 默认 my_years=2, k=5
python eval/run_eval.py --years 4 --k 3   # 换候选人年限 / top-k
python eval/run_eval.py --data eval/my_labeled.jsonl   # 换成你自己的标注集
```

输出三项指标：

| 指标 | 含义 | 好的方向 |
|---|---|---|
| **Spearman 排名相关** | 分数排序 vs 人工排序的一致性 | 越接近 +1 越好 |
| **Precision@k** | 分数最高的 k 个里，有多少真的是 strong/medium | 越接近 1 越好 |
| **NDCG@k** | 综合排名质量（标签当增益，带位置折扣） | 越接近 1 越好 |

## 标注样本格式

`dataset.jsonl`，每行一个 JSON。以 `#` 开头的行会被忽略。

```json
{"id": "s1",
 "resume_skills": ["python", "pytorch", "llm"],
 "jd_title": "Senior ML Engineer",
 "jd_text": "……真实 JD 正文……",
 "label": "strong"}
```

- `resume_skills`：技能词列表（会走同义词归并）。**或**用 `resume_text` 放整段简历文本，
  由 `extract_skills` 自动抽取——想同时评估「技能抽取」质量就用 `resume_text`。
- `label`：人工判断的匹配档位。
  - `strong` = 我很符合、值得优先投
  - `medium` = 部分符合、可以投
  - `weak` = 关系不大
  - `none` = 基本不相关
- 序数增益：strong=3, medium=2, weak=1, none=0；`relevant`（Precision 用）= strong 或 medium。

## 怎么建一个有用的评估集

1. 从工具跑出来的真实岗位里挑 30–50 个，覆盖 4 个档位（尽量各档都有 ~10 条）。
2. 用**同一份简历**（skills 固定），这样比的是评分器对不同 JD 的区分力。
3. 自己（或懂行的人）打 `strong/medium/weak/none` 标签——凭对岗位的真实判断，别看分数。
4. 跑 `run_eval.py`。若 Spearman 偏低或 Precision@k 差，说明权重/词表要调：
   - 相关岗位分低 → 多半是词表漏词或 required/preferred 段没切对；
   - 不相关岗位分高 → 领域权重可以调高，或补淘汰规则。
5. 改完 `app.py` 的权重（`W_REQUIRED` 等）后重跑，看指标是否变好——这就是回归防线。

> 种子集 `dataset.jsonl` 只有 8 条，仅用于冒烟验证脚本能跑通，不代表真实准确率。
