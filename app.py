# -*- coding: utf-8 -*-
"""AI Job Scout — 扫描全部工签雇主的 AI/LLM 岗位。

用法:  python app.py  然后浏览器打开 http://127.0.0.1:5050
"""
import csv as csvmod
import json
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime
from io import BytesIO
from urllib.parse import quote_plus

import requests
from flask import Flask, jsonify, render_template, request, send_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "state.json")
COMPANIES_FILE = os.path.join(DATA_DIR, "companies.json")
ATS_CACHE_FILE = os.path.join(DATA_DIR, "ats_cache.json")

DEFAULT_KEYWORDS = [
    "ai engineer", "machine learning", "ml engineer", "artificial intelligence",
    "llm", "large language model", "nlp", "deep learning", "genai", "gen ai",
    "generative ai", "foundation model", "prompt engineer", "agentic",
    "ai agent", "conversational ai", "data scientist", "research engineer",
    "computer vision", "mlops", "ai scientist", "applied ai",
]

# 命中即标 ⭐LLM 的关键词（用户重点关注）
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
        return ("uk", "")  # 没写地点的默认可申请
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

HEADERS = {"User-Agent": "Mozilla/5.0 (personal job-search tool)"}
TIMEOUT = 5
LONG_RUNNING_DAYS = 30   # 岗位在线 ≥30 天算“长期在招”
NEW_DAYS = 3             # 首次发现 ≤3 天算“新岗位”

app = Flask(__name__)

# ---------------------------------------------------------------- state
_lock = threading.Lock()
state = {
    "companies": {},   # name -> {"tags": ["curated"|"register"], "town": str}
    "keywords": DEFAULT_KEYWORDS,
    "uk_only": True,
    "auto_hours": 0,   # >0 时后台每隔 N 小时自动快速刷新
    "results": {},     # name -> result（只存探测到招聘页的公司 + 精选公司）
    "jobs_seen": {},   # job_url -> {"first_seen","last_seen"}
    "scan": {"running": False, "done": 0, "total": 0, "mode": None,
             "started_ts": 0, "stop": False, "new_jobs": 0},
    "last_auto": 0,
    "resume": None,        # {"text","keywords","updated","name"}
    "match_scores": {},    # job_url -> {"score","hit","miss","n"}
    "match": {"running": False, "done": 0, "total": 0},
}
ats_cache = {}  # name -> {"ats","slug"} | "none"


def load_all():
    global ats_cache
    if os.path.exists(ATS_CACHE_FILE):
        try:
            with open(ATS_CACHE_FILE, encoding="utf-8") as f:
                ats_cache = json.load(f)
        except Exception:
            ats_cache = {}
    if os.path.exists(COMPANIES_FILE):
        try:
            with open(COMPANIES_FILE, encoding="utf-8") as f:
                state["companies"] = json.load(f)
        except Exception:
            pass
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return
        comps = saved.get("companies", {})
        if isinstance(comps, list):  # 旧版本格式迁移：当时导入的就是精选清单
            comps = {c["name"]: {"tags": ["curated"], "town": ""} for c in comps}
        if comps and not state["companies"]:
            state["companies"] = comps
        state["keywords"] = saved.get("keywords", DEFAULT_KEYWORDS)
        state["uk_only"] = saved.get("uk_only", True)
        state["auto_hours"] = saved.get("auto_hours", 0)
        state["jobs_seen"] = saved.get("jobs_seen", {})
        state["resume"] = saved.get("resume")
        state["match_scores"] = saved.get("match_scores", {})
        for name, r in saved.get("results", {}).items():
            r.pop("links", None)  # 旧版把链接存了盘，现在改为按需生成
            state["results"][name] = r


def _atomic_write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, path)


def save_companies():
    """公司名单单独存（12 万条只在导入时变），避免扫描期间反复写大文件。
    调用方不得持锁。"""
    with _lock:
        payload = json.dumps(state["companies"], ensure_ascii=False)
    _atomic_write(COMPANIES_FILE, payload)


def save_state():
    """锁内序列化（results/jobs_seen 都不大），锁外写盘。调用方不得持锁。"""
    with _lock:
        payload = json.dumps({
            "keywords": state["keywords"],
            "uk_only": state["uk_only"],
            "auto_hours": state["auto_hours"],
            "results": state["results"],
            "jobs_seen": state["jobs_seen"],
            "resume": state["resume"],
            "match_scores": state["match_scores"],
        }, ensure_ascii=False)
    _atomic_write(STATE_FILE, payload)


def save_ats_cache():
    with open(ATS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(ats_cache, f, ensure_ascii=False)


# ---------------------------------------------------------------- slug 生成
STRIP_SUFFIXES = [
    "ltd", "limited", "plc", "llp", "inc", "uk", "group", "holdings",
    "international", "technologies", "technology", "labs", "lab", "co",
]


def slug_candidates(name):
    base = name.lower().strip()
    base = re.sub(r"t/a.*$", " ", base)  # 去掉 trading-as 别名
    base = re.sub(r"[&+]", " and ", base)
    base = re.sub(r"[^a-z0-9\s-]", "", base)
    words = [w for w in base.split() if w]
    trimmed = list(words)
    while len(trimmed) > 1 and trimmed[-1] in STRIP_SUFFIXES:
        trimmed.pop()
    # 只试命中率最高的形式，控制全量清查的请求量
    cands = []
    if trimmed:
        cands.append("".join(trimmed))
        cands.append("-".join(trimmed))
    if words != trimmed and words:
        cands.append("".join(words))
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:3]


# ---------------------------------------------------------------- ATS 探测
_tls = threading.local()


def _session():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
        _tls.s.headers.update(HEADERS)
    return _tls.s


def _get_json(url):
    r = _session().get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    return r.json()


def probe_greenhouse(slug):
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if not data or "jobs" not in data:
        return None
    jobs = [{
        "title": j.get("title", ""),
        "url": j.get("absolute_url", ""),
        "location": (j.get("location") or {}).get("name", ""),
    } for j in data["jobs"]]
    return {"board_url": f"https://boards.greenhouse.io/{slug}", "jobs": jobs}


def probe_lever(slug):
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return None
    jobs = [{
        "title": j.get("text", ""),
        "url": j.get("hostedUrl", ""),
        "location": (j.get("categories") or {}).get("location", "") or "",
    } for j in data]
    return {"board_url": f"https://jobs.lever.co/{slug}", "jobs": jobs}


def probe_ashby(slug):
    data = _get_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false")
    if not data or "jobs" not in data:
        return None
    jobs = [{
        "title": j.get("title", ""),
        "url": j.get("jobUrl", "") or j.get("applyUrl", ""),
        "location": j.get("location", "") or "",
    } for j in data["jobs"]]
    return {"board_url": f"https://jobs.ashbyhq.com/{slug}", "jobs": jobs}


def probe_workable(slug):
    data = _get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if not data or "jobs" not in data:
        return None
    jobs = [{
        "title": j.get("title", ""),
        "url": j.get("url", ""),
        "location": ", ".join(x for x in [j.get("city", ""), j.get("country", "")] if x),
    } for j in data["jobs"]]
    return {"board_url": f"https://apply.workable.com/{slug}/", "jobs": jobs}


def probe_smartrecruiters(slug):
    data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    # SmartRecruiters 对不存在的公司也返回 200+空列表，必须把空结果当未命中
    if not data or not data.get("content"):
        return None
    jobs = []
    for j in data["content"]:
        loc = j.get("location") or {}
        jobs.append({
            "title": j.get("name", ""),
            "url": f"https://jobs.smartrecruiters.com/{slug}/{j.get('id', '')}",
            "location": ", ".join(x for x in [loc.get("city", ""), loc.get("country", "")] if x),
        })
    return {"board_url": f"https://jobs.smartrecruiters.com/{slug}", "jobs": jobs}


def probe_recruitee(slug):
    data = _get_json(f"https://{slug}.recruitee.com/api/offers/")
    if not data or "offers" not in data:
        return None
    jobs = [{
        "title": j.get("title", ""),
        "url": j.get("careers_url", ""),
        "location": j.get("location", "") or "",
    } for j in data["offers"]]
    return {"board_url": f"https://{slug}.recruitee.com/", "jobs": jobs}


PROBES = [
    ("Greenhouse", probe_greenhouse),
    ("Lever", probe_lever),
    ("Ashby", probe_ashby),
    ("Workable", probe_workable),
    ("SmartRecruiters", probe_smartrecruiters),
    ("Recruitee", probe_recruitee),
]
PROBE_FN = dict(PROBES)


def find_ats(name):
    """返回 (ats_name, slug, {board_url, jobs}) 或 None。结果写入 ats_cache。"""
    cached = ats_cache.get(name)
    if cached == "none":
        return None
    if isinstance(cached, dict):
        try:
            res = PROBE_FN[cached["ats"]](cached["slug"])
        except Exception:
            res = None
        if res:
            return (cached["ats"], cached["slug"], res)
        # 缓存失效则重新探测

    fallback = None  # 0 岗位的空账号可能是重名壳账号，只作兜底
    for slug in slug_candidates(name):
        for ats_name, fn in PROBES:
            try:
                res = fn(slug)
            except Exception:
                res = None
            if res:
                if res["jobs"]:
                    ats_cache[name] = {"ats": ats_name, "slug": slug}
                    return (ats_name, slug, res)
                if fallback is None:
                    fallback = (ats_name, slug, res)
    if fallback:
        ats_cache[name] = {"ats": fallback[0], "slug": fallback[1]}
        return fallback
    ats_cache[name] = "none"
    return None


# ---------------------------------------------------------------- 匹配
def kw_match(text, kws):
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in kws)


def build_links(name):
    q = quote_plus(name)
    return {
        "li_people": ("https://www.linkedin.com/search/results/people/?keywords="
                      + quote_plus(f'"{name}" (recruiter OR "talent acquisition" OR "hiring manager" OR "engineering manager")')),
        "li_jobs_kw": ("https://www.linkedin.com/jobs/search/?keywords="
                       + quote_plus(f"{name} AI machine learning engineer") + "&location=United%20Kingdom"),
        "google": ("https://www.google.com/search?q="
                   + quote_plus(f'"{name}" ("AI engineer" OR "machine learning engineer") job UK')),
        "hunter": f"https://hunter.io/search/{q}",
        "careers_google": ("https://www.google.com/search?q="
                           + quote_plus(f"{name} careers jobs")),
    }


# ---------------------------------------------------------------- 扫描
def scan_company(name, keywords, uk_only):
    result = {
        "name": name,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ats": None, "slug": None, "board_url": None,
        "total_jobs": 0, "matched": [],
        "status": "no_board",
    }
    hit = find_ats(name)
    if hit:
        ats_name, slug, res = hit
        result["ats"] = ats_name
        result["slug"] = slug
        result["board_url"] = res["board_url"]
        result["total_jobs"] = len(res["jobs"])
        matched = []
        for j in res["jobs"]:
            title = (j.get("title") or "").lower()
            if not kw_match(title, keywords):
                continue
            region, rlabel = classify_region(j.get("location"))
            if uk_only and region == "other":
                continue  # 排除美国/亚洲等；英国+欧洲+Remote 都保留
            j["region"] = region
            j["country"] = rlabel
            j["level"] = classify_level(title)
            j["llm"] = kw_match(title, LLM_KEYWORDS)
            matched.append(j)
        result["matched"] = matched[:80]
        if matched:
            result["status"] = "has_ai"
        elif res["jobs"]:
            result["status"] = "board_no_ai"
        else:
            result["status"] = "no_board"  # 空壳账号
    return result


def _curated_names():
    return {n for n, c in state["companies"].items() if "curated" in c.get("tags", [])}


def _record_result(name, res, today, curated):
    """在锁内调用：登记岗位首见/末见日期，按需入库。"""
    for j in res.get("matched", []):
        seen = state["jobs_seen"].setdefault(j["url"], {"first_seen": today})
        seen["last_seen"] = today
        j["first_seen"] = seen["first_seen"]
        if seen["first_seen"] == today:
            state["scan"]["new_jobs"] += 1
    if res["status"] == "no_board" and name not in curated:
        state["results"].pop(name, None)  # register 里没招聘页的不占地方
    else:
        state["results"][name] = res


def run_scan(names, mode):
    keywords = [k.lower() for k in state["keywords"]]
    uk_only = state["uk_only"]
    curated = _curated_names()
    today = date.today().isoformat()
    state["scan"] = {"running": True, "done": 0, "total": len(names), "mode": mode,
                     "started_ts": time.time(), "stop": False, "new_jobs": 0}
    processed = 0
    try:
        with ThreadPoolExecutor(max_workers=32) as pool:
            it = iter(names)
            futures = {}

            def submit_more():
                while len(futures) < 128:
                    try:
                        n = next(it)
                    except StopIteration:
                        return
                    futures[pool.submit(scan_company, n, keywords, uk_only)] = n

            submit_more()
            while futures:
                done_set, _ = wait(list(futures), return_when=FIRST_COMPLETED)
                for fut in done_set:
                    n = futures.pop(fut)
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"name": n, "status": "error", "error": str(e),
                               "matched": [], "scanned_at": today}
                    with _lock:
                        _record_result(n, res, today, curated)
                        state["scan"]["done"] += 1
                    processed += 1
                    if processed % 500 == 0:
                        save_ats_cache()
                        save_state()
                if not state["scan"]["stop"]:
                    submit_more()
    finally:
        state["scan"]["running"] = False
        save_ats_cache()
        save_state()


def start_scan(mode):
    """mode: curated / known / pending / all"""
    if state["scan"]["running"]:
        return None
    comps = state["companies"]
    curated = _curated_names()
    if mode == "curated":
        names = sorted(curated)
    elif mode == "known":   # 已探测到招聘系统的公司：快速刷新最新岗位
        names = [n for n in comps if isinstance(ats_cache.get(n), dict)]
    elif mode == "pending":  # 还没探测过的公司：全量清查（可中断续跑）
        names = [n for n in comps if n not in ats_cache]
    else:  # all
        known = [n for n in comps if isinstance(ats_cache.get(n), dict)]
        pending = [n for n in comps if n not in ats_cache]
        names = sorted(curated) + [n for n in known if n not in curated] + pending
    if not names:
        return 0
    threading.Thread(target=run_scan, args=(names, mode), daemon=True).start()
    return len(names)


def auto_loop():
    """auto_hours>0 时定时快速刷新已知招聘系统，第一时间发现新岗位。"""
    while True:
        time.sleep(300)
        try:
            h = state["auto_hours"]
            if h > 0 and not state["scan"]["running"] \
                    and time.time() - state["last_auto"] > h * 3600:
                if start_scan("known"):
                    state["last_auto"] = time.time()
        except Exception:
            pass


# ---------------------------------------------------------------- 简历匹配
DESC_CACHE_FILE = os.path.join(DATA_DIR, "desc_cache.json")

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
    "monitoring", "grafana", "linux", "git", "rest api", "api",
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
          "transformers": "transformer", "statistical": "statistics"}


def extract_skills(text):
    t = (text or "").lower()
    found = set()
    for kw, rx in _VOCAB_RES:
        if rx.search(t):
            found.add(_CANON.get(kw, kw))
    return found


def _strip_html(html_text):
    import html as htmlmod
    txt = re.sub(r"<[^>]+>", " ", html_text or "")
    return re.sub(r"\s+", " ", htmlmod.unescape(txt)).strip()


def extract_resume_text(file_storage):
    fname = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if fname.endswith(".pdf"):
        from io import BytesIO as B
        from pypdf import PdfReader
        reader = PdfReader(B(raw))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if fname.endswith(".docx"):
        import zipfile
        from io import BytesIO as B
        with zipfile.ZipFile(B(raw)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return _strip_html(xml)
    return raw.decode("utf-8-sig", errors="replace")


def load_desc_cache():
    if os.path.exists(DESC_CACHE_FILE):
        try:
            with open(DESC_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def fetch_descriptions(r, cache):
    """尽力抓取一家公司所有匹配岗位的 JD 文本，写入 cache（url -> text）。"""
    ats, slug = r.get("ats"), r.get("slug")
    urls = {j["url"] for j in r.get("matched", []) if j.get("url")}
    todo = {u for u in urls if u not in cache}
    if not todo or not ats:
        return
    try:
        if ats == "Greenhouse":
            data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
            for j in (data or {}).get("jobs", []):
                u = j.get("absolute_url", "")
                if u in urls:
                    cache[u] = _strip_html(j.get("content", ""))[:8000]
        elif ats == "Lever":
            data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
            for j in data or []:
                u = j.get("hostedUrl", "")
                if u in urls:
                    parts = [j.get("descriptionPlain") or _strip_html(j.get("description", ""))]
                    for lst in j.get("lists", []):
                        parts.append(lst.get("text", "") + " " + _strip_html(lst.get("content", "")))
                    cache[u] = " ".join(parts)[:8000]
        elif ats == "Ashby":
            data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false")
            for j in (data or {}).get("jobs", []):
                u = j.get("jobUrl", "") or j.get("applyUrl", "")
                if u in urls:
                    cache[u] = _strip_html(j.get("descriptionHtml", ""))[:8000]
        elif ats == "Recruitee":
            data = _get_json(f"https://{slug}.recruitee.com/api/offers/")
            for j in (data or {}).get("offers", []):
                u = j.get("careers_url", "")
                if u in urls:
                    cache[u] = _strip_html(str(j.get("description", "")) + " "
                                           + str(j.get("requirements", "")))[:8000]
        elif ats == "Workable":
            data = _get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
            for j in (data or {}).get("jobs", []):
                if j.get("url") in todo and j.get("shortcode"):
                    d = _get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}/jobs/{j['shortcode']}")
                    if d:
                        cache[j["url"]] = _strip_html(
                            str(d.get("description", "")) + " " + str(d.get("requirements", "")))[:8000]
        elif ats == "SmartRecruiters":
            for u in todo:
                jid = u.rstrip("/").rsplit("/", 1)[-1]
                d = _get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}")
                if d:
                    secs = ((d.get("jobAd") or {}).get("sections") or {})
                    cache[u] = _strip_html(" ".join(
                        str(s.get("text", "")) for s in secs.values() if isinstance(s, dict)))[:8000]
    except Exception:
        pass
    for u in todo:
        cache.setdefault(u, "")  # 抓不到的记空串，避免反复重试


def run_match():
    resume = state.get("resume")
    if not resume:
        return
    resume_kws = set(resume["keywords"])
    cache = load_desc_cache()
    with _lock:
        targets = [(n, dict(r)) for n, r in state["results"].items() if r.get("matched")]
    state["match"] = {"running": True, "done": 0, "total": len(targets)}
    try:
        for n, r in targets:
            fetch_descriptions(r, cache)
            with _lock:
                for j in r.get("matched", []):
                    u = j.get("url", "")
                    text = (j.get("title", "") + " ") * 2 + cache.get(u, "")
                    job_kws = extract_skills(text)
                    if not job_kws:
                        continue
                    hit = sorted(job_kws & resume_kws)
                    miss = sorted(job_kws - resume_kws)
                    # 分母设下限：JD 抓不到全文、只有零星关键词时分数保守些
                    state["match_scores"][u] = {
                        "score": round(100 * len(hit) / max(len(job_kws), 6)),
                        "hit": hit, "miss": miss[:15], "n": len(job_kws),
                    }
                state["match"]["done"] += 1
    finally:
        state["match"]["running"] = False
        with open(DESC_CACHE_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(DESC_CACHE_FILE + ".tmp", DESC_CACHE_FILE)
        save_state()


@app.route("/api/resume", methods=["POST"])
def api_resume():
    f = request.files.get("file")
    if f:
        try:
            text = extract_resume_text(f)
        except Exception as e:
            return jsonify({"error": f"解析失败: {e}（可试试导出为 PDF/TXT 再传）"}), 400
        name = f.filename
    else:
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        name = "粘贴文本"
    text = (text or "").strip()
    if len(text) < 100:
        return jsonify({"error": "简历内容太短，未能识别（PDF 若是扫描件请用文字版）"}), 400
    kws = sorted(extract_skills(text))
    with _lock:
        state["resume"] = {"text": text[:20000], "keywords": kws, "name": name,
                           "updated": date.today().isoformat()}
        state["match_scores"] = {}
    save_state()
    threading.Thread(target=run_match, daemon=True).start()
    return jsonify({"ok": True, "keywords": kws, "chars": len(text)})


@app.route("/api/match", methods=["POST"])
def api_match():
    if not state.get("resume"):
        return jsonify({"error": "请先上传简历"}), 400
    if state["match"]["running"]:
        return jsonify({"error": "匹配计算进行中"}), 409
    threading.Thread(target=run_match, daemon=True).start()
    return jsonify({"started": True})


# ---------------------------------------------------------------- 导入
COMPANY_HEADER_HINTS = ["company", "organisation", "organization", "employer",
                        "sponsor", "name", "公司", "雇主", "企业"]


def _pick_company_col(header):
    best = None
    for i, h in enumerate(header):
        if h is None:
            continue
        hl = str(h).lower()
        for hint in COMPANY_HEADER_HINTS:
            if hint in hl:
                if hint != "name":
                    return i
                if best is None:
                    best = i
    return best


def add_companies(names, tag, towns=None):
    added = 0
    with _lock:
        norm_existing = {n.strip().lower(): n for n in state["companies"]}
        for i, n in enumerate(names):
            n = n.strip()
            if not n:
                continue
            key = n.lower()
            if key in norm_existing:
                cur = state["companies"][norm_existing[key]]
                if tag not in cur["tags"]:
                    cur["tags"].append(tag)
            else:
                state["companies"][n] = {
                    "tags": [tag],
                    "town": (towns[i] if towns else "") or "",
                }
                norm_existing[key] = n
                added += 1
    save_companies()
    return added


@app.route("/api/import_register", methods=["POST"])
def api_import_register():
    data = request.get_json(force=True)
    path = (data.get("path") or "").strip().strip('"')
    if not os.path.exists(path):
        return jsonify({"error": f"文件不存在: {path}"}), 400
    names, towns, seen = [], [], set()
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for row in csvmod.DictReader(f):
                if (row.get("Route") or "").strip() != "Skilled Worker":
                    continue
                n = (row.get("Organisation Name") or "").strip()
                if not n:
                    continue
                key = n.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(n)
                towns.append((row.get("Town/City") or "").strip())
    except Exception as e:
        return jsonify({"error": f"解析失败: {e}"}), 400
    added = add_companies(names, "register", towns)
    return jsonify({"parsed": len(names), "added": added,
                    "total": len(state["companies"])})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "没有收到文件"}), 400
    fname = f.filename.lower()
    names = []
    try:
        if fname.endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(BytesIO(f.read()), read_only=True, data_only=True)
            for ws in wb.worksheets:
                rows = ws.iter_rows(values_only=True)
                try:
                    header = next(rows)
                except StopIteration:
                    continue
                col = _pick_company_col(header)
                if col is None:
                    continue
                for row in rows:
                    if col < len(row) and row[col]:
                        v = str(row[col]).strip()
                        if v and not v.startswith("="):
                            names.append(v)
                if names:
                    break
        else:
            text = f.read().decode("utf-8-sig", errors="replace")
            rows = list(csvmod.reader(text.splitlines()))
            if rows:
                col = _pick_company_col(rows[0])
                if col is not None and len(rows) > 1:
                    names = [r[col].strip() for r in rows[1:] if len(r) > col and r[col].strip()]
                else:
                    names = [r[0].strip() for r in rows if r and r[0].strip()]
    except Exception as e:
        return jsonify({"error": f"解析失败: {e}"}), 400
    if not names:
        return jsonify({"error": "没有识别到公司名"}), 400
    added = add_companies(names, "curated")
    return jsonify({"count": added, "total": len(state["companies"])})


@app.route("/api/companies", methods=["POST"])
def api_companies():
    data = request.get_json(force=True)
    names = [n for n in data.get("names", []) if n.strip()]
    added = add_companies(names, "curated")
    return jsonify({"added": added, "total": len(state["companies"])})


# ---------------------------------------------------------------- 路由
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    today = date.today()
    with _lock:
        curated = _curated_names()
        comps = state["companies"]
        results = state["results"]

        res_out = {}
        for n, r in results.items():
            rr = dict(r)
            rr["links"] = build_links(n)
            rr["curated"] = n in curated
            res_out[n] = rr
        # 精选公司即使没探测到招聘页也要显示
        for n in curated:
            if n not in res_out:
                st = "no_board" if ats_cache.get(n) == "none" else "pending"
                res_out[n] = {"name": n, "status": st, "matched": [],
                              "curated": True, "links": build_links(n)}

        feed = []
        for n, r in results.items():
            for j in r.get("matched", []):
                # 旧数据可能缺 region/level，即时补算
                if "region" not in j:
                    j["region"], j["country"] = classify_region(j.get("location"))
                if "level" not in j:
                    j["level"] = classify_level(j.get("title"))
                fs = j.get("first_seen", "")
                try:
                    days = (today - date.fromisoformat(fs)).days if fs else None
                except Exception:
                    days = None
                ms = state["match_scores"].get(j.get("url", ""))
                feed.append({
                    "title": j.get("title", ""), "url": j.get("url", ""),
                    "location": j.get("location", ""), "company": n,
                    "curated": n in curated, "llm": bool(j.get("llm")),
                    "region": j["region"], "country": j.get("country", ""),
                    "level": j["level"],
                    "first_seen": fs, "days": days,
                    "score": ms["score"] if ms else None,
                    "hit": ms["hit"] if ms else [], "miss": ms["miss"] if ms else [],
                })
        feed.sort(key=lambda x: (x["first_seen"] or ""), reverse=True)

        probed = len(ats_cache)
        n_reg = sum(1 for c in comps.values() if "register" in c["tags"])
        counts = {
            "total": len(comps), "curated": len(curated), "register": n_reg,
            "probed": probed,
            "pending": sum(1 for n in comps if n not in ats_cache),
            "with_board": len(results),
            "has_ai": sum(1 for r in results.values() if r["status"] == "has_ai"),
            "ai_jobs": len(feed),
            "llm_jobs": sum(1 for j in feed if j["llm"]),
            "uk_jobs": sum(1 for j in feed if j["region"] in ("uk", "unknown")),
            "eu_jobs": sum(1 for j in feed if j["region"] == "europe"),
            "new_jobs": sum(1 for j in feed if j["days"] is not None and j["days"] <= NEW_DAYS),
            "long_jobs": sum(1 for j in feed if j["days"] is not None and j["days"] >= LONG_RUNNING_DAYS),
        }
        scan = dict(state["scan"])
        if scan["running"] and scan["done"]:
            rate = scan["done"] / max(time.time() - scan["started_ts"], 1)
            scan["eta_min"] = round((scan["total"] - scan["done"]) / max(rate, 0.01) / 60)
        resume = state.get("resume")
        return jsonify({
            "keywords": state["keywords"], "uk_only": state["uk_only"],
            "auto_hours": state["auto_hours"],
            "counts": counts, "results": res_out, "feed": feed[:400],
            "scan": scan, "match": dict(state["match"]),
            "resume": ({"name": resume["name"], "updated": resume["updated"],
                        "keywords": resume["keywords"], "text": resume["text"]}
                       if resume else None),
            "consts": {"new_days": NEW_DAYS, "long_days": LONG_RUNNING_DAYS,
                       "level_labels": LEVEL_LABELS},
        })


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(force=True)
    with _lock:
        if "keywords" in data:
            kws = [k.strip().lower() for k in data["keywords"] if k.strip()]
            if kws:
                state["keywords"] = kws
        if "uk_only" in data:
            state["uk_only"] = bool(data["uk_only"])
        if "auto_hours" in data:
            try:
                state["auto_hours"] = max(0, int(data["auto_hours"]))
            except Exception:
                pass
    save_state()
    return jsonify({"ok": True})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "known")
    n = start_scan(mode)
    if n is None:
        return jsonify({"error": "已有扫描在进行中"}), 409
    if n == 0:
        return jsonify({"error": "该模式下没有待扫描的公司"}), 400
    return jsonify({"started": True, "total": n, "mode": mode})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    state["scan"]["stop"] = True
    return jsonify({"ok": True})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    with _lock:
        state["companies"] = {}
        state["results"] = {}
        state["jobs_seen"] = {}
    save_companies()
    save_state()
    return jsonify({"ok": True})


@app.route("/api/export")
def api_export():
    import openpyxl
    from openpyxl.styles import Font
    today = date.today()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AI Jobs"
    head = ["Company", "精选", "Job Title", "级别", "LLM", "地区", "Location",
            "首次发现", "在线天数", "长期在招", "Job URL", "ATS", "Job Board",
            "LinkedIn People Search", "Hunter.io"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    with _lock:
        results = dict(state["results"])
        curated = _curated_names()
    rows = []
    for name, r in results.items():
        links = build_links(name)
        for j in r.get("matched", []):
            fs = j.get("first_seen", "")
            try:
                days = (today - date.fromisoformat(fs)).days if fs else ""
            except Exception:
                days = ""
            level = j.get("level") or classify_level(j.get("title"))
            region = j.get("region")
            country = j.get("country", "")
            if not region:
                region, country = classify_region(j.get("location"))
            rows.append([
                name, "⭐" if name in curated else "", j.get("title", ""),
                LEVEL_LABELS.get(level, level), "⭐" if j.get("llm") else "",
                country or ("UK" if region in ("uk", "unknown") else region),
                j.get("location", ""), fs, days,
                "长期" if isinstance(days, int) and days >= LONG_RUNNING_DAYS else "",
                j.get("url", ""), r.get("ats") or "", r.get("board_url") or "",
                links["li_people"], links["hunter"],
            ])
    rows.sort(key=lambda x: (x[7] or ""), reverse=True)
    for row in rows:
        ws.append(row)
    for col, w in zip("ABCDEFGHIJKLMNO", [28, 6, 45, 10, 6, 12, 25, 12, 9, 9, 60, 14, 40, 60, 40]):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"AI_Job_Scout_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    load_all()
    if state["companies"] and not os.path.exists(COMPANIES_FILE):
        save_companies()  # 从旧格式迁移时立即落盘，防止丢名单
    threading.Thread(target=auto_loop, daemon=True).start()
    print("\n  AI Job Scout 已启动:  http://127.0.0.1:5050\n")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
