# -*- coding: utf-8 -*-
"""AI Job Scout — scan every UK visa-sponsor employer for AI/LLM roles.

Usage:  python app.py  then open http://127.0.0.1:5050 in a browser
"""
import contextvars
import csv as csvmod
import hashlib
import hmac
import json
from collections import Counter, deque
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from io import BytesIO
from urllib.parse import quote_plus

import requests
from flask import (Flask, Response, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)

FROZEN = getattr(sys, "frozen", False)  # running as a PyInstaller-packaged exe
if FROZEN:
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))  # data/ lives next to the exe
    RES_DIR = sys._MEIPASS  # templates and other resources are bundled inside
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = BASE_DIR
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "state.json")
COMPANIES_FILE = os.path.join(DATA_DIR, "companies.json")
ATS_CACHE_FILE = os.path.join(DATA_DIR, "ats_cache.json")
SLUG_OVERRIDE_FILE = os.path.join(DATA_DIR, "slug_overrides.json")
API_KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")
COMPANY_SIZE_FILE = os.path.join(DATA_DIR, "company_sizes.json")

DEFAULT_KEYWORDS = [
    "ai engineer", "machine learning", "ml engineer", "artificial intelligence",
    "llm", "large language model", "nlp", "deep learning", "genai", "gen ai",
    "generative ai", "foundation model", "prompt engineer", "agentic",
    "ai agent", "conversational ai", "data scientist", "research engineer",
    "computer vision", "mlops", "ai scientist", "applied ai",
    # Expanded: recall more roles that are AI work even without "ai/ml" in the title
    "applied scientist", "research scientist", "recommendation",
    "recommendations", "recommender", "personalization", "search ranking",
    "learning to rank", "information retrieval", "knowledge graph",
    "llmops", "ai platform", "model evaluation", "reinforcement learning",
]

# Pure matching/scoring logic lives in matching.py (Flask-free, unit-tested).
from matching import (  # noqa: E402
    TITLE_ONLY_KEYWORDS, LLM_KEYWORDS, UK_RE, EU_PLACES, EU_RES, CHINA_RE,
    OTHER_RE, classify_region, LEVEL_LABELS, classify_level,
    LONG_RUNNING_DAYS, NEW_DAYS,
    kw_match, kw_hit_count, BROAD_TITLE_RE, EXCLUDE_TITLE_RE, match_job,
    DEFAULT_TARGET_TITLES, DEFAULT_ACCEPTABLE_TITLES, title_match,
    SKILL_VOCAB, KNOWN_SKILLS, extract_skills,
    NICE_SPLIT_RE, YEARS_RES, CLEARANCE_RE, NO_SPONSOR_RE, YES_SPONSOR_RE,
    LEVEL_YEARS, DOMAIN_SKILLS, W_REQUIRED, W_PREFERRED, W_LEVEL, W_DOMAIN,
    W_CONF, analyze_job, visa_certainty, job_tier, TIER_ORDER, rank_score,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (personal job-search tool)"}
# (connect, read) split: dead per-company subdomains give up connecting after 2s (used to burn the full 5s);
# read still gets 5s so slow-but-valid boards like Workable aren't misjudged as "no jobs".
TIMEOUT = (2, 5)
# Outer concurrency. The full hot path only runs the 4 healthy ATSs (GH/Lever/Ashby/SR) — they don't rate-limit, and probes
# run sequentially inside each worker thread to reuse keep-alive connections, so 32 is fine. Workable, the harshest limiter, is off the hot path
# (see WORKABLE_PROBES), so high concurrency no longer triggers 429s.
SCAN_WORKERS = 32
# Workable global concurrency cap: most hits but harshest rate limiting. It gates deep-rescan throughput (every find_ats must first
# pass this semaphore) — 4 was too conservative and squeezed 32 threads to near single-threaded. Raised to 12: 3x throughput; with per-probe 429 backoff
# self-throttling (see probe_workable) + the removed global 5-minute cooldown, measurably faster. Lower it if 429s are frequent.
# Tunable via env var: watch the 429 count on the scan progress bar — few 429s, raise it; many, lower it.
WORKABLE_CONC = int(os.environ.get("WORKABLE_CONC", "12"))
SWEEP_SLUGS = 2          # slug candidates tried per company in a full sweep (hits almost always land in the first 2)
# Deep-rescan only: the non-rate-limited Recruitee/Personio are pure DNS/IO waits, so higher concurrency fills the gaps while
# Workable queues; the rescan also favours speed, trying only 1 slug per company (half the probes).
DEEP_WORKERS = int(os.environ.get("DEEP_WORKERS", "48"))
DEEP_SLUGS = 1
# Deep rescan runs only Workable by default. Measured per non-existent company: Workable 0.26s (426 historical hits),
# Recruitee 0.43s (17), Personio 0.96s (12) — the two niche sources eat 84% of the time for only
# 0.02% of hits. Off by default → 1.65s down to 0.26s per company. To include them: set DEEP_NICHE=1.
DEEP_NICHE = bool(os.environ.get("DEEP_NICHE"))

app = Flask(__name__, template_folder=os.path.join(RES_DIR, "templates"))
# Template changes take effect on browser refresh, no server restart needed (faster front-end iteration)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# Session secret key: persisted to data/ so logged-in users stay logged in across restarts
_SECRET_FILE = os.path.join(DATA_DIR, "secret.key")
if os.path.exists(_SECRET_FILE):
    with open(_SECRET_FILE, encoding="utf-8") as _f:
        app.secret_key = _f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(_SECRET_FILE, "w", encoding="utf-8") as _f:
        _f.write(app.secret_key)
app.permanent_session_lifetime = timedelta(days=30)
# Session cookie hardening. SameSite=Lax blocks cross-site form POSTs (basic CSRF
# protection for login and the API). Secure is set further down, once we know
# whether multi-user mode is on.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ---- Observability: RED metrics (Rate / Errors / Duration) --------------------------
# Records recent request latency and status codes, exposing two endpoints:
#   /stats   —— human-readable JSON: p50/p95/p99, error rate, throughput, uptime (screenshot-able evidence)
#   /metrics —— Prometheus text format: for Grafana dashboards later
_metrics_lock = threading.Lock()
_lat_samples = deque(maxlen=2000)   # latency of the last N requests (ms); ring buffer saves memory
_req_total = 0                      # total requests
_req_by_status = Counter()          # count per HTTP status code
_req_errors = 0                     # number of 5xx
_proc_start = time.time()           # process start time (for uptime)
_METRICS_SKIP = ("/stats", "/metrics", "/healthz")  # not counted themselves, to avoid polluting real traffic


@app.before_request
def _metrics_start():
    g._t0 = time.time()


@app.after_request
def _metrics_end(resp):
    global _req_total, _req_errors
    t0 = g.get("_t0")
    if t0 is not None and request.path not in _METRICS_SKIP:
        dur_ms = (time.time() - t0) * 1000.0
        with _metrics_lock:
            _lat_samples.append(dur_ms)
            _req_total += 1
            _req_by_status[resp.status_code] += 1
            if resp.status_code >= 500:
                _req_errors += 1
    return resp


def _percentile(sorted_vals, p):
    """p-th percentile of a sorted list (p=95 means p95). Returns 0 for an empty list."""
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1))))
    return sorted_vals[k]


@app.route("/stats")
def stats():
    with _metrics_lock:
        lat = sorted(_lat_samples)
        total, errors = _req_total, _req_errors
        by_status = dict(_req_by_status)
    uptime = time.time() - _proc_start
    return jsonify({
        "uptime_seconds": round(uptime),
        "requests_total": total,
        "requests_per_min": round(total / (uptime / 60), 2) if uptime > 0 else 0,
        "errors_5xx": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "latency_ms": {
            "p50": round(_percentile(lat, 50), 1),
            "p95": round(_percentile(lat, 95), 1),
            "p99": round(_percentile(lat, 99), 1),
            "max": round(lat[-1], 1) if lat else 0.0,
        },
        "by_status": by_status,
        "samples": len(lat),
    })


@app.route("/metrics")
def metrics():
    with _metrics_lock:
        lat = sorted(_lat_samples)
        total, errors = _req_total, _req_errors
    uptime = time.time() - _proc_start
    lines = [
        "# HELP jobscout_requests_total Total HTTP requests handled.",
        "# TYPE jobscout_requests_total counter",
        f"jobscout_requests_total {total}",
        "# HELP jobscout_request_errors_total HTTP 5xx responses.",
        "# TYPE jobscout_request_errors_total counter",
        f"jobscout_request_errors_total {errors}",
        "# HELP jobscout_uptime_seconds Process uptime in seconds.",
        "# TYPE jobscout_uptime_seconds gauge",
        f"jobscout_uptime_seconds {round(uptime)}",
        "# HELP jobscout_request_latency_ms Request latency percentiles in milliseconds.",
        "# TYPE jobscout_request_latency_ms gauge",
        f'jobscout_request_latency_ms{{quantile="0.5"}} {round(_percentile(lat, 50), 1)}',
        f'jobscout_request_latency_ms{{quantile="0.95"}} {round(_percentile(lat, 95), 1)}',
        f'jobscout_request_latency_ms{{quantile="0.99"}} {round(_percentile(lat, 99), 1)}',
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")


# ---- Optional login protection (for public deployment) ----------------------------------------
# ---------------------------------------------------------------- Multi-user login / registration
# Multi-user mode: enabled automatically when APP_MULTIUSER=1 is set, or HOST=0.0.0.0 (publicly exposed).
#   → login required; anyone can self-register at /register; passwords salted+hashed (pbkdf2) in data/users.json.
# Local default (HOST=127.0.0.1, APP_MULTIUSER unset) → single-user, no login, same behaviour as before.
# Open registration + your shared API key: must be paired with per-user daily usage caps (phase 3), or it gets drained.
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOCAL_USER = "local"   # default username when running locally without login
MULTIUSER = bool(os.environ.get("APP_MULTIUSER")) or os.environ.get("HOST") == "0.0.0.0"
# Open self-registration. Off by default: strangers can't register (they'd otherwise see your data and burn your API key).
# Once per-user data (phase B) + usage caps (phase C) are done, set REGISTRATION_OPEN=1 to open it.
REG_OPEN = bool(os.environ.get("REGISTRATION_OPEN"))
# Must start with a letter/digit: rejects "." / ".." (which would resolve
# data/users/<name>/ to a parent directory) and hidden-file style names.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{1,31}$")
_OPEN_PATHS = {"/login", "/register", "/logout", "/healthz"}  # paths that need no login
# Secure cookie (sent over HTTPS only): on by default in multi-user mode, which is
# meant to sit behind an HTTPS reverse proxy. Set COOKIE_SECURE=0 to test over
# plain http://<server-ip>:8080 (otherwise the browser drops the login cookie).
_cookie_secure_env = (os.environ.get("COOKIE_SECURE") or "").strip().lower()
app.config["SESSION_COOKIE_SECURE"] = (
    _cookie_secure_env not in ("0", "false", "no")
    if _cookie_secure_env else MULTIUSER)   # unset/empty -> on in multi-user mode
users = {}  # username -> {"salt","hash","created"}; plaintext passwords never hit disk
_users_lock = threading.Lock()

# ---- Per-user daily usage caps (spending guardrail) ------------------------------------------
# With open registration, every LLM call burns the owner's API key. Per-user daily quotas stop abuse.
# All overridable via env vars; owner (APP_USER) is exempt; local single-user mode is unlimited.
OWNER = os.environ.get("APP_USER") or None
LLM_DAILY_CAP = int(os.environ.get("LLM_DAILY_CAP", "100"))
SCAN_DAILY_CAP = int(os.environ.get("SCAN_DAILY_CAP", "10"))
usage = {}   # uid -> {"day": "YYYY-MM-DD", "llm": int, "scan": int}
_usage_lock = threading.Lock()


class UsageLimitError(Exception):
    """Daily quota exceeded. Turned into a 429 by the errorhandler during request handling."""


def _usage_today(uid):
    today = date.today().isoformat()
    u = usage.get(uid)
    if u is None or u.get("day") != today:
        u = {"day": today, "llm": 0, "scan": 0}
        usage[uid] = u
    return u


def _charge(kind, cap, n=1):
    """Count usage if within quota; raise UsageLimitError when over. Owner/local are not counted."""
    if not MULTIUSER:
        return
    uid = _uid()
    if OWNER and uid == OWNER:
        return
    with _usage_lock:
        u = _usage_today(uid)
        if u[kind] + n > cap:
            raise UsageLimitError(
                f"Daily {kind} limit reached ({cap}/day). Please try again tomorrow.")
        u[kind] += n


@app.errorhandler(UsageLimitError)
def _handle_usage_limit(e):
    return jsonify({"error": str(e)}), 429


def _hash_pw(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                             bytes.fromhex(salt), 200_000)
    return salt, dk.hex()


def _verify_pw(password, salt, expected_hex):
    try:
        _, got = _hash_pw(password, salt)
    except Exception:
        return False
    return hmac.compare_digest(got, expected_hex)


def _norm_user_record(v):
    """Normalise to {'salt','hash','created'}. Accepts plaintext (old users.json / env vars) → hashed on load."""
    if isinstance(v, dict) and v.get("salt") and v.get("hash"):
        return {"salt": v["salt"], "hash": v["hash"], "created": v.get("created", 0)}
    if isinstance(v, str) and v:   # plaintext password
        salt, h = _hash_pw(v)
        return {"salt": salt, "hash": h, "created": 0}
    return None


def load_users():
    """Load the account table from users.json + legacy env vars. data/ is gitignored, so credentials never enter the repo."""
    global users
    loaded = {}
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                rec = _norm_user_record(v)
                if k and rec:
                    loaded[str(k)] = rec
        except Exception:
            loaded = {}
    env_u = os.environ.get("APP_USER", "")
    env_p = os.environ.get("APP_PASSWORD", "")
    if env_u and env_p and env_u not in loaded:   # backward compat with the old single-account env vars
        salt, h = _hash_pw(env_p)
        loaded[env_u] = {"salt": salt, "hash": h, "created": 0}
    users = loaded


def save_users():
    with _users_lock:
        payload = json.dumps(users, ensure_ascii=False, indent=2)
    _atomic_write(USERS_FILE, payload)


def create_user(name, password):
    """Create an account, returning (ok, error message). Username validation + password length + dedup."""
    name = (name or "").strip()
    if not _USERNAME_RE.match(name):
        return False, "Username must be 2–32 characters: letters, digits, or _ . -"
    if len((password or "")) < 6:
        return False, "Password must be at least 6 characters"
    with _users_lock:
        if name in users:
            return False, "That username is already taken"
        salt, h = _hash_pw(password)
        users[name] = {"salt": salt, "hash": h, "created": int(time.time())}
    save_users()
    return True, ""


def _bind_user(uid):
    """Bind this request to a user: load their data + set the context (used by state[...] routing)."""
    g.user = uid
    ensure_user(uid)
    _ctx_user.set(uid)


def _is_admin():
    """May the current user change state shared by every account (company
    directory, hiring-system overrides and probe cache)? Always true in local
    single-user mode; in multi-user mode only the owner account (APP_USER)."""
    if not MULTIUSER:
        return True
    return bool(OWNER) and _uid() == OWNER


def _admin_only():
    """Return a 403 response for non-owners, or None when allowed."""
    if _is_admin():
        return None
    return jsonify({"error": "Only the owner account (APP_USER) can change the "
                             "shared company list or hiring-system settings."}), 403


@app.before_request
def _require_login():
    # Reset context at the start of each request so a reused worker thread can't leak the previous request's user
    _ctx_user.set(None)
    if not MULTIUSER:
        _bind_user(LOCAL_USER)   # local single-user mode, no login
        return
    p = request.path
    if p in _OPEN_PATHS or p.startswith("/static/"):
        return  # these paths never touch state; context stays None
    user = session.get("user")
    if user and user in users:
        _bind_user(user)
        return
    # Not logged in: page navigation redirects to login, front-end fetch gets 401 (so login HTML isn't parsed as JSON)
    if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
        return redirect(url_for("login_page", next=p))
    return jsonify({"error": "not logged in"}), 401


# ---- Login throttling -------------------------------------------------------
# Failed logins are counted per (client IP, username). Keying on the username as
# well means that behind a reverse proxy (where every request shares the proxy's
# IP) one attacker cannot lock everybody out, while guessing one account's
# password is still capped.
LOGIN_MAX_FAILS = int(os.environ.get("LOGIN_MAX_FAILS", "10"))
LOGIN_WINDOW_SEC = int(os.environ.get("LOGIN_WINDOW_SEC", "900"))
_login_fails = {}   # (ip, username) -> timestamps of recent failures
_login_lock = threading.Lock()


def _login_key(name):
    return (request.remote_addr or "?", (name or "").lower())


def _login_blocked(key):
    now = time.time()
    with _login_lock:
        recent = [t for t in _login_fails.get(key, []) if now - t < LOGIN_WINDOW_SEC]
        if recent:
            _login_fails[key] = recent
        else:
            _login_fails.pop(key, None)
        return len(recent) >= LOGIN_MAX_FAILS


def _login_failed(key):
    with _login_lock:
        _login_fails.setdefault(key, []).append(time.time())


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if not MULTIUSER:
        return redirect("/")
    error = ""
    status = 200
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if request.method == "POST":
        name = (request.form.get("username") or "").strip()
        key = _login_key(name)
        if _login_blocked(key):
            error = "Too many failed attempts. Please wait a few minutes and try again."
            status = 429
        else:
            rec = users.get(name)
            if rec and _verify_pw(request.form.get("password") or "",
                                  rec["salt"], rec["hash"]):
                with _login_lock:
                    _login_fails.pop(key, None)
                session.permanent = True
                session["user"] = name
                return redirect(nxt)
            _login_failed(key)
            error = "Incorrect username or password"
    return render_template("login.html", mode="login", error=error,
                           next=nxt, reg_open=REG_OPEN), status


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if not MULTIUSER:
        return redirect("/")
    if not REG_OPEN:
        return redirect(url_for("login_page"))  # registration not open → back to login page
    error = ""
    if request.method == "POST":
        name = (request.form.get("username") or "").strip()
        pw = request.form.get("password") or ""
        if pw != (request.form.get("password2") or ""):
            error = "The two passwords don't match"
        else:
            ok, msg = create_user(name, pw)
            if ok:
                session.permanent = True
                session["user"] = name
                return redirect("/")
            error = msg
    return render_template("login.html", mode="register", error=error,
                           next="/", reg_open=REG_OPEN)


@app.route("/logout")
def logout_page():
    session.pop("user", None)
    return redirect(url_for("login_page"))

# ---------------------------------------------------------------- state (multi-tenant)
# Each user gets an independent state (resume/jobs/matches/applications… all separate).
# `state` is a proxy routed by "current user": every state[...] access lands on the current user's data.
# The current user comes from contextvars — request threads set it in before_request, background threads at their entry point.
# The company master directory (incl. 120k sponsors) is one object shared by all users, avoiding duplicate memory/disk.
_lock = threading.Lock()                 # guards state writes (global coarse-grained lock, good enough)
_states_lock = threading.Lock()          # guards the user_states dict itself
user_states = {}                         # uid -> that user's state dict
_shared_companies = {}                   # company master directory: one object shared by all users
_ctx_user = contextvars.ContextVar("ctx_user", default=None)


def _uid():
    """Current context user; falls back to LOCAL_USER when unset (local single-user / no-login paths)."""
    return _ctx_user.get() or LOCAL_USER


def blank_state():
    """A fresh user state. companies points at the shared directory (same object, not a copy of 120k entries)."""
    return {
        "companies": _shared_companies,   # shared reference (all users share one company directory)
        "keywords": list(DEFAULT_KEYWORDS),
        "exclude_keywords": [],  # hide when the title matches (e.g. sales / frontend / qa)
        "target_titles": [],     # target job titles (empty = use DEFAULT_TARGET_TITLES)
        "acceptable_titles": [], # acceptable job titles (empty = use DEFAULT_ACCEPTABLE_TITLES)
        "uk_only": True,
        "auto_hours": 0,   # >0: background quick refresh every N hours
        "results": {},     # name -> result (only companies with a detected board + curated ones)
        "jobs_seen": {},   # job_url -> {"first_seen","last_seen"}
        "scan": {"running": False, "done": 0, "total": 0, "mode": None,
                 "started_ts": 0, "stop": False, "new_jobs": 0},
        "last_auto": 0,
        "resume": None,        # {"text","keywords","updated","name"}
        "match_scores": {},    # job_url -> {"score","hit","must_miss","nice_miss","flags","n"}
        "match": {"running": False, "done": 0, "total": 0},
        "match_stats": {},     # JD fetch coverage: {"jd_ok","jd_fail","updated"}
        "exp_years": 1,        # my years of experience (for the experience-threshold check)
        "agg_jobs": {},        # aggregator (Adzuna/Reed) / social hiring-post jobs: url -> {...}
        "agg": {"running": False, "done": 0, "total": 0},
        "social": {"running": False, "done": 0, "total": 0},  # social hiring-post (HN) fetch progress
        "tracker": {},         # application tracker: job_url -> {"status","ts","title","company","location"}
        "size": {"running": False, "done": 0, "total": 0},  # company size detection progress
        "hidden": {},          # jobs hidden manually by the user: url -> {"ts","title"}
        "advice": {},          # per-job resume advice cache: url -> markdown (survives page refresh, no repeat LLM cost)
        "outreach": {},        # networking draft cache: url -> markdown
    }


def ensure_user(uid):
    """Ensure this user's state is in memory (lazy-loaded from disk on first access). Returns its state dict."""
    with _states_lock:
        st = user_states.get(uid)
        if st is not None:
            return st
    st = blank_state()          # build + read disk outside the lock so other threads never see a half-built state
    load_user_state(uid, st)
    with _states_lock:
        existing = user_states.get(uid)
        if existing is not None:  # race: another thread already built it, use theirs
            return existing
        user_states[uid] = st
        return st


class _StateProxy:
    """Makes the global name `state` mean "the current user's state". Only needs __getitem__/__setitem__/get."""
    def _d(self):
        uid = _uid()
        st = user_states.get(uid)
        return st if st is not None else ensure_user(uid)

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def get(self, k, default=None):
        return self._d().get(k, default)


state = _StateProxy()


def _spawn(fn, *args):
    """Start a background thread with the "current user" bound into the new thread's context.
    New threads don't inherit contextvars, so capture + set explicitly to avoid running on someone else's data."""
    u = _uid()

    def runner():
        _ctx_user.set(u)
        fn(*args)

    threading.Thread(target=runner, daemon=True).start()


# name -> {"ats","slug"}: ATS found
#       | "none"      : regular probe found nothing (deep rescan will retry it)
#       | "none_deep" : deep rescan also probed and confirmed none (not rescanned → stop and resume works)
ats_cache = {}
_NO_ATS = ("none", "none_deep")   # both mean "no job board"
# Guards ats_cache: 32~48 worker threads write it concurrently during scans, so snapshot inside the lock before saving,
# otherwise json.dump iterates while it's mutated → RuntimeError kills the scan thread (shows up as a "crash").
_ats_lock = threading.Lock()


def _ats_set(name, value):
    with _ats_lock:
        ats_cache[name] = value


def _ats_pop(name):
    with _ats_lock:
        ats_cache.pop(name, None)
company_sizes = {}  # company name -> {"band": startup|mid|large|unknown, "note": str}
api_keys = {}   # {"adzuna_app_id","adzuna_app_key","reed_api_key"}
slug_overrides = {}  # name.lower() -> {"ats","slug"}: manual fixes for key companies whose slug was guessed wrong


def _valid_override(v):
    """Whether a manual override is usable. Workday is located by host+site, other ATSs by slug."""
    if not v.get("ats"):
        return False
    if v["ats"] == "Workday":
        return bool(v.get("host") and v.get("site"))
    return bool(v.get("slug"))


def _user_dir(uid):
    d = os.path.join(DATA_DIR, "users", uid)
    os.makedirs(d, exist_ok=True)
    return d


def _user_state_file(uid):
    return os.path.join(_user_dir(uid), "state.json")


def load_all():
    """On startup, load data shared by all users: probe cache + company master directory. Per-user state is lazy-loaded."""
    global ats_cache, slug_overrides, api_keys, company_sizes
    if os.path.exists(COMPANY_SIZE_FILE):
        try:
            with open(COMPANY_SIZE_FILE, encoding="utf-8") as f:
                company_sizes = json.load(f)
        except Exception:
            company_sizes = {}
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
                              if isinstance(v, dict) and _valid_override(v)}
        except Exception:
            slug_overrides = {}
    # Company master directory (shared): fill _shared_companies in place so references in blank_state stay valid
    if os.path.exists(COMPANIES_FILE):
        try:
            with open(COMPANIES_FILE, encoding="utf-8") as f:
                _shared_companies.update(json.load(f))
        except Exception:
            pass
    migrate_legacy_state()


def migrate_legacy_state():
    """Migrate the old single-tenant data/state.json into the owner account's per-user state (once only).
    companies from the old file are merged into the shared directory. The original is kept as a backup, not deleted."""
    if not os.path.exists(STATE_FILE):
        return
    owner = os.environ.get("APP_USER") or LOCAL_USER
    dest = _user_state_file(owner)
    if os.path.exists(dest):
        return  # already migrated
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        return
    comps = saved.pop("companies", {})
    if isinstance(comps, list):  # even older format: what was imported then was the curated list
        comps = {c["name"]: {"tags": ["curated"], "town": ""} for c in comps}
    for k, v in (comps or {}).items():
        _shared_companies.setdefault(k, v)
    _atomic_write(dest, json.dumps(saved, ensure_ascii=False))


def load_user_state(uid, st):
    """Load a user's per-user state.json into st (companies aren't in this file; they're shared)."""
    path = _user_state_file(uid)
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        return
    st["keywords"] = saved.get("keywords", list(DEFAULT_KEYWORDS))
    st["exclude_keywords"] = saved.get("exclude_keywords", [])
    st["target_titles"] = saved.get("target_titles", [])
    st["acceptable_titles"] = saved.get("acceptable_titles", [])
    st["uk_only"] = saved.get("uk_only", True)
    st["auto_hours"] = saved.get("auto_hours", 0)
    st["jobs_seen"] = saved.get("jobs_seen", {})
    st["resume"] = saved.get("resume")
    st["match_scores"] = saved.get("match_scores", {})
    st["match_stats"] = saved.get("match_stats", {})
    st["agg_jobs"] = saved.get("agg_jobs", {})
    st["exp_years"] = saved.get("exp_years", 1)
    st["tracker"] = saved.get("tracker", {})
    st["hidden"] = saved.get("hidden", {})
    st["advice"] = saved.get("advice", {})
    st["outreach"] = saved.get("outreach", {})
    for name, r in saved.get("results", {}).items():
        r.pop("links", None)  # old versions saved links to disk; now generated on demand
        st["results"][name] = r


def _atomic_write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, path)


def save_companies():
    """Company list is stored separately (120k entries only change on import), so scans don't keep rewriting a big file.
    Caller must not hold the lock."""
    with _lock:
        payload = json.dumps(state["companies"], ensure_ascii=False)
    _atomic_write(COMPANIES_FILE, payload)


def save_state():
    """Save the "current user's" state to data/users/<uid>/state.json.
    Serialise inside the lock (results/jobs_seen are small), write to disk outside it. Caller must not hold the lock.
    companies is shared and saved separately by save_companies(), not in this file."""
    dest = _user_state_file(_uid())
    with _lock:
        payload = json.dumps({
            "keywords": state["keywords"],
            "exclude_keywords": state["exclude_keywords"],
            "target_titles": state["target_titles"],
            "acceptable_titles": state["acceptable_titles"],
            "uk_only": state["uk_only"],
            "auto_hours": state["auto_hours"],
            "results": state["results"],
            "jobs_seen": state["jobs_seen"],
            "resume": state["resume"],
            "match_scores": state["match_scores"],
            "match_stats": state["match_stats"],
            "agg_jobs": state["agg_jobs"],
            "exp_years": state["exp_years"],
            "tracker": state["tracker"],
            "hidden": state["hidden"],
            "advice": state["advice"],
            "outreach": state["outreach"],
        }, ensure_ascii=False)
    _atomic_write(dest, payload)


def save_ats_cache():
    """Snapshot inside lock → serialise outside lock → atomic write. Caller must not hold _ats_lock.

    Fixes two real incidents:
    ① Previously json.dump(ats_cache, f) directly: 32 scan threads writing while serialisation iterated →
       RuntimeError: dictionary changed size during iteration, killing the run_scan thread
       on the spot (in the UI the scan just "crashed").
    ② Previously wrote in place with open(...,"w"): the file is truncated first, so a crash midway left the whole
       probe cache corrupted; load_all() silently treats a parse failure as empty → full rescan of 120k. With atomic writes,
       only the temp file can be corrupted; the original always stays intact.
    """
    with _ats_lock:
        snap = dict(ats_cache)      # only snapshot inside the lock (C-level copy, very fast)
    _atomic_write(ATS_CACHE_FILE, json.dumps(snap, ensure_ascii=False))


# ---------------------------------------------------------------- slug generation
STRIP_SUFFIXES = [
    "ltd", "limited", "plc", "llp", "inc", "uk", "group", "holdings",
    "international", "technologies", "technology", "labs", "lab", "co",
]


def slug_candidates(name):
    base = name.lower().strip()
    base = re.sub(r"t/a.*$", " ", base)  # strip trading-as aliases
    base = re.sub(r"[&+]", " and ", base)
    base = re.sub(r"[^a-z0-9\s-]", "", base)
    words = [w for w in base.split() if w]
    trimmed = list(words)
    while len(trimmed) > 1 and trimmed[-1] in STRIP_SUFFIXES:
        trimmed.pop()
    # only try the highest-hit-rate forms, to keep full-sweep request volume down
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


# ---------------------------------------------------------------- ATS probing
_tls = threading.local()


def _session():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
        _tls.s.headers.update(HEADERS)
    return _tls.s


class RateLimited(Exception):
    """Remote side is rate-limited / temporarily unavailable; don't record the company as none, or it's missed forever."""


# Global stop switch for scans. During a deep rescan, in-flight tasks can sit in the Workable semaphore queue / backoff sleep
# for tens of seconds to minutes; checking state["scan"]["stop"] in run_scan's main loop alone can't stop them —
# every slow step (gaps between probes, semaphore waits, backoff) must be interruptible by this event within seconds.
_stop_event = threading.Event()   # fallback only: never set by the API
_scan_stops = {}                  # uid -> stop Event of that user's running scan


def _cur_stop():
    """The stop event of the scan running on this thread. Each scan gets its own
    event (bound to its worker threads in run_scan), so one user pressing Stop
    never halts another user's scan."""
    return getattr(_tls, "stop", None) or _stop_event


# Monitoring of recent rate-limit (429/503) counts — observability only (_recent_rl for diagnostics / future metrics).
# Note: since the all-source speedup, "hit the cap → global 5-minute cooldown" is gone; 429s use per-probe backoff self-throttling.
_rl_lock = threading.Lock()
_rl_hits = []          # timestamps of recent 429/503s
RL_WINDOW = 120        # stats window (seconds)


def _note_rate_limit():
    now = time.time()
    with _rl_lock:
        _rl_hits.append(now)
        cutoff = now - RL_WINDOW
        while _rl_hits and _rl_hits[0] < cutoff:
            _rl_hits.pop(0)


def _recent_rl():
    now = time.time()
    with _rl_lock:
        return sum(1 for t in _rl_hits if t >= now - RL_WINDOW)


def _get_json(url):
    r = _session().get(url, timeout=TIMEOUT)
    if r.status_code in (429, 503):
        _note_rate_limit()
        raise RateLimited(url)
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
    """Greenhouse's basic list has no JD; content=true fetches the full text of every job at the company in one go.
    Only called when there are "wide-net candidates", so at most one extra request per company."""
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
        "desc": _lever_desc(j),  # Lever's list API includes the JD, so the second check is free
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


_WORKABLE_SEM = threading.BoundedSemaphore(WORKABLE_CONC)


def probe_workable(slug):
    # Workable rate-limits hardest: ① a global concurrency gate caps simultaneous probes; ② 429s are retried with backoff, not dropped,
    # so the deep rescan eventually finishes (backoff holds a slot → automatic slow-down and self-healing). Only affects deep rescans,
    # not the full hot path, so the first full sweep isn't slowed by it.
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    # while waiting for a slot, check the stop switch every 0.5s; stop is treated as RateLimited → no none cache entry
    stop = _cur_stop()
    while not _WORKABLE_SEM.acquire(timeout=0.5):
        if stop.is_set():
            raise RateLimited(url)
    try:
        data = None
        for attempt in range(4):
            try:
                data = _get_json(url)
                break
            except RateLimited:
                if attempt == 3:
                    raise                       # still rate-limited after 4 tries → don't record none this round, retry next round
                # backoff: 1.5s, 3s, 6s; give up at once if stopped meanwhile (wait returns True = event set)
                if stop.wait(1.5 * (2 ** attempt)):
                    raise RateLimited(url)
    finally:
        _WORKABLE_SEM.release()
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
    # SmartRecruiters returns 200 + an empty list even for non-existent companies, so treat empty results as a miss
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
    # Personio gives each company a public XML job feed that includes the full text (second check is free)
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
    """Anonymous API of Workday public career sites. host like nvidia.wd5.myworkdayjobs.com,
    site like NVIDIAExternalCareerSite. Only configurable via manual override (can't be guessed from the company name)."""
    if not host or not site:
        return None
    tenant = host.split(".")[0]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    jobs, offset = [], 0
    try:
        while offset < 200:  # fetch at most 200, so huge sites don't slow things down
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
                })  # Workday's list has no full text → judge by title only
            total = d.get("total") or 0
            offset += 20
            if not batch or offset >= total:
                break
    except Exception:
        return None
    if not jobs:
        return None
    return {"board_url": f"https://{host}/en-US/{site}", "jobs": jobs}


# Healthy fast probes: shared domains, fast and not rate-limited — the full sweep runs only these by default and actually finishes
FAST_PROBES = [
    ("Greenhouse", probe_greenhouse),
    ("Lever", probe_lever),
    ("Ashby", probe_ashby),
    ("SmartRecruiters", probe_smartrecruiters),
]
# Workable: most hits (273 companies) but harshest rate limiting; on the hot path it would 429 en masse and the sweep would never finish.
# Moved to the "deep rescan" (mode=deep), throttled with _WORKABLE_SEM so it doesn't drag down the main scan.
WORKABLE_PROBES = [("Workable", probe_workable)]
# Slow probes: Recruitee/Personio use per-company subdomains, so each non-existent company costs a doomed
# DNS+handshake (measured ~3.7s each), with very few hits (Recruitee 8, Personio 0). Also moved to the deep rescan.
EXTRA_PROBES = [
    ("Recruitee", probe_recruitee),
    ("Personio", probe_personio),
]
PROBES = FAST_PROBES                             # default hot path (pending/all/known)
CORE_PROBES = FAST_PROBES + WORKABLE_PROBES      # small curated list: include Workable (small volume, rate limits don't matter)
# Deep rescan: Workable only by default (~6x faster, and still gets 93% of the deep rescan's yield).
# Set DEEP_NICHE=1 to add back the niche Recruitee/Personio sources (much slower, finds ~0.02% more).
DEEP_PROBES = WORKABLE_PROBES + (EXTRA_PROBES if DEEP_NICHE else [])
ALL_PROBES = CORE_PROBES + EXTRA_PROBES
PROBE_FN = dict(ALL_PROBES)       # cache hits / manual override lookups still need to know every ATS
# Workday takes no part in guessing slugs from company names (needs host+site); manual override only
OVERRIDE_ATS = set(PROBE_FN) | {"Workday"}

# Preset Workday career sites (host, site) for big employers. These use Workday/in-house systems, so guessing
# the slug from the name fails; the built-in host/site hit their public job API directly. Best-effort:
#   · a failed probe has no side effects — find_ats falls back to regular probing;
#   · if host/site change later, fix them via "Manual fix" in the web UI (written to data/slug_overrides.json, overriding the built-ins).
# Note: Google / Amazon / Meta / Microsoft / Morgan etc. use **in-house** hiring systems (not Workday),
# with no public API to scrape; check them manually via the "Google direct / LinkedIn search" links on the company card.
BUILTIN_WORKDAY = {
    "NVIDIA": ("nvidia.wd5.myworkdayjobs.com", "NVIDIAExternalCareerSite"),
    "Salesforce": ("salesforce.wd12.myworkdayjobs.com", "External_Career_Site"),
    "Adobe": ("adobe.wd5.myworkdayjobs.com", "external_experienced"),
    "Dell Technologies": ("dell.wd1.myworkdayjobs.com", "External"),
    "Mastercard": ("mastercard.wd1.myworkdayjobs.com", "CorporateCareers"),
    "Capital One": ("capitalone.wd1.myworkdayjobs.com", "Capital_One"),
    "Autodesk": ("autodesk.wd1.myworkdayjobs.com", "Ext"),
    "AstraZeneca": ("astrazeneca.wd3.myworkdayjobs.com", "Careers"),
    "Sanofi": ("sanofi.wd3.myworkdayjobs.com", "SanofiCareers"),
    "Workday": ("workday.wd5.myworkdayjobs.com", "Workday"),
}
BUILTIN_OVERRIDES = {name.lower(): {"ats": "Workday", "host": host, "site": site}
                     for name, (host, site) in BUILTIN_WORKDAY.items()}

# Preset well-known AI/ML/fintech employers as curated company seeds. Most use Greenhouse/Lever/
# Ashby and other auto-detectable systems, so slugs are detected once added; any not found show as "no job board",
# reminding you to check manually. (All hire in the UK and often sponsor visas.)
CURATED_SEED = [
    "Anthropic", "OpenAI", "Cohere", "Hugging Face", "DeepMind", "Databricks",
    "Palantir Technologies", "Wayve", "Faculty", "Quantexa", "Synthesia",
    "Stability AI", "ElevenLabs", "PolyAI", "Speechmatics", "Graphcore",
    "Monzo", "Wise", "Revolut", "Improbable",
] + list(BUILTIN_WORKDAY)


def seed_builtin_companies():
    """Add preset big-name/AI employers to the company list (curated) so they get scanned; Workday ones also hit the built-in overrides."""
    changed = False
    with _lock:
        existing = {n.strip().lower() for n in state["companies"]}
        for name in CURATED_SEED:
            if name.strip().lower() not in existing:
                state["companies"][name] = {"tags": ["curated"], "town": ""}
                existing.add(name.strip().lower())
                changed = True
    if changed:
        save_companies()


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


def find_ats(name, probes=PROBES, max_slugs=SWEEP_SLUGS, force=False):
    """Return (ats_name, slug, {board_url, jobs}) or None. Results are written to ats_cache.
    probes/max_slugs depend on the scan mode; force=True ignores the 'none' cache (for deep rescans).
    Probes run sequentially in the calling thread — reusing its keep-alive connections (several times faster than
    a new thread pool per company with a fresh TLS handshake per request)."""
    key = (name or "").strip().lower()
    ov = slug_overrides.get(key) or BUILTIN_OVERRIDES.get(key)  # user overrides first, then built-in big employers
    if ov:
        res = _probe_override(ov)
        if res:  # manual override first; fall back to auto-probing if it finds nothing
            return (ov["ats"], ov.get("slug") or ov.get("site") or "", res)
    cached = ats_cache.get(name)
    if cached in _NO_ATS and not force:
        return None
    if isinstance(cached, dict):
        try:
            res = PROBE_FN[cached["ats"]](cached["slug"])
        except Exception:
            res = None
        if res:
            return (cached["ats"], cached["slug"], res)
        # cache invalid, re-probe

    stop = _cur_stop()
    fallback = None  # an empty account with 0 jobs may be a same-name shell account; fallback only
    rate_limited = False  # rate-limited probes count as "unknown", not "none"
    for slug in slug_candidates(name)[:max_slugs]:
        for ats_name, fn in probes:
            if stop.is_set():
                rate_limited = True  # aborted midway counts as "unknown"; don't write a none cache entry
                break
            try:
                res = fn(slug)
            except RateLimited:
                rate_limited = True
                res = None
            except Exception:
                res = None
            if res:
                if res["jobs"]:
                    _ats_set(name, {"ats": ats_name, "slug": slug})
                    return (ats_name, slug, res)
                if fallback is None:
                    fallback = (ats_name, slug, res)
        if stop.is_set():
            break
    if fallback:
        _ats_set(name, {"ats": fallback[0], "slug": fallback[1]})
        return fallback
    if not rate_limited:  # don't write the cache when rate-limited/stopped midway; resuming will re-probe this company
        # Not found even by the deep rescan (force=True) → record none_deep, so the next deep rescan skips it.
        # So "stop halfway, resume tomorrow" doesn't restart from scratch (regular probes still record none, left for the deep rescan).
        _ats_set(name, "none_deep" if force else "none")
    return None


# ---------------------------------------------------------------- matching


def build_links(name):
    q = quote_plus(name)
    # One-click job search keywords follow the current user's own industry, not hardcoded AI — in multi-user mode
    # each account (you search AI, a friend searches finance/construction) gets search links for their own field.
    kws = [k for k in (state.get("keywords") or []) if k][:3]
    li_terms = " ".join(kws) if kws else "jobs"
    g_role = (" OR ".join(f'"{k}"' for k in kws)) if kws else ""
    g_query = f'"{name}" ({g_role}) job UK' if g_role else f'"{name}" jobs UK'
    return {
        "li_people": ("https://www.linkedin.com/search/results/people/?keywords="
                      + quote_plus(f'"{name}" (recruiter OR "talent acquisition" OR "hiring manager" OR "engineering manager")')),
        "li_jobs_kw": ("https://www.linkedin.com/jobs/search/?keywords="
                       + quote_plus(f"{name} {li_terms}") + "&location=United%20Kingdom"),
        "google": ("https://www.google.com/search?q=" + quote_plus(g_query)),
        "hunter": f"https://hunter.io/search/{q}",
        "careers_google": ("https://www.google.com/search?q="
                           + quote_plus(f"{name} careers jobs")),
    }


# ---------------------------------------------------------------- scanning
def scan_company(name, keywords, uk_only, probes=PROBES, max_slugs=SWEEP_SLUGS,
                 force=False):
    result = {
        "name": name,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ats": None, "slug": None, "board_url": None,
        "total_jobs": 0, "matched": [],
        "status": "no_board",
    }
    hit = find_ats(name, probes, max_slugs, force)
    if hit:
        ats_name, slug, res = hit
        result["ats"] = ats_name
        result["slug"] = slug
        result["board_url"] = res["board_url"]
        result["total_jobs"] = len(res["jobs"])
        matched = []
        gh_bodies = None  # Greenhouse full text fetched once, on demand
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
                continue  # exclude US/Asia etc.; keep UK + Europe + Remote
            j.pop("desc", None)  # JD text isn't stored here; resume matching saves it separately in desc_cache
            j["region"] = region
            j["country"] = rlabel
            j["level"] = classify_level(title)
            j["llm"] = kw_match(title, LLM_KEYWORDS) or bool(
                body and kw_match(body.lower(), LLM_KEYWORDS))
            j["via"] = via  # title = matched on title / jd = matched on body (title doesn't mention AI)
            matched.append(j)
        result["matched"] = matched[:80]
        if matched:
            result["status"] = "has_ai"
        elif res["jobs"]:
            result["status"] = "board_no_ai"
        else:
            result["status"] = "no_board"  # empty shell account
    return result


def _curated_names():
    return {n for n, c in state["companies"].items() if "curated" in c.get("tags", [])}


def _record_result(name, res, today, curated):
    """Call while holding the lock: record first-seen/last-seen dates for jobs, storing them as needed."""
    for j in res.get("matched", []):
        seen = state["jobs_seen"].setdefault(j["url"], {"first_seen": today})
        seen["last_seen"] = today
        j["first_seen"] = seen["first_seen"]
        if seen["first_seen"] == today:
            state["scan"]["new_jobs"] += 1
    if res["status"] == "no_board" and name not in curated:
        state["results"].pop(name, None)  # register companies without a job board take up no space
    else:
        state["results"][name] = res


def run_scan(names, mode):
    keywords = [k.lower() for k in state["keywords"]]
    uk_only = state["uk_only"]
    curated = _curated_names()
    today = date.today().isoformat()
    # Deep rescan: re-run rate-limited/slow probes (Workable+Recruitee+Personio) on companies marked none; must bypass the none cache.
    # All-source speedup: keep Workable (no coverage loss); speed comes from higher Workable concurrency + more threads + single slug,
    # 429s are left to probe_workable's per-probe backoff self-throttling (the global 5-minute cooldown is gone, see main loop).
    if mode == "deep":
        probes, force, max_slugs, workers = DEEP_PROBES, True, DEEP_SLUGS, DEEP_WORKERS
    elif mode == "curated":       # curated list is small; include Workable
        probes, force, max_slugs, workers = CORE_PROBES, False, SWEEP_SLUGS, SCAN_WORKERS
    else:                         # pending / all / known: healthy fast probes only
        probes, force, max_slugs, workers = PROBES, False, SWEEP_SLUGS, SCAN_WORKERS
    state["scan"] = {"running": True, "done": 0, "total": len(names), "mode": mode,
                     "started_ts": time.time(), "stop": False, "new_jobs": 0,
                     "paused_until": 0}
    stop_ev = threading.Event()        # this scan's own stop signal
    _scan_stops[_uid()] = stop_ev
    processed = 0

    def scan_one(*args):
        _tls.stop = stop_ev            # bind the stop signal to the worker thread
        return scan_company(*args)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            it = iter(names)
            futures = {}
            # buffer only slightly above concurrency — fewer in-flight tasks to discard on "stop", so it stops fast
            buf = workers * 2

            def submit_more():
                while len(futures) < buf:
                    try:
                        n = next(it)
                    except StopIteration:
                        return
                    futures[pool.submit(scan_one, n, keywords, uk_only,
                                        probes, max_slugs, force)] = n

            submit_more()
            while futures:
                # poll with a timeout: during a deep rescan, in-flight tasks may go tens of seconds without any "completing";
                # without a timeout the stop flag would only be checked once some task finishes
                done_set, _ = wait(list(futures), timeout=2,
                                   return_when=FIRST_COMPLETED)
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
                if state["scan"]["stop"]:
                    pool.shutdown(wait=False, cancel_futures=True)  # cancel anything still queued, stop immediately
                    break
                # All-source speedup: recent 429s no longer trigger a global 5-minute cooldown — 429s are handled by probe_workable's per-probe
                # backoff (1.5/3/6s, 4 tries) in place, holding up only the affected probes instead of freezing the whole scan.
                submit_more()
    finally:
        state["scan"]["running"] = False
        if _scan_stops.get(_uid()) is stop_ev:
            _scan_stops.pop(_uid(), None)
        save_ats_cache()
        save_state()
        # after a scan, recompute match scores automatically (if a resume exists), so new jobs don't need a manual "compute match"
        if state.get("resume") and not state["match"]["running"]:
            _spawn(run_match)


def start_scan(mode):
    """mode: curated / known / pending / deep / all"""
    if state["scan"]["running"]:
        return None
    comps = state["companies"]
    curated = _curated_names()
    if mode == "curated":
        names = sorted(curated)
    elif mode == "known":   # companies with a detected ATS: quick refresh of the latest jobs
        names = [n for n in comps if isinstance(ats_cache.get(n), dict)]
    elif mode == "pending":  # companies not probed yet: full sweep (interruptible and resumable)
        names = [n for n in comps if n not in ats_cache]
    elif mode == "deep":    # deep rescan: retry slow probes (Recruitee/Personio) on companies marked none
        # only pick "none" entries not yet deep-probed; confirmed ones are none_deep and deliberately excluded → resumable
        names = [n for n in comps if ats_cache.get(n) == "none"]
    else:  # all
        known = [n for n in comps if isinstance(ats_cache.get(n), dict)]
        pending = [n for n in comps if n not in ats_cache]
        names = sorted(curated) + [n for n in known if n not in curated] + pending
    if not names:
        return 0
    _charge("scan", SCAN_DAILY_CAP)   # charge the daily scan quota (raises UsageLimitError when over)
    _spawn(run_scan, names, mode)
    return len(names)


def auto_loop():
    """When auto_hours>0, periodically quick-refresh known ATSs to catch new jobs as early as possible.
    Multi-tenant: checks each user's own auto_hours (only users currently in memory;
    after a restart, a user's first login loads them back into memory and their timer resumes)."""
    while True:
        time.sleep(300)
        for uid in list(user_states.keys()):
            try:
                _ctx_user.set(uid)   # switch the context to this user; state[...] is now their data
                h = state["auto_hours"]
                if h > 0 and not state["scan"]["running"] \
                        and time.time() - state["last_auto"] > h * 3600:
                    if start_scan("known"):   # the internal _spawn captures the current uid
                        state["last_auto"] = time.time()
            except Exception:
                pass


# ---------------------------------------------------------------- aggregator search
# Adzuna / Reed are keyword aggregators: a few calls sweep jobs from every UK company/ATS,
# the biggest lever for "most complete + fastest". Each needs its own free official API key (in data/api_keys.json).
# Search terms follow the user's job keywords (works for nursing/accounting too); the free APIs have quotas,
# so at most the first N keywords are used per round.
AGG_MAX_QUERIES = 6

AGG_KEY_FIELDS = ("adzuna_app_id", "reed_api_key", "jooble_api_key", "rapidapi_key")


def _has_agg_keys():
    return any(api_keys.get(k) for k in AGG_KEY_FIELDS)


def _norm_company(n):
    """Normalise company names, for cross-checking aggregator jobs against the official sponsor register."""
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


def search_jooble(query):
    """Jooble aggregates many job sites (including some LinkedIn/Indeed reposts). Free key, called via POST."""
    key = api_keys.get("jooble_api_key")
    if not key:
        return []
    try:
        r = _session().post(f"https://jooble.org/api/{key}",
                            json={"keywords": query, "location": "United Kingdom"},
                            timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        res = r.json().get("jobs") or []
    except Exception:
        return []
    return [{
        "company": j.get("company", ""), "title": j.get("title", ""),
        "url": j.get("link", ""), "location": j.get("location", ""),
        "desc": _strip_html(j.get("snippet", "")), "source": "Jooble",
    } for j in res]


def search_jsearch(query):
    """JSearch (RapidAPI) scrapes Google for Jobs — covering LinkedIn/Indeed/Glassdoor/ZipRecruiter,
    exactly the biggest blind spot of this tool's official ATS scanning. Free tier is about 200 calls a month."""
    key = api_keys.get("rapidapi_key")
    if not key:
        return []
    try:
        r = _session().get("https://jsearch.p.rapidapi.com/search",
                          params={"query": f"{query} in United Kingdom",
                                  "page": "1", "num_pages": "1", "country": "gb"},
                          headers={"X-RapidAPI-Key": key,
                                   "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
                          timeout=(4, 20))
        if r.status_code != 200:
            return []
        res = r.json().get("data") or []
    except Exception:
        return []
    out = []
    for j in res:
        loc = ", ".join(x for x in (j.get("job_city"), j.get("job_country")) if x)
        out.append({
            "company": j.get("employer_name", ""), "title": j.get("job_title", ""),
            "url": j.get("job_apply_link") or j.get("job_google_link", ""),
            "location": loc, "desc": _strip_html(j.get("job_description", "")),
            "source": j.get("job_publisher") or "JSearch",
        })
    return out


def run_aggregators():
    """Run Adzuna+Reed keyword searches, AI-filter, merge into agg_jobs, and flag whether each is a visa sponsor."""
    if not _has_agg_keys():
        return
    kws = [k.lower() for k in state["keywords"]]
    queries = kws[:AGG_MAX_QUERIES]  # follow the user's keywords instead of hardcoded AI terms
    today = date.today().isoformat()
    with _lock:
        sponsor_idx = {_norm_company(n) for n in state["companies"]}
    state["agg"] = {"running": True, "done": 0, "total": len(queries)}
    new_descs = {}  # url -> JD summary, saved into desc_cache for resume match scoring
    try:
        for q in queries:
            found = (search_adzuna(q) + search_reed(q)
                     + search_jooble(q) + search_jsearch(q))
            with _lock:
                for j in found:
                    u = j.get("url")
                    title = (j.get("title") or "").lower()
                    desc = j.get("desc") or ""
                    if not u or not match_job(title, desc, kws):
                        continue
                    if desc:
                        new_descs[u] = desc[:8000]
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
        if new_descs:
            cache = load_desc_cache()
            for u, d in new_descs.items():
                if len(d) > len(cache.get(u) or ""):  # keep the more complete version
                    cache[u] = d
            _atomic_write(DESC_CACHE_FILE, json.dumps(cache, ensure_ascii=False))
        save_state()
        # score the new jobs right after fetching
        if state.get("resume") and not state["match"]["running"]:
            _spawn(run_match)


# ---------------------------------------------------------------- Social hiring posts (Hacker News)
# HN has a monthly "Ask HN: Who is hiring?" thread (posted by the whoishiring bot on the 1st);
# each top-level comment is a hiring post, conventionally headed: Company | Role | Location | Remote | Visa | tech | url.
# Algolia offers a free, unauthenticated search API with no API key — the best-fitting social source for this tool.
HN_ALGOLIA = "https://hn.algolia.com/api/v1"
_HN_URL_RE = re.compile(r"https?://[^\s|)<>\"']+")
_HN_VISA_RE = re.compile(r"\b(visa|sponsor|sponsorship|relocation|relocat\w*|h1b|h-1b|tier 2|skilled worker)\b", re.I)


def _hn_first_para(html_text):
    """Take the comment's first paragraph (the hiring post's header line: Company | Role | Location | Remote | …).
    HN comment paragraphs are separated by <p>; the first one comes before the first <p>."""
    head = re.split(r"<p>", html_text or "", maxsplit=1)[0]
    return _strip_html(head)


def _hn_get(url):
    """HN Algolia-specific fetch: generous timeout + one retry. Skips the ATS (2,5) timeout and rate-limit exceptions,
    because the items endpoint returns ~500KB of JSON; a short timeout occasionally fails and is silently swallowed as 0."""
    for attempt in range(2):
        try:
            r = _session().get(url, timeout=(5, 30))
            if r.status_code == 200:
                return r.json()
        except Exception:
            if attempt == 0 and _cur_stop().wait(1.0):
                break
    return None


def _hn_hiring_threads(n_threads=1):
    data = _hn_get(f"{HN_ALGOLIA}/search_by_date?tags=story,author_whoishiring&hitsPerPage=8")
    hits = (data or {}).get("hits") or []
    threads = [h for h in hits if "who is hiring" in (h.get("title") or "").lower()]
    return threads[:n_threads]


def search_hackernews(n_threads=1):
    """Parse every hiring comment under the latest n HN 'Who is hiring' threads into a job.
    Same shape as search_adzuna: {company,title,url,location,desc,source}."""
    out = []
    for th in _hn_hiring_threads(n_threads):
        item = _hn_get(f"{HN_ALGOLIA}/items/{th.get('objectID')}")
        for c in (item or {}).get("children") or []:
            raw = c.get("text")
            if not raw:
                continue
            plain = _strip_html(raw)
            if len(plain) < 30:       # skip short comments like "[dead]" or pure meta
                continue
            header = _hn_first_para(raw)[:200] or plain[:200]
            m = _HN_URL_RE.search(plain)          # external application link in the body
            apply_url = m.group(0) if m and "ycombinator.com" not in m.group(0) else None
            hn_url = f"https://news.ycombinator.com/item?id={c.get('id')}"
            company = re.split(r"[|:\-–—]", header)[0].strip()[:80]
            out.append({
                "company": company, "title": header,
                "url": apply_url or hn_url, "hn_url": hn_url,
                "location": header,   # header line often contains location/Remote; classify_region handles it
                "desc": (plain + f"  · Original post: {hn_url}")[:8000],
                "source": "HackerNews",
            })
    return out


def run_social():
    """Fetch HN hiring posts, filter by user keywords and merge into agg_jobs (reusing the aggregator display/matching pipeline).
    No API key needed."""
    if state["social"]["running"]:
        return
    kws = [k.lower() for k in state["keywords"]]
    today = date.today().isoformat()
    with _lock:
        sponsor_idx = {_norm_company(n) for n in state["companies"]}
    state["social"] = {"running": True, "done": 0, "total": 0, "found": 0, "err": ""}
    new_descs = {}
    added = 0
    try:
        try:
            posts = search_hackernews(n_threads=1)
        except Exception as e:
            posts = []
            state["social"]["err"] = f"Hacker News fetch failed: {e}"[:200]
        state["social"]["total"] = len(posts)
        with _lock:
            for j in posts:
                u = j.get("url")
                title = (j.get("title") or "").lower()
                desc = j.get("desc") or ""
                state["social"]["done"] += 1
                if not u or not match_job(title, desc, kws):
                    continue
                added += 1
                new_descs[u] = desc[:8000]
                region, rlabel = classify_region(j.get("location"))
                seen = state["agg_jobs"].get(u)
                state["agg_jobs"][u] = {
                    "company": j.get("company", ""), "title": j.get("title", ""),
                    "url": u, "location": rlabel or "",
                    "source": "HackerNews", "region": region, "country": rlabel,
                    "level": classify_level(title),
                    "llm": kw_match(title, LLM_KEYWORDS) or kw_match(desc.lower(), LLM_KEYWORDS),
                    "sponsor": _norm_company(j.get("company", "")) in sponsor_idx,
                    "mentions_visa": bool(_HN_VISA_RE.search(desc)),
                    "first_seen": seen["first_seen"] if seen else today,
                    "last_seen": today,
                }
    finally:
        state["social"]["found"] = added
        state["social"]["running"] = False
        if new_descs:
            cache = load_desc_cache()
            for u, d in new_descs.items():
                if len(d) > len(cache.get(u) or ""):
                    cache[u] = d
            _atomic_write(DESC_CACHE_FILE, json.dumps(cache, ensure_ascii=False))
        save_state()
        if state.get("resume") and not state["match"]["running"]:
            _spawn(run_match)


# ---------------------------------------------------------------- Company size (LLM estimate)
SIZE_BANDS = ("startup", "mid", "large", "unknown")
SIZE_LABELS = {"startup": "Startup <50", "mid": "Mid 50–500",
               "large": "Large 500+", "unknown": "Size unknown"}
_SIZE_BATCH = 30   # companies per LLM request


def save_company_sizes():
    _atomic_write(COMPANY_SIZE_FILE, json.dumps(company_sizes, ensure_ascii=False))


def _parse_llm_json(text):
    """Extract a JSON array from LLM output (tolerating ```json fences and surrounding chatter)."""
    t = (text or "").strip()
    if "```" in t:
        t = re.sub(r"```(?:json)?", "", t)
    m = re.search(r"\[.*\]", t, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _size_targets():
    """Company names needing size detection: sponsors with matching jobs + aggregator job companies, deduped, cached ones skipped."""
    names = set()
    with _lock:
        for n, r in state["results"].items():
            if r.get("matched"):
                names.add(n)
        for j in state["agg_jobs"].values():
            c = (j.get("company") or "").strip()
            if c:
                names.add(c)
    return [n for n in names if n and n not in company_sizes]


def run_company_size():
    """Use an LLM to batch-estimate employee-size bands for "companies with jobs", writing to company_sizes and caching.
    Only uncached companies are asked, to spread cost; the model returns unknown for ones it doesn't know (no guessing)."""
    if not _llm_ready():
        return
    todo = _size_targets()
    state["size"] = {"running": True, "done": 0, "total": len(todo)}
    try:
        for i in range(0, len(todo), _SIZE_BATCH):
            batch = todo[i:i + _SIZE_BATCH]
            prompt = (
                "Classify each UK company below by employee headcount. Output ONLY "
                'a JSON array; each item {"name":..., "band":..., "note":...}.\n'
                'band must be one of: "startup" (<50 people), "mid" (50-500), '
                '"large" (500+), "unknown" (use this whenever you are not sure or '
                "do not recognise the company; never guess).\n"
                'note: at most 12 characters, the basis for the call or "unsure".\n'
                "Companies: " + json.dumps(batch, ensure_ascii=False))
            try:
                rows = _parse_llm_json(_llm_complete(prompt, max_tokens=2000))
            except Exception:
                rows = []
            by_name = {(r.get("name") or "").strip(): r for r in rows if isinstance(r, dict)}
            for n in batch:
                r = by_name.get(n) or {}
                band = r.get("band") if r.get("band") in SIZE_BANDS else "unknown"
                company_sizes[n] = {"band": band, "note": (r.get("note") or "")[:12]}
            state["size"]["done"] = min(i + len(batch), len(todo))
            save_company_sizes()
    finally:
        state["size"]["running"] = False
        save_company_sizes()


# ---------------------------------------------------------------- Resume matching
DESC_CACHE_FILE = os.path.join(DATA_DIR, "desc_cache.json")
DESC_FAIL_FILE = os.path.join(DATA_DIR, "desc_fail.json")
FAIL_RETRY_SEC = 24 * 3600  # allow a retry 24 hours after a JD fetch failure



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
    """URLs whose fetch failed; only re-fetched after 24h, so each match run doesn't retry dead links."""
    ts = fails.get(u)
    if not ts:
        return True
    try:
        return (time.time() - float(ts)) > FAIL_RETRY_SEC
    except (TypeError, ValueError):
        return True


def fetch_descriptions(r, cache, fails):
    """Best-effort fetch of JD text for all matching jobs at one company, written to cache (url -> text).
    Failures go into fails (url -> failure timestamp) and may be retried after 24h."""
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
            fails.pop(u, None)          # fetched this time, clear the failure record
        else:
            fails[u] = time.time()      # still not fetched; record the failure time, retry after 24h


# --- Rules approximating real UK recruiting screens ---


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
        agg = [(u, dict(j)) for u, j in state["agg_jobs"].items()]
    state["match"] = {"running": True, "done": 0,
                      "total": len(targets) + (1 if agg else 0)}
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
        if agg:  # aggregator jobs are scored too: the JD is the summary saved into desc_cache at fetch time
            agg_scores = {}
            for u, j in agg:
                res = analyze_job(j.get("title", ""), cache.get(u, ""),
                                  resume_kws, my_years, j.get("level"))
                if res["n"]:
                    agg_scores[u] = res
            with _lock:
                state["match_scores"].update(agg_scores)
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
            return jsonify({"error": f"Could not parse the file: {e} (try exporting it as PDF or TXT)"}), 400
        name = f.filename
    else:
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        name = "Pasted text"
    text = (text or "").strip()
    if len(text) < 100:
        return jsonify({"error": "Resume text is too short to read (if the PDF is a scan, use a text PDF or paste the text)"}), 400
    kws = sorted(extract_skills(text))
    with _lock:
        state["resume"] = {"text": text[:20000], "keywords": kws, "name": name,
                           "updated": date.today().isoformat()}
        state["match_scores"] = {}
    save_state()
    _spawn(run_match)
    return jsonify({"ok": True, "keywords": kws, "chars": len(text)})


@app.route("/api/match", methods=["POST"])
def api_match():
    if not state.get("resume"):
        return jsonify({"error": NEED_RESUME_MSG}), 400
    if state["match"]["running"]:
        return jsonify({"error": "Match scoring is already running"}), 409
    _spawn(run_match)
    return jsonify({"started": True})


# ---------------------------------------------------------------- Resume improvement advice
# Corpus mining: catch phrases like "experience with X / proficiency in X" in JDs to surface skills outside the vocabulary
_FREEFORM_CUE_RE = re.compile(
    r"(?:experience (?:with|in|using)|proficien(?:t|cy) (?:in|with)|knowledge of|"
    r"familiar(?:ity)? with|expertise in|skilled? in|hands[- ]on (?:with|experience with)|"
    r"background in|understanding of|working knowledge of|deep understanding of) "
    r"([a-z0-9][a-z0-9 .+#/-]{2,40})")
_FREEFORM_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "with", "using", "to", "for", "our",
    "your", "their", "this", "that", "these", "those", "such", "related", "various",
    "modern", "strong", "solid", "good", "excellent", "proven", "real", "world",
    "large", "scale", "high", "quality", "best", "practices", "practice", "years",
    "year", "team", "teams", "ability", "concepts", "principles", "at", "least",
    "is", "are", "be", "required", "preferred", "plus", "etc", "including", "as",
    "on", "per", "across", "into", "within", "other", "any", "all", "must",
    "should", "would", "will", "can", "we", "you", "they", "it", "clusters",
}


def mine_frequent_terms(descs, known, top=10):
    """Mine frequent candidate skill phrases from the JD corpus that aren't in the skill vocabulary/resume (heuristic)."""
    from collections import Counter
    cnt = Counter()
    for d in descs:
        for m in _FREEFORM_CUE_RE.finditer((d or "").lower()):
            words = [w for w in re.split(r"[ /]+", m.group(1).strip())
                     if w and w not in _FREEFORM_STOP]
            for n in (2, 1):  # prefer bigrams, fall back to unigrams
                if len(words) >= n:
                    term = " ".join(words[:n])
                    if len(term) > 2 and term not in known:
                        cnt[term] += 1
                    break
    return cnt.most_common(top)


def resume_gap_report(top=15):
    """Aggregate the resume and platform-wide match scores into a gap report: skills most worth adding + their impact."""
    resume = state.get("resume")
    if not resume:
        return {"ready": False}
    from collections import Counter
    resume_kws = set(resume["keywords"])
    with _lock:
        scores = [dict(ms) for ms in state["match_scores"].values() if ms]
    weight, jobs, near, have = Counter(), Counter(), Counter(), Counter()
    n_scored = 0
    for ms in scores:
        if not ms.get("n"):
            continue
        n_scored += 1
        band = 35 <= (ms.get("score") or 0) < 70   # mid-range match: adding skills moves these the most
        for k in ms.get("must_miss", []):
            weight[k] += 2; jobs[k] += 1
            if band:
                near[k] += 1
        for k in (ms.get("nice_miss") or []):
            weight[k] += 1; jobs[k] += 1
            if band:
                near[k] += 1
        for k in ms.get("hit", []):
            have[k] += 1
    gaps = [{"skill": k, "jobs": jobs[k], "near": near[k]}
            for k, _ in weight.most_common(top)]
    known = KNOWN_SKILLS | resume_kws
    freeform = [{"term": t, "jobs": c}
                for t, c in mine_frequent_terms(load_desc_cache().values(), known)]
    return {"ready": True, "n_scored": n_scored, "gaps": gaps,
            "have": [k for k, _ in have.most_common(15)], "freeform": freeform}


def _anthropic_key():
    return api_keys.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")


def _openai_key():
    return api_keys.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")


def _llm_provider():
    """Decide which LLM generates advice: explicit llm_provider wins, otherwise whichever has a key configured."""
    pref = (api_keys.get("llm_provider") or "").strip().lower()
    if pref in ("openai", "chatgpt", "gpt"):
        return "openai" if _openai_key() else ("anthropic" if _anthropic_key() else None)
    if pref in ("anthropic", "claude"):
        return "anthropic" if _anthropic_key() else ("openai" if _openai_key() else None)
    if _openai_key():        # when unspecified: use the ChatGPT key if present, otherwise Claude
        return "openai"
    if _anthropic_key():
        return "anthropic"
    return None


def _llm_ready():
    return _llm_provider() is not None


LLM_LABELS = {"openai": "ChatGPT", "anthropic": "Claude"}
LLM_MISSING_MSG = ("No LLM API key configured: add openai_api_key (ChatGPT) or "
                   "anthropic_api_key (Claude) to data/api_keys.json, or set the "
                   "OPENAI_API_KEY / ANTHROPIC_API_KEY environment variable")
NEED_RESUME_MSG = "Please upload your resume first"
NEED_URL_MSG = "Missing job URL"

# System prompt per UI language. Deliberately industry-neutral: the tool is used
# for nursing, accounting, engineering... not only AI/ML roles.
RESUME_SYS = {
    "en": ("You are a senior resume consultant and ATS-optimisation expert helping "
           "job seekers in the UK. Your advice is specific, actionable and honest; "
           "never invent experience the candidate does not have."),
    "zh": ("你是资深简历顾问兼 ATS 优化专家，服务在英国求职的候选人。"
           "建议要具体、可执行、诚实，绝不编造求职者没有的经历。"),
}


def _req_lang():
    """UI language of the current request: "en" by default, "zh" when the UI is
    in Chinese. The frontend sends it as JSON {"lang": ...} or ?lang=."""
    data = request.get_json(silent=True) or {}
    lang = str(data.get("lang") or request.args.get("lang") or "en").lower()
    return "zh" if lang.startswith("zh") else "en"


def _openai_complete(prompt, max_tokens, lang="en"):
    from openai import OpenAI
    client = OpenAI(api_key=_openai_key())
    model = api_keys.get("openai_model", "gpt-4o")
    sys_prompt = RESUME_SYS.get(lang, RESUME_SYS["en"])
    kw = dict(model=model,
              messages=[{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": prompt}])
    try:
        resp = client.chat.completions.create(max_tokens=max_tokens, **kw)
    except Exception:  # newer/reasoning models use max_completion_tokens instead
        resp = client.chat.completions.create(max_completion_tokens=max_tokens, **kw)
    return resp.choices[0].message.content or ""


def _anthropic_complete(prompt, max_tokens, lang="en"):
    import anthropic
    client = anthropic.Anthropic(api_key=_anthropic_key())
    model = api_keys.get("anthropic_model", "claude-opus-4-8")
    with client.messages.stream(model=model, max_tokens=max_tokens,
                                thinking={"type": "adaptive"},
                                system=RESUME_SYS.get(lang, RESUME_SYS["en"]),
                                messages=[{"role": "user", "content": prompt}]) as stream:
        msg = stream.get_final_message()
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _llm_complete(prompt, max_tokens=6000, lang="en"):
    """Call the LLM for the configured provider to generate advice; returns plain text.
    In multi-tenant mode, first charges the current user's daily LLM quota; raises UsageLimitError when over."""
    _charge("llm", LLM_DAILY_CAP)
    return (_openai_complete if _llm_provider() == "openai"
            else _anthropic_complete)(prompt, max_tokens, lang)


def generate_resume_advice(report, lang="en"):
    """Actionable resume advice (Markdown) from the gap report + full resume text,
    written in the UI language."""
    resume = state.get("resume") or {}
    resume_txt = (resume.get("text") or "")[:8000]
    n_scored = report.get("n_scored", 0)
    if lang == "zh":
        gaps_txt = "\n".join(
            f"- {g['skill']}：缺失于 {g['jobs']} 个岗位"
            + (f"（其中 {g['near']} 个是中等匹配，最可能因此被拉低）" if g["near"] else "")
            for g in report.get("gaps", []))
        free_txt = "、".join(f"{f['term']}({f['jobs']})" for f in report.get("freeform", []))
        have_txt = "、".join(report.get("have", [])) or "（无）"
        prompt = f"""我在英国求职。以下是把我的简历与全平台 {n_scored} 个岗位匹配后的统计。

【我简历已覆盖的高频技能】{have_txt}

【全平台最常要求、但我简历缺失的技能（按影响排序）】
{gaps_txt or '（无）'}

【JD 里高频出现、但可能既不在我简历也不在技能词表里的表达（启发式，仅供参考）】{free_txt or '（无）'}

【我的简历全文】
{resume_txt}

请给我一份可执行的简历修改建议（中文，Markdown）：
1. 优先级：先补哪 3–5 个技能/关键词最能整体提升匹配度，并引用“缺失于多少个岗位”说明理由。
2. 每个要补的技能：若我可能已具备，建议加到简历哪一段、用什么措辞最自然（给 1 条量化 bullet 示例）。
3. 指出我简历里 2–3 条最该改写的经历，怎么改更贴近这些岗位。
4. 诚实提醒：哪些缺失技能若我确实没有，别硬写，应通过项目/课程补齐。
不要编造我没有的经历。"""
    else:
        gaps_txt = "\n".join(
            f"- {g['skill']}: missing from {g['jobs']} jobs"
            + (f" ({g['near']} of them medium matches, most likely pulled down by it)"
               if g["near"] else "")
            for g in report.get("gaps", []))
        free_txt = ", ".join(f"{f['term']} ({f['jobs']})" for f in report.get("freeform", []))
        have_txt = ", ".join(report.get("have", [])) or "(none)"
        prompt = f"""I'm job hunting in the UK. Below are the statistics from matching my resume against {n_scored} jobs.

[High-frequency skills my resume already covers] {have_txt}

[Skills most often required but missing from my resume (ranked by impact)]
{gaps_txt or '(none)'}

[Phrases that appear often in the job descriptions but may be in neither my resume nor the skill vocabulary (heuristic, for reference only)] {free_txt or '(none)'}

[My full resume]
{resume_txt}

Please give me actionable resume advice (in English, Markdown):
1. Priorities: which 3–5 skills/keywords to add first for the biggest overall lift, citing how many jobs each is missing from.
2. For each skill to add: if I plausibly already have it, which resume section to put it in and the most natural wording (give one quantified bullet example).
3. Point out the 2–3 experiences in my resume most worth rewriting, and how to bring them closer to these jobs.
4. Honesty check: for missing skills I genuinely don't have, don't fake them; suggest how to build them through projects or courses instead.
Do not invent experience I don't have."""
    return _llm_complete(prompt, max_tokens=8000, lang=lang)


@app.route("/api/resume_suggestions")
def api_resume_suggestions():
    report = resume_gap_report()
    prov = _llm_provider()
    report["has_llm"] = prov is not None
    report["llm_label"] = LLM_LABELS.get(prov)
    return jsonify(report)


@app.route("/api/resume_suggestions/generate", methods=["POST"])
def api_resume_suggestions_generate():
    if not state.get("resume"):
        return jsonify({"error": NEED_RESUME_MSG}), 400
    report = resume_gap_report()
    if not report.get("ready") or not report.get("gaps"):
        return jsonify({"error": "No match data yet: upload your resume and wait for scoring to finish"}), 400
    if not _llm_ready():
        return jsonify({"error": LLM_MISSING_MSG}), 400
    try:
        advice = generate_resume_advice(report, _req_lang())
    except UsageLimitError:
        raise
    except Exception as e:
        return jsonify({"error": f"Generation failed: {e}"}), 500
    return jsonify({"advice": advice})


def _find_job(url):
    """Look up job metadata (title, company, location) by URL in scan results / aggregator jobs."""
    with _lock:
        for n, r in state["results"].items():
            for j in r.get("matched", []):
                if j.get("url") == url:
                    return {"title": j.get("title", ""), "company": n,
                            "location": j.get("location", "")}
        j = state["agg_jobs"].get(url)
        if j:
            return {"title": j.get("title", ""), "company": j.get("company", ""),
                    "location": j.get("location", "")}
    return None


def generate_job_advice(url, lang="en"):
    """Job-specific resume advice (Markdown): the JD text + this job's match
    analysis + the full resume, written in the UI language."""
    resume = state.get("resume") or {}
    meta = _find_job(url) or {}
    ms = state["match_scores"].get(url) or {}
    jd = (load_desc_cache().get(url) or "")[:8000]
    resume_txt = (resume.get("text") or "")[:8000]
    title, company, loc = meta.get("title", ""), meta.get("company", ""), meta.get("location", "")
    if lang == "zh":
        flags_txt = "；".join(f.get("t", "") for f in ms.get("flags", []))
        prompt = f"""请针对下面这个具体岗位，帮我优化简历，让它更容易通过 ATS 筛选并打动招聘官。

【目标岗位】{title} — {company}（{loc}）
【岗位链接】{url}
【当前匹配度】{ms.get('score', '未知')}%
【JD 要求、我简历已覆盖】{('、'.join(ms.get('hit', [])) or '（无）')}
【JD 必需、我简历缺失（优先处理）】{('、'.join(ms.get('must_miss', [])) or '（无）')}
【JD 加分、我简历缺失】{('、'.join(ms.get('nice_miss', [])) or '（无）')}
{('【签证/门槛提醒】' + flags_txt) if flags_txt else ''}

【JD 正文节选】
{jd or '（未抓到正文，请只依据上面的技能缺口给建议）'}

【我的简历全文】
{resume_txt}

请给出这一份岗位专属的简历修改建议（中文，Markdown）：
1. 若缺失技能我实际具备：该加到简历哪一段、用什么措辞最自然（给量化 bullet 示例）。
2. 重写我简历中最相关的 2–3 条经历，向这个岗位靠拢，量化成果、贴合 JD 关键词（利于 ATS，但别堆砌）。
3. 针对这家公司写一段 3 句话的求职信开场白。
4. 诚实提醒：哪些缺失技能若我确实没有，别硬写，建议怎么补齐。
不要编造我没有的经历。"""
    else:
        # Flags are stored as Chinese keys by matching.py; translate for the prompt.
        flags_txt = "; ".join(_flag_en(f.get("t", "")) for f in ms.get("flags", []))
        prompt = f"""Please help me tailor my resume to the specific job below so it passes ATS screening and appeals to the recruiter.

[Target role] {title} — {company} ({loc})
[Job link] {url}
[Current match score] {ms.get('score', 'unknown')}%
[JD skills my resume already covers] {(', '.join(ms.get('hit', [])) or '(none)')}
[JD required skills missing from my resume (prioritise)] {(', '.join(ms.get('must_miss', [])) or '(none)')}
[JD nice-to-have skills missing from my resume] {(', '.join(ms.get('nice_miss', [])) or '(none)')}
{('[Visa / threshold warnings] ' + flags_txt) if flags_txt else ''}

[Job description excerpt]
{jd or '(Full JD text was not fetched; base the advice on the skill gaps above only)'}

[My full resume]
{resume_txt}

Please give resume advice specific to this one job (in English, Markdown):
1. For missing skills I actually have: which resume section to add them to and the most natural wording (give quantified bullet examples).
2. Rewrite the 2–3 most relevant experiences in my resume to fit this job: quantify results and mirror the JD's keywords (good for ATS, but don't stuff them).
3. Write a 3-sentence cover-letter opening tailored to this company.
4. Honesty check: for missing skills I genuinely don't have, don't fake them; suggest how to build them.
Do not invent experience I don't have."""
    return _llm_complete(prompt, max_tokens=6000, lang=lang)


def _flag_en(t):
    """English text for a match flag (matching.py stores them in Chinese; the
    frontend translates them the same way)."""
    m = re.match(r"^要求 (\d+)\+ 年经验$", t or "")
    if m:
        return f"Requires {m.group(1)}+ years of experience"
    return {
        "需安全许可/国籍要求": "Security clearance / nationality required",
        "JD 声明不担保签证": "JD says no visa sponsorship",
        "明确提供签证担保": "JD explicitly offers visa sponsorship",
        "未抓到 JD，仅按标题估分": "JD not fetched; scored from the title only",
    }.get(t, t)


@app.route("/api/job_advice", methods=["POST"])
def api_job_advice():
    if not state.get("resume"):
        return jsonify({"error": NEED_RESUME_MSG}), 400
    if not _llm_ready():
        return jsonify({"error": LLM_MISSING_MSG}), 400
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": NEED_URL_MSG}), 400
    if url not in state["match_scores"]:
        return jsonify({"error": "This job has no match score yet; run match scoring first"}), 400
    lang = _req_lang()
    ckey = _cache_key(url, lang)
    cached = state["advice"].get(ckey)
    if cached and not data.get("force"):
        return jsonify({"advice": cached, "cached": True})
    try:
        advice = generate_job_advice(url, lang)
    except UsageLimitError:
        raise
    except Exception as e:
        return jsonify({"error": f"Generation failed: {e}"}), 500
    with _lock:
        state["advice"][ckey] = advice
    save_state()
    return jsonify({"advice": advice})


def _cache_key(url, lang):
    """Cache key for LLM drafts. English keeps the bare URL; other languages get a
    suffix so switching the UI language never serves a draft in the wrong one."""
    return url if lang == "en" else f"{url}#lang={lang}"


# ---------------------------------------------------------------- Hidden jobs
# Generic words skipped when mining exclude-word suggestions: they appear in almost every title, so excluding them is pointless
_TITLE_STOP = {
    "engineer", "engineering", "developer", "scientist", "researcher", "analyst",
    "senior", "junior", "lead", "staff", "graduate", "intern", "internship",
    "the", "and", "for", "with", "remote", "hybrid", "london", "manchester",
    "data", "software", "machine", "learning", "artificial", "intelligence",
}


def exclude_suggestions():
    """Mine frequent words from hidden jobs' titles (appearing ≥3 times, not already keywords/exclude words)
    as "one-click add to exclude words" candidates — the more you hide, the better it learns."""
    kws = set(state["keywords"]) | set(state["exclude_keywords"])
    cnt = Counter()
    for h in state["hidden"].values():
        for w in set(re.findall(r"[a-z]{3,}", (h.get("title") or "").lower())):
            if w not in _TITLE_STOP and w not in kws:
                cnt[w] += 1
    return [w for w, c in cnt.most_common(5) if c >= 3]


@app.route("/api/hide", methods=["POST"])
def api_hide():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": NEED_URL_MSG}), 400
    with _lock:
        if data.get("on", True):
            state["hidden"][url] = {"ts": date.today().isoformat(),
                                    "title": (data.get("title") or "")[:200]}
        else:
            state["hidden"].pop(url, None)
        n = len(state["hidden"])
    save_state()
    return jsonify({"ok": True, "hidden": n, "excl_suggest": exclude_suggestions()})


# ---------------------------------------------------------------- Application tracker
TRACK_STATUSES = ("saved", "applied", "interview", "offer", "rejected")


@app.route("/api/track", methods=["POST"])
def api_track():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    status = (data.get("status") or "").strip()
    if not url:
        return jsonify({"error": NEED_URL_MSG}), 400
    with _lock:
        if status == "remove":
            state["tracker"].pop(url, None)
        elif status in TRACK_STATUSES:
            ent = state["tracker"].get(url) or {"ts": date.today().isoformat()}
            ent["status"] = status
            # store a job snapshot so it still shows in the tracker after the listing is taken down
            for k in ("title", "company", "location"):
                if data.get(k):
                    ent[k] = data[k]
            state["tracker"][url] = ent
        else:
            return jsonify({"error": "Invalid status"}), 400
        tracker = dict(state["tracker"])
    save_state()
    return jsonify({"ok": True, "tracker": tracker})


def generate_outreach(url, lang="en"):
    """Personalised networking drafts for one job (LinkedIn connection note,
    follow-up DM, cold email). The drafts themselves are always in English (they
    go to UK recruiters); the section labels follow the UI language."""
    resume = state.get("resume") or {}
    meta = _find_job(url) or {}
    ms = state["match_scores"].get(url) or {}
    jd = (load_desc_cache().get(url) or "")[:4000]
    resume_txt = (resume.get("text") or "")[:6000]
    title, company, loc = meta.get("title", ""), meta.get("company", ""), meta.get("location", "")
    if lang == "zh":
        prompt = f"""我想就下面这个岗位，主动联系这家公司的招聘官或团队成员（networking）。请基于我的简历亮点，为我起草个性化的英文搭话内容——要像我本人手写的：具体、真诚、克制，绝不能有套话群发感。

【目标岗位】{title} — {company}（{loc}）
【我与岗位的重合点】{('、'.join(ms.get('hit', [])[:10]) or '（还没算匹配度，请从我简历里挑最相关的亮点）')}
【JD 正文节选】
{jd or '（未抓到正文，依据岗位标题和公司背景来写）'}

【我的简历全文】
{resume_txt}

请输出三部分（英文正文，每部分前用一行中文说明用途；Markdown 格式）：
1. **LinkedIn 好友申请附言**（≤280 字符：一句对这家公司具体产品/技术方向的真实兴趣 + 一句我是谁 + 轻量请求）
2. **通过后的跟进私信**（100–150 词：为什么对这个岗位/团队感兴趣（具体到产品或技术栈）、我最相关的 1–2 个量化成果、一个清晰的小请求——15 分钟聊聊或帮忙内推）
3. **冷邮件**（含 Subject 行；120–180 词，结构同上但更正式，结尾提一句简历见附件）

硬性要求：不编造我没有的经历；语气自信但不自夸；每一封都必须包含至少一个只属于这家公司的具体细节（产品名/技术方向/公开的近期动态），JD 里没有就基于公司名选择其公开的主营方向。"""
    else:
        prompt = f"""I want to reach out to a recruiter or team member at this company about the job below (networking). Based on the highlights of my resume, draft personalised outreach in English. It should read as if I wrote it by hand: specific, sincere and restrained, never like a mass template.

[Target role] {title} — {company} ({loc})
[Where I overlap with the role] {(', '.join(ms.get('hit', [])[:10]) or '(No match score yet; pick the most relevant highlights from my resume)')}
[Job description excerpt]
{jd or '(Full JD text was not fetched; write from the job title and the company background)'}

[My full resume]
{resume_txt}

Output three parts (Markdown, each preceded by a one-line heading saying what it is for):
1. **LinkedIn connection note** (≤280 characters: one line of genuine interest in a specific product/technical direction of this company + one line on who I am + a light ask)
2. **Follow-up message after they accept** (100–150 words: why this role/team interests me (specific product or stack), my 1–2 most relevant quantified achievements, and one clear small ask: a 15-minute chat or a referral)
3. **Cold email** (with a Subject line; 120–180 words, same structure but more formal, ending with a note that my resume is attached)

Hard rules: don't invent experience I don't have; confident but not boastful; every draft must include at least one detail specific to this company (product name, technical direction or a recent public update). If the JD has none, use the company's publicly known main business."""
    return _llm_complete(prompt, max_tokens=4000, lang=lang)


@app.route("/api/outreach", methods=["POST"])
def api_outreach():
    if not state.get("resume"):
        return jsonify({"error": NEED_RESUME_MSG}), 400
    if not _llm_ready():
        return jsonify({"error": LLM_MISSING_MSG}), 400
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": NEED_URL_MSG}), 400
    lang = _req_lang()
    ckey = _cache_key(url, lang)
    cached = state["outreach"].get(ckey)
    if cached and not data.get("force"):
        return jsonify({"draft": cached, "cached": True})
    try:
        draft = generate_outreach(url, lang)
    except UsageLimitError:
        raise
    except Exception as e:
        return jsonify({"error": f"Generation failed: {e}"}), 500
    with _lock:
        state["outreach"][ckey] = draft
    save_state()
    return jsonify({"draft": draft})


# ---------------------------------------------------------------- Import
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


REGISTER_ROUTE = "Skilled Worker"   # only this visa route is wanted from the official register


def _read_table(f):
    """Read an uploaded xlsx/csv uniformly as (header, data rows), so both formats share the same detection."""
    fname = (f.filename or "").lower()
    if fname.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(f.read()), read_only=True, data_only=True)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            try:
                header = ["" if c is None else str(c) for c in next(it)]
            except StopIteration:
                continue
            if any(h.strip() for h in header):
                return header, [["" if c is None else str(c) for c in r] for r in it]
        return [], []
    text = f.read().decode("utf-8-sig", errors="replace")
    table = list(csvmod.reader(text.splitlines()))
    return (table[0], table[1:]) if table else ([], [])


def _extract_companies(header, rows):
    """(names, towns, tag). Auto-distinguishes the "official sponsor register" from a "plain company list".

    The official register (the gov.uk CSV) has Organisation Name + Route columns: only take the Skilled Worker
    route, include Town/City, and tag register. Other files are treated as plain lists and tagged curated.
    """
    idx = {str(h).strip().lower(): i for i, h in enumerate(header) if str(h).strip()}
    ni, ri = idx.get("organisation name"), idx.get("route")
    if ni is not None and ri is not None:          # official sponsor register
        ti = idx.get("town/city")
        names, towns, seen = [], [], set()
        for r in rows:
            if len(r) <= max(ni, ri) or str(r[ri]).strip() != REGISTER_ROUTE:
                continue
            n = str(r[ni]).strip()
            if not n or n.lower() in seen:
                continue
            seen.add(n.lower())
            names.append(n)
            towns.append(str(r[ti]).strip() if ti is not None and len(r) > ti else "")
        return names, towns, "register"
    col = _pick_company_col(header)                 # plain list
    if col is not None:
        names = [str(r[col]).strip() for r in rows if len(r) > col and str(r[col]).strip()]
    else:                                            # no header: treat the whole column as company names
        names = [str(r[0]).strip() for r in [header] + rows if r and str(r[0]).strip()]
    return [n for n in names if not n.startswith("=")], None, "curated"


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Import a company list: the official sponsor-register CSV or your own
    Excel/CSV list, detected automatically. Owner-only in multi-user mode
    (the company directory is shared by every account)."""
    denied = _admin_only()
    if denied:
        return denied
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file received"}), 400
    try:
        names, towns, tag = _extract_companies(*_read_table(f))
    except Exception as e:
        return jsonify({"error": f"Could not parse the file: {e}"}), 400
    if not names:
        return jsonify({"error": "No company names found (check the file has a company-name column)"}), 400
    added = add_companies(names, tag, towns)
    return jsonify({"count": added, "parsed": len(names), "kind": tag,
                    "total": len(state["companies"])})


@app.route("/api/companies", methods=["POST"])
def api_companies():
    denied = _admin_only()
    if denied:
        return denied
    data = request.get_json(force=True)
    names = [n for n in data.get("names", []) if n.strip()]
    added = add_companies(names, "curated")
    return jsonify({"added": added, "total": len(state["companies"])})


# ---------------------------------------------------------------- Routes
@app.route("/healthz")
def healthz():
    return "ok", 200


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
        # curated companies are shown even if no job board was detected
        for n in curated:
            if n not in res_out:
                st = "no_board" if ats_cache.get(n) in _NO_ATS else "pending"
                res_out[n] = {"name": n, "status": st, "matched": [],
                              "curated": True, "links": build_links(n)}

        excl = state.get("exclude_keywords") or []
        excl_re = (re.compile(r"\b(" + "|".join(re.escape(k) for k in excl) + r")\b")
                   if excl else None)
        # Target/acceptable titles: the built-in AI defaults used to be back-filled by the front end and saved back — anything
        # identical to the defaults counts as "not set", otherwise the tool would be locked into the AI profile forever.
        user_tgt = state.get("target_titles") or None
        if user_tgt == DEFAULT_TARGET_TITLES:
            user_tgt = None
        user_acc = state.get("acceptable_titles") or None
        if user_acc == DEFAULT_ACCEPTABLE_TITLES:
            user_acc = None
        kws = [k.lower() for k in (state.get("keywords") or [])]
        # As soon as the user sets target titles, or changes keywords from the built-in AI defaults to another industry (incl. clearing
        # keywords = see everything), switch to the custom profile: direction follows the user's words, no AI blocklist.
        default_kws = [k.lower() for k in DEFAULT_KEYWORDS]
        custom_prof = bool(user_tgt) or bool(user_acc) or (kws != default_kws)
        show_hidden = request.args.get("hidden") == "1"  # hidden view: show only hidden jobs

        feed = []
        for n, r in results.items():
            on_reg = "register" in (comps.get(n) or {}).get("tags", [])
            for j in r.get("matched", []):
                if (j.get("url", "") in state["hidden"]) != show_hidden:
                    continue
                if excl_re and excl_re.search((j.get("title") or "").lower()):
                    continue
                # old data may lack region/level; compute on the fly
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
                visa = visa_certainty(ms, on_reg)
                tmatch = title_match(j.get("title", ""), user_tgt, user_acc,
                                     custom=custom_prof, keywords=kws)
                feed.append({
                    "title": j.get("title", ""), "url": j.get("url", ""),
                    "location": j.get("location", ""), "company": n,
                    "curated": n in curated, "llm": bool(j.get("llm")),
                    "region": j["region"], "country": j.get("country", ""),
                    "level": j["level"], "via": j.get("via", "title"),
                    "first_seen": fs, "days": days,
                    "njobs": r.get("total_jobs", 0),
                    "csize": (company_sizes.get(n) or {}).get("band", ""),
                    "req_years": ms.get("req_years", 0) if ms else 0,
                    "score": ms["score"] if ms else None,
                    "conf": ms.get("conf") if ms else None,
                    "visa": visa, "title_match": tmatch,
                    "tier": job_tier(ms["score"] if ms else None, ms, visa, tmatch),
                    "rank": rank_score(ms["score"] if ms else None,
                                       ms.get("conf") if ms else None, visa, tmatch, days),
                    "hit": ms["hit"] if ms else [],
                    "must_miss": (ms.get("must_miss") or ms.get("miss", [])) if ms else [],
                    "nice_miss": ms.get("nice_miss", []) if ms else [],
                    "flags": ms.get("flags", []) if ms else [],
                })
        # merge in aggregator (Adzuna/Reed) jobs
        for u, j in state["agg_jobs"].items():
            if (u in state["hidden"]) != show_hidden:
                continue
            if excl_re and excl_re.search((j.get("title") or "").lower()):
                continue
            region = j.get("region", "uk")
            if state["uk_only"] and region == "other":
                continue
            fs = j.get("first_seen", "")
            try:
                days = (today - date.fromisoformat(fs)).days if fs else None
            except Exception:
                days = None
            ms = state["match_scores"].get(u)
            visa = visa_certainty(ms, bool(j.get("sponsor")))
            tmatch = title_match(j.get("title", ""), user_tgt, user_acc,
                                 custom=custom_prof, keywords=kws)
            feed.append({
                "title": j.get("title", ""), "url": u,
                "location": j.get("location", ""), "company": j.get("company", ""),
                "curated": False, "llm": bool(j.get("llm")),
                "region": region, "country": j.get("country", ""),
                "level": j.get("level", "mid"), "via": "agg",
                "source": j.get("source", ""), "sponsor": bool(j.get("sponsor")),
                "first_seen": fs, "days": days,
                "njobs": None,
                "csize": (company_sizes.get(j.get("company", "")) or {}).get("band", ""),
                "req_years": ms.get("req_years", 0) if ms else 0,
                "score": ms["score"] if ms else None,
                "conf": ms.get("conf") if ms else None,
                "visa": visa, "title_match": tmatch,
                "tier": job_tier(ms["score"] if ms else None, ms, visa, tmatch),
                "rank": rank_score(ms["score"] if ms else None,
                                   ms.get("conf") if ms else None, visa, tmatch, days),
                "hit": ms["hit"] if ms else [],
                "must_miss": ms.get("must_miss", []) if ms else [],
                "nice_miss": ms.get("nice_miss", []) if ms else [],
                "flags": ms.get("flags", []) if ms else [],
            })
        # sort as the front end requested before truncating, so "high-score older jobs" aren't cut beyond the top 400 by time order
        sort = request.args.get("sort")
        if sort == "rank":   # recommended first: bucket by tier priority, then combined score descending within each bucket
            feed.sort(key=lambda x: (TIER_ORDER.get(x["tier"], 9), -(x.get("rank") or 0),
                                     x["first_seen"] or ""))
        elif sort == "score":
            feed.sort(key=lambda x: (x["score"] if x["score"] is not None else -1,
                                     x["first_seen"] or ""), reverse=True)
        else:
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
            "slug_failed": sum(1 for v in ats_cache.values() if v in _NO_ATS),
            "overrides": len(slug_overrides),
            "has_ai": sum(1 for r in results.values() if r["status"] == "has_ai"),
            "ai_jobs": len(feed),
            "llm_jobs": sum(1 for j in feed if j["llm"]),
            "via_jd_jobs": sum(1 for j in feed if j.get("via") == "jd"),
            "agg_jobs": sum(1 for j in feed if j.get("via") == "agg"),
            "agg_sponsor": sum(1 for j in feed if j.get("via") == "agg" and j.get("sponsor")),
            "uk_jobs": sum(1 for j in feed if j["region"] == "uk"),
            "eu_jobs": sum(1 for j in feed if j["region"] == "europe"),
            "new_jobs": sum(1 for j in feed if j["days"] is not None and j["days"] <= NEW_DAYS),
            "long_jobs": sum(1 for j in feed if j["days"] is not None and j["days"] >= LONG_RUNNING_DAYS),
            "jd_ok": jd_ok, "jd_fail": jd_fail,
            "jd_rate": (round(100 * jd_ok / (jd_ok + jd_fail)) if (jd_ok + jd_fail) else None),
            "hidden_jobs": len(state["hidden"]),
        }
        scan = dict(state["scan"])
        if scan["running"] and scan["done"]:
            rate = scan["done"] / max(time.time() - scan["started_ts"], 1)
            scan["eta_min"] = round((scan["total"] - scan["done"]) / max(rate, 0.01) / 60)
            scan["rate"] = round(rate, 1)   # companies/sec — watch it when tuning WORKABLE_CONC to see if it got faster
            scan["rl"] = _recent_rl()       # rate-limit (429/503) count over the last 2 minutes — the brake light for tuning
        try:
            limit = max(50, min(int(request.args.get("limit", 400)), 5000))
        except ValueError:
            limit = 400
        resume = state.get("resume")
        return jsonify({
            "keywords": state["keywords"], "uk_only": state["uk_only"],
            "exclude_keywords": state["exclude_keywords"],
            "target_titles": user_tgt or [],
            "acceptable_titles": user_acc or [],
            "excl_suggest": exclude_suggestions(),
            "auto_hours": state["auto_hours"], "exp_years": state["exp_years"],
            "counts": counts, "results": res_out, "feed": feed[:limit],
            "scan": scan, "match": dict(state["match"]), "agg": dict(state["agg"]),
            "size": dict(state["size"]), "social": dict(state["social"]),
            "has_api_keys": _has_agg_keys(),
            "has_llm": _llm_ready(),
            "llm_label": LLM_LABELS.get(_llm_provider()),
            "tracker": dict(state["tracker"]),
            "resume": ({"name": resume["name"], "updated": resume["updated"],
                        "keywords": resume["keywords"], "text": resume["text"]}
                       if resume else None),
            "consts": {"new_days": NEW_DAYS, "long_days": LONG_RUNNING_DAYS,
                       "level_labels": LEVEL_LABELS, "size_labels": SIZE_LABELS},
            "auth": _auth_info(),
        })


def _auth_info():
    """For the front end: current login name, whether multi-user, and today's remaining quota (for logout/quota display)."""
    uid = _uid()
    info = {"multiuser": MULTIUSER, "user": (uid if MULTIUSER else None)}
    if MULTIUSER and not (OWNER and uid == OWNER):
        with _usage_lock:
            u = _usage_today(uid)
            info["usage"] = {"llm": u["llm"], "llm_cap": LLM_DAILY_CAP,
                             "scan": u["scan"], "scan_cap": SCAN_DAILY_CAP}
    return info


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(force=True)
    with _lock:
        if "keywords" in data:  # empty list = see everything (no industry filter)
            state["keywords"] = [
                k.strip().lower() for k in data["keywords"] if k.strip()]
        if "exclude_keywords" in data:  # empty list = clear exclude words
            state["exclude_keywords"] = [
                k.strip().lower() for k in data["exclude_keywords"] if k.strip()]
        if "target_titles" in data:      # empty list = restore default target titles
            state["target_titles"] = [
                k.strip().lower() for k in data["target_titles"] if k.strip()]
        if "acceptable_titles" in data:
            state["acceptable_titles"] = [
                k.strip().lower() for k in data["acceptable_titles"] if k.strip()]
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
        return jsonify({"error": "A scan is already running"}), 409
    if n == 0:
        return jsonify({"error": "No companies to scan in this mode"}), 400
    return jsonify({"started": True, "total": n, "mode": mode})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    state["scan"]["stop"] = True
    ev = _scan_stops.get(_uid())
    if ev is not None:
        ev.set()  # interrupt only this user's in-flight probes (semaphore wait / backoff)
    return jsonify({"ok": True})


@app.route("/api/slug_override", methods=["POST"])
def api_slug_override():
    """Manually fix a company's ATS location (slug guessed wrong, or ones like Workday that must be configured by hand).
    body: {name, ats, slug}  or  {name, ats:"Workday", host, site}.
    slug/host both empty → delete that override.
    Owner-only in multi-user mode: overrides and the probe cache are shared."""
    denied = _admin_only()
    if denied:
        return denied
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Missing company name"}), 400
    key = name.lower()
    ats = (data.get("ats") or "").strip()
    slug = (data.get("slug") or "").strip()
    host = (data.get("host") or "").strip()
    site = (data.get("site") or "").strip()
    if not slug and not (host and site):
        slug_overrides.pop(key, None)
        _ats_pop(name)                     # clear the old cache so it's re-probed next time
    else:
        if ats not in OVERRIDE_ATS:
            return jsonify({"error": f"ats must be one of {sorted(OVERRIDE_ATS)}"}), 400
        if ats == "Workday":
            if not (host and site):
                return jsonify({"error": "Workday needs both host and site"}), 400
            slug_overrides[key] = {"ats": "Workday", "host": host, "site": site}
        else:
            if not slug:
                return jsonify({"error": f"{ats} needs a slug"}), 400
            slug_overrides[key] = {"ats": ats, "slug": slug}
        _ats_pop(name)                     # make the next scan use the override
    save_slug_overrides()
    save_ats_cache()
    return jsonify({"ok": True, "overrides": len(slug_overrides)})


@app.route("/api/aggregators", methods=["POST"])
def api_aggregators():
    """Trigger Adzuna/Reed aggregator search, sweeping UK-wide jobs by the user's keywords."""
    if not _has_agg_keys():
        return jsonify({"error": "No job-board API keys configured (Adzuna / Reed / Jooble / JSearch; see data/api_keys.json)"}), 400
    if state["agg"]["running"]:
        return jsonify({"error": "Job-board search is already running"}), 409
    _spawn(run_aggregators)
    return jsonify({"started": True,
                    "queries": len(state["keywords"][:AGG_MAX_QUERIES])})


@app.route("/api/social", methods=["POST"])
def api_social():
    """Fetch Hacker News 'Who is hiring' posts, filter by keywords and merge into the job stream. No API key needed."""
    if state["social"]["running"]:
        return jsonify({"error": "Hacker News fetch is already running"}), 409
    _spawn(run_social)
    return jsonify({"started": True})


@app.route("/api/company_size", methods=["POST"])
def api_company_size():
    """Use an LLM to batch-estimate employee size for companies with jobs; results are cached."""
    if not _llm_ready():
        return jsonify({"error": LLM_MISSING_MSG}), 400
    if state["size"]["running"]:
        return jsonify({"error": "Company-size estimation is already running"}), 409
    n = len(_size_targets())
    if not n:
        return jsonify({"error": "No new companies to size (all companies with jobs are done)"}), 400
    _spawn(run_company_size)
    return jsonify({"started": True, "total": n})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    # Multi-tenant: only clear "my" scan data; the company master directory is shared, not touched here
    # (otherwise one person clearing would wipe the 120k-company directory everyone shares).
    with _lock:
        state["results"] = {}
        state["jobs_seen"] = {}
        state["agg_jobs"] = {}
        state["match_scores"] = {}
    save_state()
    return jsonify({"ok": True})


EXPORT_HEADERS = ["Company", "Curated", "Job Title", "Level", "LLM", "Region",
                  "Location", "First Seen", "Days Online", "Long-running", "Job URL",
                  "ATS / Source", "Job Board", "LinkedIn People Search", "Hunter.io"]
LEVEL_LABELS_EN = {"grad": "Intern/Graduate", "junior": "Junior", "mid": "Mid",
                   "senior": "Senior", "staff": "Staff/Lead", "mgmt": "Management"}


def export_rows(today=None):
    """Rows for the Excel export: jobs from company hiring systems *and* from
    job boards / Hacker News (the latter were missing before)."""
    today = today or date.today()

    def days_of(fs):
        try:
            return (today - date.fromisoformat(fs)).days if fs else ""
        except Exception:
            return ""

    def region_label(region, country):
        return country or ("UK" if region in ("uk", "unknown") else region)

    with _lock:
        results = dict(state["results"])
        agg = dict(state["agg_jobs"])
        hidden = set(state["hidden"])
        curated = _curated_names()
    rows = []
    for name, r in results.items():
        links = build_links(name)
        for j in r.get("matched", []):
            if j.get("url") in hidden:
                continue
            fs = j.get("first_seen", "")
            days = days_of(fs)
            level = j.get("level") or classify_level(j.get("title"))
            region = j.get("region")
            country = j.get("country", "")
            if not region:
                region, country = classify_region(j.get("location"))
            rows.append([
                name, "*" if name in curated else "", j.get("title", ""),
                LEVEL_LABELS_EN.get(level, level), "*" if j.get("llm") else "",
                region_label(region, country),
                j.get("location", ""), fs, days,
                "Yes" if isinstance(days, int) and days >= LONG_RUNNING_DAYS else "",
                j.get("url", ""), r.get("ats") or "", r.get("board_url") or "",
                links["li_people"], links["hunter"],
            ])
    for u, j in agg.items():
        if u in hidden:
            continue
        company = j.get("company", "")
        links = build_links(company) if company else {"li_people": "", "hunter": ""}
        fs = j.get("first_seen", "")
        days = days_of(fs)
        level = j.get("level") or classify_level(j.get("title"))
        rows.append([
            company, "", j.get("title", ""),
            LEVEL_LABELS_EN.get(level, level), "*" if j.get("llm") else "",
            region_label(j.get("region", "unknown"), j.get("country", "")),
            j.get("location", ""), fs, days,
            "Yes" if isinstance(days, int) and days >= LONG_RUNNING_DAYS else "",
            u, j.get("source", ""), "",
            links["li_people"], links["hunter"],
        ])
    rows.sort(key=lambda x: (x[7] or ""), reverse=True)
    return rows


@app.route("/api/export")
def api_export():
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jobs"
    ws.append(EXPORT_HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in export_rows():
        ws.append(row)
    for col, w in zip("ABCDEFGHIJKLMNO", [28, 8, 45, 14, 6, 12, 25, 12, 11, 12, 60, 16, 40, 60, 40]):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"Job_Scout_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    load_users()  # load the multi-account table (data/users.json + legacy env var compat)
    load_all()
    seed_builtin_companies()  # preset big-name/AI employers (curated), scannable right from first launch
    if state["companies"] and not os.path.exists(COMPANIES_FILE):
        save_companies()  # save immediately when migrating from the old format, so the list isn't lost
    threading.Thread(target=auto_loop, daemon=True).start()
    port = int(os.environ.get("PORT", "5050"))
    # Bind to localhost only by default (safe); set HOST=0.0.0.0 in a container/server for external access.
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"\n  AI Job Scout running:  http://127.0.0.1:{port}")
    print("  This window is the website's server — keep it open while you use the tool (you can minimize it).\n")
    if FROZEN:  # auto-open the browser when the exe is double-clicked
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except OSError:
        # port already in use: most likely the tool is already running, so just open the page
        print(f"  Port {port} is already in use - the tool is probably already "
              "running in another window. Opening it in your browser.")
        webbrowser.open(f"http://127.0.0.1:{port}")
        time.sleep(3)
