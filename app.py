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
import xml.etree.ElementTree as ET
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
SLUG_OVERRIDE_FILE = os.path.join(DATA_DIR, "slug_overrides.json")
API_KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")

DEFAULT_KEYWORDS = [
    "ai engineer", "machine learning", "ml engineer", "artificial intelligence",
    "llm", "large language model", "nlp", "deep learning", "genai", "gen ai",
    "generative ai", "foundation model", "prompt engineer", "agentic",
    "ai agent", "conversational ai", "data scientist", "research engineer",
    "computer vision", "mlops", "ai scientist", "applied ai",
    # 扩充：召回更多“标题不含 ai/ml 但其实是 AI 方向”的岗位
    "applied scientist", "research scientist", "recommendation",
    "recommendations", "recommender", "personalization", "search ranking",
    "learning to rank", "information retrieval", "knowledge graph",
    "llmops", "ai platform", "model evaluation", "reinforcement learning",
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
    "match_scores": {},    # job_url -> {"score","hit","must_miss","nice_miss","flags","n"}
    "match": {"running": False, "done": 0, "total": 0},
    "match_stats": {},     # JD 抓取覆盖率：{"jd_ok","jd_fail","updated"}
    "exp_years": 1,        # 我的工作年限（用于年限门槛检测）
    "agg_jobs": {},        # 聚合器(Adzuna/Reed)岗位：url -> {...}
    "agg": {"running": False, "done": 0, "total": 0},
}
ats_cache = {}  # name -> {"ats","slug"} | "none"
api_keys = {}   # {"adzuna_app_id","adzuna_app_key","reed_api_key"}
slug_overrides = {}  # name.lower() -> {"ats","slug"}：手动修正 slug 猜错的重点公司


def load_all():
    global ats_cache, slug_overrides, api_keys
    if os.path.exists(API_KEYS_FILE):
        try:
            with open(API_KEYS_FILE, encoding="utf-8") as f:
                api_keys = json.load(f)
        except Exception:
            api_keys = {}
    if os.path.exists(ATS_CACHE_FILE):
        try:
            with open(ATS_CACHE_FILE, encoding="utf-8") as f:
                ats_cache = json.load(f)
        except Exception:
            ats_cache = {}
    if os.path.exists(SLUG_OVERRIDE_FILE):
        try:
            with open(SLUG_OVERRIDE_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            slug_overrides = {k.strip().lower(): v for k, v in raw.items()
                              if isinstance(v, dict) and v.get("ats") and v.get("slug")}
        except Exception:
            slug_overrides = {}
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
        state["match_stats"] = saved.get("match_stats", {})
        state["agg_jobs"] = saved.get("agg_jobs", {})
        state["exp_years"] = saved.get("exp_years", 1)
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
            "match_stats": state["match_stats"],
            "agg_jobs": state["agg_jobs"],
            "exp_years": state["exp_years"],
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


def greenhouse_bodies(slug):
    """Greenhouse 基础列表不含 JD，用 content=true 一次拿全公司所有岗位正文。
    只在有“广撒网候选”时才调用，均摊到每家公司最多一次额外请求。"""
    data = _get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = {}
    for j in (data or {}).get("jobs", []):
        u = j.get("absolute_url", "")
        if u:
            out[u] = _strip_html(j.get("content", ""))
    return out


def _lever_desc(j):
    parts = [j.get("descriptionPlain") or _strip_html(j.get("description", ""))]
    for lst in j.get("lists", []):
        parts.append(lst.get("text", "") + " " + _strip_html(lst.get("content", "")))
    return " ".join(p for p in parts if p)


def probe_lever(slug):
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return None
    jobs = [{
        "title": j.get("text", ""),
        "url": j.get("hostedUrl", ""),
        "location": (j.get("categories") or {}).get("location", "") or "",
        "desc": _lever_desc(j),  # Lever 列表接口自带 JD，二次确认零成本
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
        "desc": j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml", "")),
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
        "desc": _strip_html(str(j.get("description", "")) + " "
                            + str(j.get("requirements", ""))),
    } for j in data["offers"]]
    return {"board_url": f"https://{slug}.recruitee.com/", "jobs": jobs}


def probe_personio(slug):
    # Personio 每家公司自带公开 XML 岗位源，正文也在里面（二次确认零成本）
    try:
        r = _session().get(f"https://{slug}.jobs.personio.com/xml", timeout=TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200 or "<position" not in r.text:
        return None
    try:
        root = ET.fromstring(r.content)
    except Exception:
        return None
    jobs = []
    for pos in root.iter("position"):
        pid = (pos.findtext("id") or "").strip()
        title = (pos.findtext("name") or "").strip()
        if not pid or not title:
            continue
        office = (pos.findtext("office") or "").strip()
        descs = [jd.findtext("value") or "" for jd in pos.iter("jobDescription")]
        jobs.append({
            "title": title,
            "url": f"https://{slug}.jobs.personio.com/job/{pid}",
            "location": office,
            "desc": _strip_html(" ".join(descs)),
        })
    return {"board_url": f"https://{slug}.jobs.personio.com/", "jobs": jobs}


def probe_workday_tenant(host, site):
    """Workday 公开岗位站的匿名接口。host 如 nvidia.wd5.myworkdayjobs.com，
    site 如 NVIDIAExternalCareerSite。只能通过手动 override 配置（无法从公司名猜）。"""
    if not host or not site:
        return None
    tenant = host.split(".")[0]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    jobs, offset = [], 0
    try:
        while offset < 200:  # 最多取 200 个，避免超大站拖慢
            r = _session().post(f"{base}/jobs",
                                json={"appliedFacets": {}, "limit": 20,
                                      "offset": offset, "searchText": ""},
                                timeout=10)
            if r.status_code != 200:
                break
            d = r.json()
            batch = d.get("jobPostings") or []
            for j in batch:
                jobs.append({
                    "title": j.get("title", ""),
                    "url": f"https://{host}/en-US/{site}{j.get('externalPath', '')}",
                    "location": j.get("locationsText", "") or "",
                })  # Workday 列表不含正文 → 只按标题判断
            total = d.get("total") or 0
            offset += 20
            if not batch or offset >= total:
                break
    except Exception:
        return None
    if not jobs:
        return None
    return {"board_url": f"https://{host}/en-US/{site}", "jobs": jobs}


PROBES = [
    ("Greenhouse", probe_greenhouse),
    ("Lever", probe_lever),
    ("Ashby", probe_ashby),
    ("Workable", probe_workable),
    ("SmartRecruiters", probe_smartrecruiters),
    ("Recruitee", probe_recruitee),
    ("Personio", probe_personio),
]
PROBE_FN = dict(PROBES)
# Workday 不参与按公司名猜 slug（需要 host+site），只能手动 override
OVERRIDE_ATS = set(PROBE_FN) | {"Workday"}


def save_slug_overrides():
    _atomic_write(SLUG_OVERRIDE_FILE, json.dumps(slug_overrides, ensure_ascii=False))


def _probe_override(ov):
    ats = ov.get("ats")
    if ats == "Workday":
        return probe_workday_tenant(ov.get("host", ""), ov.get("site", ""))
    fn = PROBE_FN.get(ats)
    if fn and ov.get("slug"):
        try:
            return fn(ov["slug"])
        except Exception:
            return None
    return None


def find_ats(name):
    """返回 (ats_name, slug, {board_url, jobs}) 或 None。结果写入 ats_cache。"""
    ov = slug_overrides.get((name or "").strip().lower())
    if ov:
        res = _probe_override(ov)
        if res:  # 手动修正优先，抓不到再走自动探测
            return (ov["ats"], ov.get("slug") or ov.get("site") or "", res)
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


# 广撒网标题：工程/数据/研究类岗位，标题没写 AI 也值得读 JD 正文二次确认
BROAD_TITLE_RE = re.compile(
    r"\b(engineer|developer|scientist|programmer|architect|researcher)\b")


def match_job(title, desc, keywords):
    """判断一个岗位是否算 AI 岗，返回命中来源：
      'title' —— 标题直接命中 AI 关键词；
      'jd'    —— 标题是工程/数据/研究类且 JD 正文命中 AI 关键词（拓宽召回）；
      None    —— 都没命中。
    JD 正文抓不到时（desc 为空）只走标题，天然保守。"""
    t = (title or "").lower()
    if kw_match(t, keywords):
        return "title"
    if desc and BROAD_TITLE_RE.search(t) and kw_match(desc.lower(), keywords):
        return "jd"
    return None


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
        gh_bodies = None  # Greenhouse 正文按需拉取一次
        for j in res["jobs"]:
            title = (j.get("title") or "").lower()
            body = j.get("desc") or ""
            via = match_job(title, body, keywords)
            if via is None and ats_name == "Greenhouse" and BROAD_TITLE_RE.search(title):
                if gh_bodies is None:
                    gh_bodies = greenhouse_bodies(slug)
                body = gh_bodies.get(j.get("url", ""), "")
                via = match_job(title, body, keywords)
            if via is None:
                continue
            region, rlabel = classify_region(j.get("location"))
            if uk_only and region == "other":
                continue  # 排除美国/亚洲等；英国+欧洲+Remote 都保留
            j.pop("desc", None)  # JD 正文不入库，简历匹配时另存 desc_cache
            j["region"] = region
            j["country"] = rlabel
            j["level"] = classify_level(title)
            j["llm"] = kw_match(title, LLM_KEYWORDS) or bool(
                body and kw_match(body.lower(), LLM_KEYWORDS))
            j["via"] = via  # title=标题命中 / jd=正文命中（标题没写 AI）
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


# ---------------------------------------------------------------- 聚合平台搜索
# Adzuna / Reed 是关键词聚合器：几次调用就能横扫全英国所有公司/ATS 的岗位，
# 是“抓最全 + 求快”的最大杠杆。需要各自的免费官方 API key（放 data/api_keys.json）。
AGG_QUERIES = ["machine learning", "artificial intelligence", "llm",
               "ai engineer", "data scientist", "deep learning"]


def _norm_company(n):
    """公司名归一化，用于把聚合器岗位和官方 sponsor 名单交叉核对。"""
    b = re.sub(r"[^a-z0-9 ]", " ", (n or "").lower())
    words = [w for w in b.split() if w and w not in STRIP_SUFFIXES]
    return " ".join(words)


def search_adzuna(query, pages=2):
    aid, key = api_keys.get("adzuna_app_id"), api_keys.get("adzuna_app_key")
    if not aid or not key:
        return []
    out = []
    for p in range(1, pages + 1):
        url = (f"https://api.adzuna.com/v1/api/jobs/gb/search/{p}"
               f"?app_id={aid}&app_key={key}&results_per_page=50"
               f"&what={quote_plus(query)}&max_days_old=30&content-type=application/json")
        data = _get_json(url)
        res = (data or {}).get("results") or []
        for j in res:
            out.append({
                "company": (j.get("company") or {}).get("display_name", ""),
                "title": j.get("title", ""), "url": j.get("redirect_url", ""),
                "location": (j.get("location") or {}).get("display_name", ""),
                "desc": _strip_html(j.get("description", "")), "source": "Adzuna",
            })
        if len(res) < 50:
            break
    return out


def search_reed(query):
    key = api_keys.get("reed_api_key")
    if not key:
        return []
    try:
        r = _session().get("https://www.reed.co.uk/api/1.0/search",
                           params={"keywords": query, "resultsToTake": 100},
                           auth=(key, ""), timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        res = r.json().get("results") or []
    except Exception:
        return []
    return [{
        "company": j.get("employerName", ""), "title": j.get("jobTitle", ""),
        "url": j.get("jobUrl", ""), "location": j.get("locationName", ""),
        "desc": _strip_html(j.get("jobDescription", "")), "source": "Reed",
    } for j in res]


def run_aggregators():
    """跑 Adzuna+Reed 关键词搜索，AI 过滤后并入 agg_jobs，并标注是否为工签 sponsor。"""
    if not (api_keys.get("adzuna_app_id") or api_keys.get("reed_api_key")):
        return
    kws = [k.lower() for k in state["keywords"]]
    today = date.today().isoformat()
    with _lock:
        sponsor_idx = {_norm_company(n) for n in state["companies"]}
    state["agg"] = {"running": True, "done": 0, "total": len(AGG_QUERIES)}
    try:
        for q in AGG_QUERIES:
            found = search_adzuna(q) + search_reed(q)
            with _lock:
                for j in found:
                    u = j.get("url")
                    title = (j.get("title") or "").lower()
                    desc = j.get("desc") or ""
                    if not u or not match_job(title, desc, kws):
                        continue
                    region, rlabel = classify_region(j.get("location"))
                    seen = state["agg_jobs"].get(u)
                    state["agg_jobs"][u] = {
                        "company": j.get("company", ""), "title": j.get("title", ""),
                        "url": u, "location": j.get("location", ""),
                        "source": j.get("source", ""), "region": region, "country": rlabel,
                        "level": classify_level(title),
                        "llm": kw_match(title, LLM_KEYWORDS) or kw_match(desc.lower(), LLM_KEYWORDS),
                        "sponsor": _norm_company(j.get("company", "")) in sponsor_idx,
                        "first_seen": seen["first_seen"] if seen else today,
                        "last_seen": today,
                    }
                state["agg"]["done"] += 1
    finally:
        state["agg"]["running"] = False
        save_state()


# ---------------------------------------------------------------- 简历匹配
DESC_CACHE_FILE = os.path.join(DATA_DIR, "desc_cache.json")
DESC_FAIL_FILE = os.path.join(DATA_DIR, "desc_fail.json")
FAIL_RETRY_SEC = 24 * 3600  # JD 抓取失败 24 小时后允许重试

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


def load_desc_fail():
    if os.path.exists(DESC_FAIL_FILE):
        try:
            with open(DESC_FAIL_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _should_retry(u, fails):
    """抓取失败过的 URL，超过 24h 才允许再抓，避免每次匹配都重试死链。"""
    ts = fails.get(u)
    if not ts:
        return True
    try:
        return (time.time() - float(ts)) > FAIL_RETRY_SEC
    except (TypeError, ValueError):
        return True


def fetch_descriptions(r, cache, fails):
    """尽力抓取一家公司所有匹配岗位的 JD 文本，写入 cache（url -> text）。
    抓不到的记入 fails（url -> 失败时间戳），24h 后允许重试。"""
    ats, slug = r.get("ats"), r.get("slug")
    urls = {j["url"] for j in r.get("matched", []) if j.get("url")}
    todo = {u for u in urls if not cache.get(u) and _should_retry(u, fails)}
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
        if cache.get(u):
            fails.pop(u, None)          # 这次抓到了，清除失败记录
        else:
            fails[u] = time.time()      # 仍抓不到，登记失败时间，24h 后重试


# --- 贴近真实英国招聘筛选的规则 ---
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
    return {
        "score": score, "hit": sorted(hit_c | hit_n),
        "must_miss": sorted(miss_c)[:12], "nice_miss": sorted(miss_n)[:10],
        "flags": flags, "n": len(core) + len(nice),
    }


def run_match():
    resume = state.get("resume")
    if not resume:
        return
    resume_kws = set(resume["keywords"])
    my_years = state.get("exp_years", 1)
    cache = load_desc_cache()
    fails = load_desc_fail()
    with _lock:
        targets = [(n, dict(r)) for n, r in state["results"].items() if r.get("matched")]
    state["match"] = {"running": True, "done": 0, "total": len(targets)}
    try:
        for n, r in targets:
            fetch_descriptions(r, cache, fails)
            with _lock:
                for j in r.get("matched", []):
                    u = j.get("url", "")
                    res = analyze_job(j.get("title", ""), cache.get(u, ""),
                                      resume_kws, my_years, j.get("level"))
                    if res["n"]:
                        state["match_scores"][u] = res
                state["match"]["done"] += 1
    finally:
        state["match"]["running"] = False
        jd_ok = sum(1 for v in cache.values() if v)
        state["match_stats"] = {"jd_ok": jd_ok, "jd_fail": len(fails),
                                "updated": date.today().isoformat()}
        _atomic_write(DESC_CACHE_FILE, json.dumps(cache, ensure_ascii=False))
        _atomic_write(DESC_FAIL_FILE, json.dumps(fails, ensure_ascii=False))
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
                    "level": j["level"], "via": j.get("via", "title"),
                    "first_seen": fs, "days": days,
                    "score": ms["score"] if ms else None,
                    "hit": ms["hit"] if ms else [],
                    "must_miss": (ms.get("must_miss") or ms.get("miss", [])) if ms else [],
                    "nice_miss": ms.get("nice_miss", []) if ms else [],
                    "flags": ms.get("flags", []) if ms else [],
                })
        # 并入聚合平台(Adzuna/Reed)岗位
        for u, j in state["agg_jobs"].items():
            region = j.get("region", "uk")
            if state["uk_only"] and region == "other":
                continue
            fs = j.get("first_seen", "")
            try:
                days = (today - date.fromisoformat(fs)).days if fs else None
            except Exception:
                days = None
            ms = state["match_scores"].get(u)
            feed.append({
                "title": j.get("title", ""), "url": u,
                "location": j.get("location", ""), "company": j.get("company", ""),
                "curated": False, "llm": bool(j.get("llm")),
                "region": region, "country": j.get("country", ""),
                "level": j.get("level", "mid"), "via": "agg",
                "source": j.get("source", ""), "sponsor": bool(j.get("sponsor")),
                "first_seen": fs, "days": days,
                "score": ms["score"] if ms else None,
                "hit": ms["hit"] if ms else [],
                "must_miss": ms.get("must_miss", []) if ms else [],
                "nice_miss": ms.get("nice_miss", []) if ms else [],
                "flags": ms.get("flags", []) if ms else [],
            })
        feed.sort(key=lambda x: (x["first_seen"] or ""), reverse=True)

        probed = len(ats_cache)
        n_reg = sum(1 for c in comps.values() if "register" in c["tags"])
        mstat = state.get("match_stats") or {}
        jd_ok, jd_fail = mstat.get("jd_ok", 0), mstat.get("jd_fail", 0)
        counts = {
            "total": len(comps), "curated": len(curated), "register": n_reg,
            "probed": probed,
            "pending": sum(1 for n in comps if n not in ats_cache),
            "with_board": len(results),
            "slug_failed": sum(1 for v in ats_cache.values() if v == "none"),
            "overrides": len(slug_overrides),
            "has_ai": sum(1 for r in results.values() if r["status"] == "has_ai"),
            "ai_jobs": len(feed),
            "llm_jobs": sum(1 for j in feed if j["llm"]),
            "via_jd_jobs": sum(1 for j in feed if j.get("via") == "jd"),
            "agg_jobs": sum(1 for j in feed if j.get("via") == "agg"),
            "agg_sponsor": sum(1 for j in feed if j.get("via") == "agg" and j.get("sponsor")),
            "uk_jobs": sum(1 for j in feed if j["region"] in ("uk", "unknown")),
            "eu_jobs": sum(1 for j in feed if j["region"] == "europe"),
            "new_jobs": sum(1 for j in feed if j["days"] is not None and j["days"] <= NEW_DAYS),
            "long_jobs": sum(1 for j in feed if j["days"] is not None and j["days"] >= LONG_RUNNING_DAYS),
            "jd_ok": jd_ok, "jd_fail": jd_fail,
            "jd_rate": (round(100 * jd_ok / (jd_ok + jd_fail)) if (jd_ok + jd_fail) else None),
        }
        scan = dict(state["scan"])
        if scan["running"] and scan["done"]:
            rate = scan["done"] / max(time.time() - scan["started_ts"], 1)
            scan["eta_min"] = round((scan["total"] - scan["done"]) / max(rate, 0.01) / 60)
        resume = state.get("resume")
        return jsonify({
            "keywords": state["keywords"], "uk_only": state["uk_only"],
            "auto_hours": state["auto_hours"], "exp_years": state["exp_years"],
            "counts": counts, "results": res_out, "feed": feed[:400],
            "scan": scan, "match": dict(state["match"]), "agg": dict(state["agg"]),
            "has_api_keys": bool(api_keys.get("adzuna_app_id") or api_keys.get("reed_api_key")),
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
        if "exp_years" in data:
            try:
                state["exp_years"] = max(0, int(data["exp_years"]))
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


@app.route("/api/slug_override", methods=["POST"])
def api_slug_override():
    """手动修正某公司的 ATS 定位（slug 猜错、或 Workday 这类必须手配的）。
    body: {name, ats, slug}  或  {name, ats:"Workday", host, site}。
    slug/host 都传空 → 删除该 override。"""
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "缺少公司名"}), 400
    key = name.lower()
    ats = (data.get("ats") or "").strip()
    slug = (data.get("slug") or "").strip()
    host = (data.get("host") or "").strip()
    site = (data.get("site") or "").strip()
    if not slug and not (host and site):
        slug_overrides.pop(key, None)
        ats_cache.pop(name, None)          # 清掉旧缓存，下次重新探测
    else:
        if ats not in OVERRIDE_ATS:
            return jsonify({"error": f"ats 需为 {sorted(OVERRIDE_ATS)} 之一"}), 400
        if ats == "Workday":
            if not (host and site):
                return jsonify({"error": "Workday 需要 host 和 site"}), 400
            slug_overrides[key] = {"ats": "Workday", "host": host, "site": site}
        else:
            if not slug:
                return jsonify({"error": f"{ats} 需要 slug"}), 400
            slug_overrides[key] = {"ats": ats, "slug": slug}
        ats_cache.pop(name, None)          # 让下次扫描按 override 走
    save_slug_overrides()
    save_ats_cache()
    return jsonify({"ok": True, "overrides": len(slug_overrides)})


@app.route("/api/aggregators", methods=["POST"])
def api_aggregators():
    """触发 Adzuna/Reed 聚合搜索，横扫全英国 AI 岗位。"""
    if not (api_keys.get("adzuna_app_id") or api_keys.get("reed_api_key")):
        return jsonify({"error": "未配置 Adzuna/Reed 的 API key（见 data/api_keys.json）"}), 400
    if state["agg"]["running"]:
        return jsonify({"error": "聚合搜索进行中"}), 409
    threading.Thread(target=run_aggregators, daemon=True).start()
    return jsonify({"started": True, "queries": len(AGG_QUERIES)})


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
    port = int(os.environ.get("PORT", "5050"))
    print(f"\n  AI Job Scout 已启动:  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
