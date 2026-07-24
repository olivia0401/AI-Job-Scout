"""Pure job matching / scoring logic — no Flask, no global state.

Region & seniority classification, the AI-role title filter, the skill
vocabulary, and the ATS-style fit score. Extracted from app.py so this
logic can be read and unit-tested on its own (see tests/test_matching.py).
"""
import os
import re


TITLE_ONLY_KEYWORDS = {"recommendation", "recommendations", "personalization"}

# 命中即标 LLM 的关键词（用户重点关注）
LLM_KEYWORDS = [
    "llm", "large language model", "genai", "gen ai", "generative ai",
    "foundation model", "prompt engineer", "agentic", "ai agent", "rag",
    "conversational ai", "chatbot", "nlp",
]

UK_RE = re.compile(r"\b(united kingdom|uk|london|manchester|birmingham|cambridge|oxford|"
                   r"edinburgh|glasgow|bristol|leeds|belfast|cardiff|reading|milton keynes|"
                   r"newcastle|sheffield|liverpool|nottingham|southampton|brighton|"
                   r"england|scotland|wales)\b")

# 欧洲：按对 AI 人才需求排序靠前的国家优先匹配
EU_PLACES = [
    ("Germany", r"germany|berlin|munich|münchen|frankfurt|hamburg|cologne|stuttgart"),
    ("Netherlands", r"netherlands|amsterdam|rotterdam|eindhoven|utrecht|the hague"),
    ("Ireland", r"ireland|dublin|cork"),
    ("France", r"france|paris|lyon|grenoble|toulouse|nice"),
    ("Switzerland", r"switzerland|zurich|zürich|geneva|lausanne|basel"),
    ("Sweden", r"sweden|stockholm|gothenburg"),
    ("Denmark", r"denmark|copenhagen"),
    ("Spain", r"spain|madrid|barcelona|valencia"),
    ("Portugal", r"portugal|lisbon|porto"),
    ("Poland", r"poland|warsaw|krakow|kraków|wroclaw|gdansk"),
    ("Austria", r"austria|vienna"),
    ("Belgium", r"belgium|brussels|antwerp|ghent"),
    ("Finland", r"finland|helsinki"),
    ("Norway", r"norway|oslo"),
    ("Italy", r"italy|milan|rome|turin"),
    ("Czechia", r"czech|prague"),
    ("Luxembourg", r"luxembourg"),
    ("Estonia", r"estonia|tallinn"),
    ("Lithuania", r"lithuania|vilnius"),
    ("Greece", r"greece|athens"),
    ("Hungary", r"hungary|budapest"),
    ("Romania", r"romania|bucharest|cluj"),
    ("Europe", r"europe|emea|european union"),
]
EU_RES = [(label, re.compile(r"\b(" + pat + r")\b")) for label, pat in EU_PLACES]

CHINA_RE = re.compile(
    r"\b(china|shanghai|beijing|shenzhen|hangzhou|guangzhou|nanjing|chengdu|wuhan|"
    r"suzhou|xi'an|xian|tianjin|hong kong|hongkong|macau|taipei|taiwan)\b")

OTHER_RE = re.compile(
    r"\b(usa|us|u\.s\.|united states|canada|toronto|vancouver|montreal|india|bangalore|"
    r"bengaluru|hyderabad|mumbai|delhi|pune|"
    r"japan|tokyo|korea|seoul|singapore|australia|sydney|melbourne|new zealand|brazil|"
    r"sao paulo|mexico|argentina|chile|colombia|qatar|doha|dubai|uae|abu dhabi|saudi|"
    r"israel|tel aviv|turkey|istanbul|egypt|cairo|nigeria|lagos|kenya|nairobi|"
    r"south africa|cape town|johannesburg|pakistan|bangladesh|vietnam|philippines|"
    r"indonesia|thailand|malaysia|new york|san francisco|seattle|austin|boston|chicago|"
    r"denver|los angeles|washington|atlanta|miami|philadelphia|dallas|houston|phoenix)\b")


def classify_region(location):
    """返回 (region, label)：uk / europe / china / remote / other / unknown"""
    loc = (location or "").lower()
    if not loc:
        return ("unknown", "")  # 没写地点 ≠ 英国：单列，前端可选择性显示
    if UK_RE.search(loc):
        return ("uk", "UK")
    for label, rx in EU_RES:
        if rx.search(loc):
            return ("europe", label)
    if CHINA_RE.search(loc):
        return ("china", "China")
    if OTHER_RE.search(loc):
        return ("other", "")
    if "remote" in loc:
        return ("remote", "Remote")
    return ("unknown", "")


LEVEL_LABELS = {
    "grad": "实习/毕业生", "junior": "初级", "mid": "中级",
    "senior": "高级", "staff": "Staff/Lead", "mgmt": "管理层",
}
_LEVEL_RES = [
    ("grad", re.compile(r"\b(intern|internship|graduate|grad|early careers?|entry[- ]?level|apprentice|working student|placement)\b")),
    ("mgmt", re.compile(r"\b(head|director|vp|vice president|chief|manager|management)\b")),
    ("staff", re.compile(r"\b(staff|principal|distinguished|fellow|lead)\b")),
    ("senior", re.compile(r"\b(senior|sr)\b")),
    ("junior", re.compile(r"\b(junior|jr|associate)\b")),
]


def classify_level(title):
    t = (title or "").lower()
    for level, rx in _LEVEL_RES:
        if rx.search(t):
            return level
    return "mid"


LONG_RUNNING_DAYS = 30   # 岗位在线 ≥30 天算“长期在招”
NEW_DAYS = 3             # 首次发现 ≤3 天算“新岗位”


def kw_match(text, kws):
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in kws)


def kw_hit_count(text, kws):
    """关键词命中总次数（同一个词出现多次都计入）。"""
    return sum(len(re.findall(r"\b" + re.escape(k) + r"\b", text)) for k in kws)


# 广撒网标题：工程/数据/研究类岗位，标题没写 AI 也值得读 JD 正文二次确认
BROAD_TITLE_RE = re.compile(
    r"\b(engineer|developer|scientist|programmer|architect|researcher)\b")

# 标题黑名单：明显不是 AI 研发方向的角色，不给走 JD 正文宽通道——
# 这些岗位挂在"AI 公司"名下时，JD 里的公司简介总会提到 AI，全是误命中
EXCLUDE_TITLE_RE = re.compile(
    r"\b(sales|pre-?sales|account (?:manager|executive)|business development|"
    r"marketing|recruit(?:er|ing|ment)|talent acquisition|customer success|"
    r"support|solutions? (?:architect|engineer|consultant)|"
    r"qa|sdet|quality assurance|test(?:er|ing)?|"
    r"android|ios|mobile|front[- ]?end|"
    r"network|electrical|mechanical|civil|hardware|firmware|embedded|bmc|"
    r"devops|site reliability|sre|security|help ?desk|"
    r"field operations?|control engineer|validation engineer)\b")


def match_job(title, desc, keywords):
    """判断一个岗位是否算 AI 岗，返回命中来源：
      'title' —— 标题直接命中 AI 关键词；
      'jd'    —— 标题是工程/数据/研究类（且不在黑名单里）、JD 正文命中
                 AI 关键词 ≥2 次（拓宽召回；要求 ≥2 次是为了滤掉
                 公司简介里"we are an AI-powered..."这种一嘴带过的套话）；
      None    —— 都没命中。
    JD 正文抓不到时（desc 为空）只走标题，天然保守。
    keywords 为空 = 用户要"看全部"（不做行业过滤），收录每个岗位（返回 'all'）。"""
    if not keywords:
        return "all"
    t = (title or "").lower()
    if kw_match(t, keywords):
        return "title"
    if desc and BROAD_TITLE_RE.search(t) and not EXCLUDE_TITLE_RE.search(t):
        body_kws = [k for k in keywords if k not in TITLE_ONLY_KEYWORDS]
        if kw_hit_count(desc.lower(), body_kws) >= 2:
            return "jd"
    return None


# 目标岗位画像：区分"这个岗位方向是否对口"，与"简历技能是否重合"解耦。
# 关键：技能重合高 ≠ 岗位对口——IT Support 的 JD 也会写 python/docker/aws。
DEFAULT_TARGET_TITLES = [
    "machine learning engineer", "ml engineer", "mle",
    "ai engineer", "artificial intelligence engineer",
    "llm engineer", "nlp engineer", "genai engineer", "generative ai engineer",
    "deep learning engineer", "computer vision engineer",
    "machine learning scientist", "ai scientist",
]
DEFAULT_ACCEPTABLE_TITLES = [
    "applied scientist", "research engineer", "research scientist",
    "data scientist", "data science", "applied ai",
    "machine learning researcher", "ml researcher",
    "mlops engineer", "ai platform engineer",
]


def _title_hit(title_l, phrases):
    return any(re.search(r"\b" + re.escape(p) + r"\b", title_l) for p in phrases)


# 词元启发式：AI/ML 方向词 + 角色词。用于兜住写法千变万化的真实岗位标题
# （如 "Software Engineer, Machine Learning" / "ML Platform Engineer" /
#  "NLP Research Engineer" / "Research Scientist, Foundation Models"），
# 避免"精确短语命中"把真实相关岗位误判成 off_target。
_AI_TOKEN_RE = re.compile(
    r"\b(machine learning|ml|deep learning|artificial intelligence|ai|"
    r"llm|large language model|nlp|natural language|computer vision|"
    r"genai|generative ai|foundation model|reinforcement learning|"
    r"recommendations?|recommender|personali[sz]ations?|search ranking|"
    r"mlops|applied ai|data science)\b")
_ENG_ROLE_RE = re.compile(r"\b(engineer|developer|programmer)\b")
_SCI_ROLE_RE = re.compile(r"\b(scientist|researcher|research)\b")


def title_match(title, targets=None, acceptables=None, custom=False, keywords=None):
    """岗位方向：target=正好想要 / acceptable=能接受 / off_target=方向不对。
    off_target 的岗位无论技能分多高都不该被强推（例如 IT Support、Sales）。

    两种画像：
    · custom=True —— 用户已经把工具切到别的行业（改了关键词或填了目标岗位）。
      方向**完全**由用户自己的目标/可接受/搜索词决定，绝不套用 AI 专用的
      标题黑名单和 AI 词元启发式——否则金融/建筑/机械/市场等岗位会被永久
      判成 off_target 沉底，工具就退化成"只出得来 AI 岗"。
    · custom=False（内置 AI 画像）—— 保持原逻辑：① 黑名单角色直接 off_target；
      ② 目标/可接受短语；③ AI 方向词+角色词的词元启发式兜底。"""
    t = (title or "").lower()
    if custom:
        if targets and _title_hit(t, targets):
            return "target"
        if acceptables and _title_hit(t, acceptables):
            return "acceptable"
        if keywords and _title_hit(t, keywords):
            # 标题命中用户的搜索词 = 至少对口；没单独列 target 时就当 target
            return "acceptable" if targets else "target"
        if not (targets or acceptables or keywords):
            return "target"     # 关键词/目标全空 = 看全部，任何岗位都不沉底
        return "off_target"
    tg = targets if targets is not None else DEFAULT_TARGET_TITLES
    ac = acceptables if acceptables is not None else DEFAULT_ACCEPTABLE_TITLES
    if EXCLUDE_TITLE_RE.search(t):          # ① 黑名单：即便带 engineer/AI 也算方向不对
        return "off_target"
    if _title_hit(t, tg):                   # ② 用户/默认目标短语
        return "target"
    if _title_hit(t, ac):
        return "acceptable"
    has_ai = bool(_AI_TOKEN_RE.search(t))   # ③ 词元启发式
    if has_ai and _ENG_ROLE_RE.search(t):
        return "target"
    if has_ai and _SCI_ROLE_RE.search(t):
        return "acceptable"
    return "off_target"


SKILL_VOCAB = [
    # 语言
    "python", "java", "c++", "c#", "golang", "rust", "scala", "sql", "r",
    "javascript", "typescript", "matlab", "bash",
    # 机器学习
    "machine learning", "deep learning", "pytorch", "tensorflow", "keras",
    "scikit-learn", "sklearn", "xgboost", "lightgbm", "computer vision",
    "nlp", "natural language processing", "reinforcement learning",
    "recommendation", "recommender", "time series", "anomaly detection",
    "statistics", "statistical", "a/b testing", "causal inference",
    "feature engineering", "classification", "regression", "clustering",
    "neural network", "cnn", "rnn", "lstm", "gan",
    # LLM / GenAI
    "llm", "large language model", "transformer", "transformers",
    "hugging face", "huggingface", "fine-tuning", "finetuning", "lora",
    "rlhf", "prompt engineering", "rag", "retrieval augmented generation",
    "vector database", "embedding", "embeddings", "faiss", "pinecone",
    "milvus", "langchain", "llamaindex", "llama", "agent", "agentic",
    "openai", "anthropic", "claude", "gpt", "gemini", "mistral",
    "whisper", "stable diffusion", "diffusion", "multimodal",
    "speech recognition", "ocr", "generative ai", "genai", "chatbot",
    "semantic search", "knowledge graph",
    "llmops", "guardrails", "guardrail", "azure openai", "bedrock",
    "aws bedrock", "model evaluation", "llm evaluation", "model evals",
    "prompt optimization", "retrieval", "vector search", "rerank",
    "reranking", "peft", "quantization", "distillation", "vllm", "triton",
    "langgraph", "autogen", "dspy", "semantic kernel", "context window",
    "production ml", "retrieval systems",
    # 数据
    "pandas", "numpy", "spark", "pyspark", "hadoop", "kafka", "airflow",
    "dbt", "snowflake", "databricks", "etl", "data pipeline",
    "data warehouse", "bigquery", "redshift", "tableau", "power bi",
    "data analysis", "data visualization",
    # 工程 / 基础设施
    "aws", "gcp", "google cloud", "azure", "docker", "kubernetes", "k8s",
    "terraform", "ci/cd", "mlops", "mlflow", "kubeflow", "sagemaker",
    "vertex ai", "model deployment", "model serving", "inference",
    "onnx", "tensorrt", "gpu", "cuda", "distributed training", "ray",
    "monitoring", "observability", "grafana", "linux", "git", "rest api", "api",
    "bentoml", "weights & biases", "wandb", "dvc", "feature store",
    "microservices", "fastapi", "flask", "django", "react", "node.js",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "system design", "scalability", "testing", "unit test",
    # 领域 / 软技能
    "agile", "scrum", "stakeholder", "cross-functional", "mentoring",
    "leadership", "research", "publication", "phd", "kaggle",
    "open source", "fintech", "healthcare", "fraud detection", "risk",
    "personalization", "search ranking", "ads", "etl pipelines",
]
_VOCAB_RES = [(kw, re.compile(r"(?<![\w+#])" + re.escape(kw) + r"(?![\w+#])"))
              for kw in SKILL_VOCAB]

# 同义词归并：命中任一形式只记规范名
_CANON = {"sklearn": "scikit-learn", "huggingface": "hugging face",
          "finetuning": "fine-tuning", "k8s": "kubernetes",
          "natural language processing": "nlp", "google cloud": "gcp",
          "large language model": "llm", "golang": "go",
          "retrieval augmented generation": "rag",
          "generative ai": "genai", "embeddings": "embedding",
          "transformers": "transformer", "statistical": "statistics",
          "aws bedrock": "bedrock", "reranking": "rerank",
          "wandb": "weights & biases", "llm evaluation": "model evaluation",
          "model evals": "model evaluation", "guardrail": "guardrails",
          "retrieval systems": "retrieval"}


def extract_skills(text):
    t = (text or "").lower()
    found = set()
    for kw, rx in _VOCAB_RES:
        if rx.search(t):
            found.add(_CANON.get(kw, kw))
    return found


# Every skill name extract_skills can emit: raw vocab plus canonical forms.
# Used to tell "known" skills from free-form terms mined out of job descriptions.
KNOWN_SKILLS = set(SKILL_VOCAB) | set(_CANON.values())


NICE_SPLIT_RE = re.compile(
    r"nice to have|nice-to-have|bonus point|desirable|preferred qualification|"
    r"is a plus|would be a plus|even better if|great to have|good to have|"
    r"it would be great|we'd love|additionally")
YEARS_RES = [
    re.compile(r"(\d{1,2})\s*\+\s*years?"),
    re.compile(r"at least (\d{1,2}) years?"),
    re.compile(r"minimum (?:of )?(\d{1,2}) years?"),
    re.compile(r"(\d{1,2}) or more years?"),
]
CLEARANCE_RE = re.compile(
    r"security clearance|sc clear|dv clear|active clearance|"
    r"uk nationals? only|british citizen|must be a uk national|eligible for (?:sc|dv)\b")
NO_SPONSOR_RE = re.compile(
    r"(?:cannot|unable to|not able to|do not|don'?t|no)\s+(?:currently\s+)?"
    r"(?:offer|provide|support)?\s*(?:visa\s+)?sponsorship"
    r"|not (?:currently )?(?:able to )?sponsor|without (?:visa )?sponsorship")
YES_SPONSOR_RE = re.compile(
    r"(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided|supported)"
    r"|(?:we|company)\s+(?:can|do|will)\s+sponsor|able to sponsor|sponsorship for this role")


# 岗位级别 → 典型经验年限中点（用于职级匹配打分）
LEVEL_YEARS = {"grad": 0.0, "junior": 1.5, "mid": 3.5,
               "senior": 6.5, "staff": 9.0, "mgmt": 10.0}
# 领域标记：命中即代表方向对口，单独占一档权重
DOMAIN_SKILLS = {
    "nlp", "computer vision", "llm", "rag", "recommendation", "recommender",
    "fraud detection", "fintech", "healthcare", "search ranking", "ads",
    "time series", "speech recognition", "multimodal", "reinforcement learning",
    "anomaly detection", "knowledge graph", "personalization", "risk",
    "genai", "retrieval",
}

# ATS 式综合评分权重（可测的分项才计权重，最后按实际权重和归一化）：
#   必备技能 55% · 加分技能 20% · 职级 10% · 领域 10% · JD抓取置信度 5%
W_REQUIRED, W_PREFERRED, W_LEVEL, W_DOMAIN, W_CONF = 0.55, 0.20, 0.10, 0.10, 0.05


def analyze_job(title, desc, resume_kws, my_years, level=None):
    """ATS 式综合评分：技能覆盖(必备/加分) + 职级 + 领域 + JD置信度，再叠加淘汰项。

    每个分项都归一化到 0..1，只有"可测"的分项才计入权重，最后按参与权重之和
    归一化——这样缺 nice-to-have 段落或抓不到 JD 时不会被凭空扣分。"""
    dl = (desc or "").lower()
    full = (title or "").lower() + ". " + dl
    m = NICE_SPLIT_RE.search(dl)
    core_txt = dl[:m.start()] if m else dl
    nice_txt = dl[m.start():] if m else ""
    core = extract_skills((title or "").lower()) | extract_skills(core_txt)
    nice = extract_skills(nice_txt) - core
    hit_c, miss_c = core & resume_kws, core - resume_kws
    hit_n, miss_n = nice & resume_kws, nice - resume_kws

    comps = []  # (weight, subscore 0..1)
    if core:
        comps.append((W_REQUIRED, len(hit_c) / len(core)))
    if nice:
        comps.append((W_PREFERRED, len(hit_n) / len(nice)))
    if level in LEVEL_YEARS and my_years is not None:
        gap = abs(my_years - LEVEL_YEARS[level])
        comps.append((W_LEVEL, max(0.0, 1.0 - gap / 5.0)))
    job_domains = (core | nice) & DOMAIN_SKILLS
    if job_domains:
        comps.append((W_DOMAIN, len(job_domains & resume_kws) / len(job_domains)))
    # JD 抓取置信度：抓到完整正文 1.0，正文很短 0.6，只有标题 0.3
    conf = 1.0 if len(dl) >= 400 else (0.6 if dl else 0.3)
    comps.append((W_CONF, conf))

    wsum = sum(w for w, _ in comps)
    score = round(100 * sum(w * s for w, s in comps) / wsum) if wsum else 0

    flags = []
    yrs = 0
    for rx in YEARS_RES:
        for g in rx.findall(full):
            try:
                yrs = max(yrs, int(g))
            except ValueError:
                pass
    if 0 < my_years < yrs <= 15:
        flags.append({"t": f"要求 {yrs}+ 年经验", "lv": "warn"})
    if CLEARANCE_RE.search(full):
        flags.append({"t": "需安全许可/国籍要求", "lv": "warn"})
    if NO_SPONSOR_RE.search(full):
        flags.append({"t": "JD 声明不担保签证", "lv": "warn"})
        score = max(score - 40, 0)  # 真实世界里这基本等于淘汰
    elif YES_SPONSOR_RE.search(full):
        flags.append({"t": "明确提供签证担保", "lv": "good"})
    if not dl:
        # 没抓到 JD 正文：只凭标题算的分虚高（"Junior ML Engineer" 光标题就能拿 90+），
        # 封顶并明示低置信度，防止挤掉那些用完整 JD 验证过的真高分岗位
        score = min(score, 65)
        flags.append({"t": "未抓到 JD，仅按标题估分", "lv": "warn"})
    return {
        "score": score, "hit": sorted(hit_c | hit_n),
        "must_miss": sorted(miss_c)[:12], "nice_miss": sorted(miss_n)[:10],
        "flags": flags, "n": len(core) + len(nice),
        "req_years": yrs,   # JD 抽到的最低要求年限（0=未注明），供前端“经验要求”筛选
        # 分数可信度：high=完整JD / mid=JD较短 / low=只有标题——分数一样时先信 high
        "conf": ("high" if len(dl) >= 400 else "mid" if dl else "low"),
    }


def visa_certainty(ms, on_register):
    """签证确定性分层（前端一级筛选）：
      yes       —— JD 明确写提供担保
      no        —— JD 明确写不担保
      register  —— 公司在官方 sponsor 名单里，但 JD 未说明（大多数岗位在这层）
      uncertain —— 聚合平台岗位且公司名没匹配上名单，担保与否完全未知"""
    txts = [f.get("t", "") for f in ((ms or {}).get("flags") or [])]
    if any("不担保" in t for t in txts):
        return "no"
    if any("提供签证担保" in t for t in txts):
        return "yes"
    return "register" if on_register else "uncertain"


def job_tier(score, ms, visa, tmatch="target"):
    """推荐分层：strong 强推荐 / maybe 可以看看 / weak 匹配弱 /
    lowconf 低置信（没抓到JD或没算分） / risk 签证或安全许可风险。

    进 strong 必须三者同时成立：岗位方向对口(target/acceptable) + 分数≥60 +
    无签证/许可风险。tmatch=off_target 的岗位（IT Support、Sales 等）即使技能分
    很高也只归 weak——避免"技能重合"被误当成"岗位对口"。"""
    txts = [f.get("t", "") for f in ((ms or {}).get("flags") or [])]
    if visa == "no" or any("安全许可" in t for t in txts):
        return "risk"
    if tmatch == "off_target":
        return "weak"     # 方向不对：直接沉底，绝不进今日推荐（在 lowconf 判断之前）
    if score is None or any("仅按标题估分" in t for t in txts):
        return "lowconf"
    if score >= 60:
        return "strong"
    if score >= 35:
        return "maybe"
    return "weak"


# 综合推荐分权重（方向对口是精准度命门，权重高于 roadmap 原案的 0.10）
_CONF_W = {"high": 1.0, "mid": 0.6, "low": 0.3}
_VISA_W = {"yes": 1.0, "register": 0.6, "uncertain": 0.3, "no": 0.0}
_TMATCH_W = {"target": 1.0, "acceptable": 0.7, "off_target": 0.0}
TIER_ORDER = {"strong": 0, "maybe": 1, "lowconf": 2, "weak": 3, "risk": 4}


def rank_score(score, conf, visa, tmatch, days):
    """综合推荐分 0..100：技能分×0.40 + 方向×0.20 + 签证×0.20 + 置信×0.12 + 新鲜×0.08。
    tier 是粗分桶（strong/maybe/…），rank_score 用于桶内细排和"今日推荐 Top"。"""
    s = max(0, min(score or 0, 100)) / 100.0
    if days is None:
        fresh = 0.3
    elif days <= NEW_DAYS:
        fresh = 1.0
    elif days <= LONG_RUNNING_DAYS:
        fresh = 0.5
    else:
        fresh = 0.2
    val = (0.40 * s
           + 0.20 * _TMATCH_W.get(tmatch, 0.0)
           + 0.20 * _VISA_W.get(visa, 0.3)
           + 0.12 * _CONF_W.get(conf, 0.3)
           + 0.08 * fresh)
    return round(100 * val)
