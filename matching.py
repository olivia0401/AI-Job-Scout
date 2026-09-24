"""Pure job matching / scoring logic — no Flask, no global state.

Region & seniority classification, the AI-role title filter, the skill
vocabulary, and the ATS-style fit score. Extracted from app.py so this
logic can be read and unit-tested on its own (see tests/test_matching.py).
"""
import os
import re


TITLE_ONLY_KEYWORDS = {"recommendation", "recommendations", "personalization"}

# Keywords that tag a job as LLM on any hit (the user's main focus)
LLM_KEYWORDS = [
    "llm", "large language model", "genai", "gen ai", "generative ai",
    "foundation model", "prompt engineer", "agentic", "ai agent", "rag",
    "conversational ai", "chatbot", "nlp",
]

UK_RE = re.compile(r"\b(united kingdom|uk|london|manchester|birmingham|cambridge|oxford|"
                   r"edinburgh|glasgow|bristol|leeds|belfast|cardiff|reading|milton keynes|"
                   r"newcastle|sheffield|liverpool|nottingham|southampton|brighton|"
                   r"england|scotland|wales)\b")

# Europe: countries with the highest AI talent demand are matched first
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
    """Return (region, label): uk / europe / china / remote / other / unknown"""
    loc = (location or "").lower()
    if not loc:
        return ("unknown", "")  # no location ≠ UK: kept separate so the frontend can choose to show it
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
    "grad": "Intern/Graduate", "junior": "Junior", "mid": "Mid",
    "senior": "Senior", "staff": "Staff/Lead", "mgmt": "Management",
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


LONG_RUNNING_DAYS = 30   # listed ≥30 days counts as "long-running"
NEW_DAYS = 3             # first seen ≤3 days ago counts as "new"


def kw_match(text, kws):
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in kws)


def kw_hit_count(text, kws):
    """Total keyword hits (repeat occurrences of a word all count)."""
    return sum(len(re.findall(r"\b" + re.escape(k) + r"\b", text)) for k in kws)


# Wide-net titles: engineering/data/research roles are worth a second check of the JD body even without AI in the title
BROAD_TITLE_RE = re.compile(
    r"\b(engineer|developer|scientist|programmer|architect|researcher)\b")

# Title blacklist: roles clearly outside AI R&D don't get the wide JD-body path —
# when listed under an "AI company", the JD's company blurb always mentions AI, so every hit is false
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
    """Decide whether a job counts as an AI role; return the match source:
      'title' —— the title directly hits an AI keyword;
      'jd'    —— the title is engineering/data/research (and not blacklisted) and the JD body hits
                 AI keywords ≥2 times (widens recall; requiring ≥2 filters out
                 passing boilerplate like "we are an AI-powered..." in company blurbs);
      None    —— neither matched.
    When the JD body can't be fetched (desc empty) only the title is used, so it stays conservative.
    Empty keywords = the user wants "show all" (no industry filter): keep every job (return 'all')."""
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


# Target-role profile: judges "is this role the right direction", decoupled from "do resume skills overlap".
# Key point: high skill overlap ≠ right role — IT Support JDs also list python/docker/aws.
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


# Token heuristic: AI/ML domain word + role word. Catches real job titles phrased in endless ways
# (e.g. "Software Engineer, Machine Learning" / "ML Platform Engineer" /
#  "NLP Research Engineer" / "Research Scientist, Foundation Models"),
# so "exact-phrase matching" doesn't misjudge genuinely relevant roles as off_target.
_AI_TOKEN_RE = re.compile(
    r"\b(machine learning|ml|deep learning|artificial intelligence|ai|"
    r"llm|large language model|nlp|natural language|computer vision|"
    r"genai|generative ai|foundation model|reinforcement learning|"
    r"recommendations?|recommender|personali[sz]ations?|search ranking|"
    r"mlops|applied ai|data science)\b")
_ENG_ROLE_RE = re.compile(r"\b(engineer|developer|programmer)\b")
_SCI_ROLE_RE = re.compile(r"\b(scientist|researcher|research)\b")


def title_match(title, targets=None, acceptables=None, custom=False, keywords=None):
    """Role direction: target=exactly wanted / acceptable=would accept / off_target=wrong direction.
    off_target roles should never be pushed, however high the skill score (e.g. IT Support, Sales).

    Two profiles:
    · custom=True —— the user switched the tool to another industry (changed keywords or set target roles).
      Direction is decided **entirely** by the user's own target/acceptable/search terms, never by the AI-only
      title blacklist or AI token heuristic — otherwise finance/construction/mechanical/marketing roles would be
      permanently sunk as off_target, and the tool would degrade to "AI jobs only".
    · custom=False (built-in AI profile) —— original logic: ① blacklisted roles go straight to off_target;
      ② target/acceptable phrases; ③ AI-domain + role-word token heuristic as a fallback."""
    t = (title or "").lower()
    if custom:
        if targets and _title_hit(t, targets):
            return "target"
        if acceptables and _title_hit(t, acceptables):
            return "acceptable"
        if keywords and _title_hit(t, keywords):
            # title hits the user's search terms = at least relevant; counts as target if no targets are listed
            return "acceptable" if targets else "target"
        if not (targets or acceptables or keywords):
            return "target"     # no keywords/targets = show all, nothing sinks
        return "off_target"
    tg = targets if targets is not None else DEFAULT_TARGET_TITLES
    ac = acceptables if acceptables is not None else DEFAULT_ACCEPTABLE_TITLES
    if EXCLUDE_TITLE_RE.search(t):          # ① blacklist: wrong direction even with engineer/AI
        return "off_target"
    if _title_hit(t, tg):                   # ② user/default target phrases
        return "target"
    if _title_hit(t, ac):
        return "acceptable"
    has_ai = bool(_AI_TOKEN_RE.search(t))   # ③ token heuristic
    if has_ai and _ENG_ROLE_RE.search(t):
        return "target"
    if has_ai and _SCI_ROLE_RE.search(t):
        return "acceptable"
    return "off_target"


SKILL_VOCAB = [
    # Languages
    "python", "java", "c++", "c#", "golang", "rust", "scala", "sql", "r",
    "javascript", "typescript", "matlab", "bash",
    # Machine learning
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
    # Data
    "pandas", "numpy", "spark", "pyspark", "hadoop", "kafka", "airflow",
    "dbt", "snowflake", "databricks", "etl", "data pipeline",
    "data warehouse", "bigquery", "redshift", "tableau", "power bi",
    "data analysis", "data visualization",
    # Engineering / infrastructure
    "aws", "gcp", "google cloud", "azure", "docker", "kubernetes", "k8s",
    "terraform", "ci/cd", "mlops", "mlflow", "kubeflow", "sagemaker",
    "vertex ai", "model deployment", "model serving", "inference",
    "onnx", "tensorrt", "gpu", "cuda", "distributed training", "ray",
    "monitoring", "observability", "grafana", "linux", "git", "rest api", "api",
    "bentoml", "weights & biases", "wandb", "dvc", "feature store",
    "microservices", "fastapi", "flask", "django", "react", "node.js",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "system design", "scalability", "testing", "unit test",
    # Domains / soft skills
    "agile", "scrum", "stakeholder", "cross-functional", "mentoring",
    "leadership", "research", "publication", "phd", "kaggle",
    "open source", "fintech", "healthcare", "fraud detection", "risk",
    "personalization", "search ranking", "ads", "etl pipelines",
]
_VOCAB_RES = [(kw, re.compile(r"(?<![\w+#])" + re.escape(kw) + r"(?![\w+#])"))
              for kw in SKILL_VOCAB]

# Synonym merging: any matched form is recorded under its canonical name
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


# Job level → midpoint of typical years of experience (for level-fit scoring)
LEVEL_YEARS = {"grad": 0.0, "junior": 1.5, "mid": 3.5,
               "senior": 6.5, "staff": 9.0, "mgmt": 10.0}
# Domain markers: a hit means the domain fits; gets its own weight bucket
DOMAIN_SKILLS = {
    "nlp", "computer vision", "llm", "rag", "recommendation", "recommender",
    "fraud detection", "fintech", "healthcare", "search ranking", "ads",
    "time series", "speech recognition", "multimodal", "reinforcement learning",
    "anomaly detection", "knowledge graph", "personalization", "risk",
    "genai", "retrieval",
}

# ATS-style score weights (only measurable components count; normalised by the weights actually used):
#   required skills 55% · preferred skills 20% · level 10% · domain 10% · JD fetch confidence 5%
W_REQUIRED, W_PREFERRED, W_LEVEL, W_DOMAIN, W_CONF = 0.55, 0.20, 0.10, 0.10, 0.05


def analyze_job(title, desc, resume_kws, my_years, level=None):
    """ATS-style score: skill coverage (required/preferred) + level + domain + JD confidence, plus knockout factors.

    Each component is normalised to 0..1; only "measurable" components carry weight, and the total is
    normalised by the weights used — so a missing nice-to-have section or JD costs no points."""
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
    # JD fetch confidence: full body 1.0, short body 0.6, title only 0.3
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
        score = max(score - 40, 0)  # in practice this is effectively a rejection
    elif YES_SPONSOR_RE.search(full):
        flags.append({"t": "明确提供签证担保", "lv": "good"})
    if not dl:
        # No JD body: title-only scores are inflated ("Junior ML Engineer" alone can score 90+),
        # so cap and flag low confidence to avoid crowding out genuine high scorers verified by a full JD
        score = min(score, 65)
        flags.append({"t": "未抓到 JD，仅按标题估分", "lv": "warn"})
    return {
        "score": score, "hit": sorted(hit_c | hit_n),
        "must_miss": sorted(miss_c)[:12], "nice_miss": sorted(miss_n)[:10],
        "flags": flags, "n": len(core) + len(nice),
        "req_years": yrs,   # minimum years required from the JD (0=unstated), for the frontend "experience" filter
        # score confidence: high=full JD / mid=short JD / low=title only — on ties, trust high first
        "conf": ("high" if len(dl) >= 400 else "mid" if dl else "low"),
    }


def visa_certainty(ms, on_register):
    """Visa certainty tiers (top-level frontend filter):
      yes       —— JD explicitly offers sponsorship
      no        —— JD explicitly says no sponsorship
      register  —— company is on the official sponsor register but the JD is silent (most jobs land here)
      uncertain —— aggregator job whose company didn't match the register; sponsorship entirely unknown"""
    txts = [f.get("t", "") for f in ((ms or {}).get("flags") or [])]
    if any("不担保" in t for t in txts):
        return "no"
    if any("提供签证担保" in t for t in txts):
        return "yes"
    return "register" if on_register else "uncertain"


def job_tier(score, ms, visa, tmatch="target"):
    """Recommendation tiers: strong = strongly recommended / maybe = worth a look / weak = poor match /
    lowconf = low confidence (no JD or no score) / risk = visa or security-clearance risk.

    strong requires all three: right role direction (target/acceptable) + score ≥60 +
    no visa/clearance risk. tmatch=off_target roles (IT Support, Sales, etc.) only get weak
    even with high skill scores — so "skill overlap" isn't mistaken for "right role"."""
    txts = [f.get("t", "") for f in ((ms or {}).get("flags") or [])]
    if visa == "no" or any("安全许可" in t for t in txts):
        return "risk"
    if tmatch == "off_target":
        return "weak"     # wrong direction: sink straight away, never in today's picks (checked before lowconf)
    if score is None or any("仅按标题估分" in t for t in txts):
        return "lowconf"
    if score >= 60:
        return "strong"
    if score >= 35:
        return "maybe"
    return "weak"


# Overall ranking weights (role direction is key to precision, so it outweighs the roadmap's original 0.10)
_CONF_W = {"high": 1.0, "mid": 0.6, "low": 0.3}
_VISA_W = {"yes": 1.0, "register": 0.6, "uncertain": 0.3, "no": 0.0}
_TMATCH_W = {"target": 1.0, "acceptable": 0.7, "off_target": 0.0}
TIER_ORDER = {"strong": 0, "maybe": 1, "lowconf": 2, "weak": 3, "risk": 4}


def rank_score(score, conf, visa, tmatch, days):
    """Overall ranking score 0..100: skill×0.40 + direction×0.20 + visa×0.20 + confidence×0.12 + freshness×0.08.
    tier is the coarse bucket (strong/maybe/…); rank_score orders within a bucket and drives "today's top picks"."""
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
