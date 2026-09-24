# -*- coding: utf-8 -*-
"""Regression tests for the security / multi-tenant / i18n fixes.

Run:  pytest tests/   (from the repo root)
Nothing here touches the network, an LLM API, or the real data/ folder.
"""
import os
import re
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

CJK = re.compile(r"[一-鿿]")


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """Point every file the app writes at a temp dir."""
    monkeypatch.setattr(app, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(app, "COMPANIES_FILE", str(tmp_path / "companies.json"))
    monkeypatch.setattr(app, "SLUG_OVERRIDE_FILE", str(tmp_path / "slug_overrides.json"))
    monkeypatch.setattr(app, "ATS_CACHE_FILE", str(tmp_path / "ats_cache.json"))
    return tmp_path


@pytest.fixture
def multiuser(tmp_data, monkeypatch):
    """Multi-user mode with an owner and a normal user."""
    monkeypatch.setattr(app, "MULTIUSER", True)
    monkeypatch.setattr(app, "OWNER", "owner")
    salt, h = app._hash_pw("ownerpass")
    salt2, h2 = app._hash_pw("bobpass1")
    monkeypatch.setattr(app, "users", {
        "owner": {"salt": salt, "hash": h, "created": 0},
        "bob": {"salt": salt2, "hash": h2, "created": 0},
    })
    app._login_fails.clear()
    yield
    app._login_fails.clear()


def _client_as(user):
    c = app.app.test_client()
    with c.session_transaction() as s:
        s["user"] = user
    return c


# ------------------------------------------------------------ usernames

@pytest.mark.parametrize("name", ["..", "...", ".x", "-a", "_a", "a/b", "a", ""])
def test_username_rejects_traversal_and_odd_names(name, tmp_data, monkeypatch):
    monkeypatch.setattr(app, "users", {})
    ok, _ = app.create_user(name, "secret123")
    assert not ok


@pytest.mark.parametrize("name", ["ab", "alice", "bob.smith", "x_1-2"])
def test_username_accepts_normal_names(name, tmp_data, monkeypatch):
    monkeypatch.setattr(app, "users", {})
    ok, msg = app.create_user(name, "secret123")
    assert ok, msg


# ------------------------------------------------------------ login throttling

def test_login_is_throttled_after_repeated_failures(multiuser, monkeypatch):
    monkeypatch.setattr(app, "LOGIN_MAX_FAILS", 3)
    c = app.app.test_client()
    for _ in range(3):
        r = c.post("/login", data={"username": "bob", "password": "wrong"})
        assert r.status_code == 200
    # Even the right password is refused while throttled.
    r = c.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert r.status_code == 429
    # Other accounts are unaffected (key is ip + username).
    r = c.post("/login", data={"username": "owner", "password": "ownerpass"})
    assert r.status_code == 302


def test_login_rejects_protocol_relative_next(multiuser):
    c = app.app.test_client()
    r = c.post("/login?next=//evil.example",
               data={"username": "owner", "password": "ownerpass"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")
    assert "evil" not in r.headers["Location"]


def test_session_cookie_flags():
    assert app.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


# ------------------------------------------------------------ owner-only shared writes

def test_shared_company_list_is_owner_only(multiuser):
    r = _client_as("bob").post("/api/companies", json={"names": ["Acme Ltd"]})
    assert r.status_code == 403
    assert "Acme Ltd" not in app._shared_companies

    r = _client_as("owner").post("/api/companies", json={"names": ["Acme Ltd"]})
    assert r.status_code == 200
    app._shared_companies.pop("Acme Ltd", None)


def test_slug_override_is_owner_only(multiuser):
    r = _client_as("bob").post("/api/slug_override",
                               json={"name": "Acme", "ats": "Lever", "slug": "acme"})
    assert r.status_code == 403
    assert "acme" not in app.slug_overrides


def test_local_mode_is_admin():
    assert app._is_admin()


# ------------------------------------------------------------ per-scan stop

def test_stop_only_stops_my_scan():
    mine, theirs = threading.Event(), threading.Event()
    app._scan_stops.clear()
    app._scan_stops[app.LOCAL_USER] = mine
    app._scan_stops["someone-else"] = theirs
    try:
        r = app.app.test_client().post("/api/scan/stop")
        assert r.status_code == 200
        assert mine.is_set()
        assert not theirs.is_set()
    finally:
        app._scan_stops.clear()


def test_find_ats_honours_thread_bound_stop_event():
    """A stopped scan's worker must not cache 'none'; another thread is unaffected."""
    app.ats_cache.clear()
    noprobe = [("Fake", lambda slug: None)]
    ev = threading.Event()
    ev.set()

    def stopped_worker():
        app._tls.stop = ev
        try:
            app.find_ats("Stopped Ltd", probes=noprobe, max_slugs=1)
        finally:
            app._tls.stop = None

    t = threading.Thread(target=stopped_worker)
    t.start()
    t.join()
    assert "Stopped Ltd" not in app.ats_cache
    app.find_ats("Running Ltd", probes=noprobe, max_slugs=1)
    assert app.ats_cache["Running Ltd"] == "none"
    app.ats_cache.clear()


# ------------------------------------------------------------ LLM prompts follow the UI language

URL = "https://jobs.example.com/1"


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def fake(prompt, max_tokens=6000, lang="en"):
        calls.append((prompt, lang))
        return "ok"
    monkeypatch.setattr(app, "_llm_complete", fake)
    monkeypatch.setattr(app, "_llm_ready", lambda: True)
    app.state["resume"] = {"text": "Python developer " * 20, "keywords": ["python"],
                           "name": "cv.txt", "updated": "2026-01-01"}
    app.state["match_scores"][URL] = {"score": 50, "hit": ["python"],
                                      "must_miss": ["sql"], "nice_miss": [],
                                      "flags": [{"t": "要求 5+ 年经验", "lv": "warn"}],
                                      "n": 2}
    return calls


@pytest.mark.parametrize("fn", ["generate_job_advice", "generate_outreach"])
def test_job_prompts_default_to_english(fn, fake_llm):
    getattr(app, fn)(URL)
    prompt, lang = fake_llm[-1]
    assert lang == "en"
    assert not CJK.search(prompt)


def test_job_advice_prompt_translates_flags(fake_llm):
    app.generate_job_advice(URL, "en")
    assert "Requires 5+ years" in fake_llm[-1][0]


@pytest.mark.parametrize("fn", ["generate_job_advice", "generate_outreach"])
def test_job_prompts_follow_chinese_ui(fn, fake_llm):
    getattr(app, fn)(URL, "zh")
    prompt, lang = fake_llm[-1]
    assert lang == "zh"
    assert CJK.search(prompt)


def test_resume_advice_prompt_language(fake_llm):
    report = {"n_scored": 3, "gaps": [{"skill": "sql", "jobs": 2, "near": 1}],
              "have": ["python"], "freeform": []}
    app.generate_resume_advice(report)
    assert not CJK.search(fake_llm[-1][0])
    app.generate_resume_advice(report, "zh")
    assert "中文" in fake_llm[-1][0]


def test_system_prompt_is_industry_neutral():
    assert "AI/ML" not in app.RESUME_SYS["en"]
    assert "AI/ML" not in app.RESUME_SYS["zh"]


def test_job_advice_endpoint_caches_per_language(fake_llm):
    c = app.app.test_client()
    assert c.post("/api/job_advice", json={"url": URL}).status_code == 200
    assert c.post("/api/job_advice", json={"url": URL, "lang": "zh"}).status_code == 200
    assert URL in app.state["advice"]
    assert app._cache_key(URL, "zh") in app.state["advice"]
    assert [lang for _, lang in fake_llm] == ["en", "zh"]


def test_llm_needs_resume_error_is_english():
    r = app.app.test_client().post("/api/job_advice", json={"url": URL})
    assert r.status_code == 400
    assert not CJK.search(r.get_json()["error"])


# ------------------------------------------------------------ export

def test_export_has_english_headers_and_job_board_rows():
    assert not any(CJK.search(h) for h in app.EXPORT_HEADERS)
    app.state["results"]["Acme"] = {
        "status": "has_ai", "ats": "Lever", "board_url": "https://jobs.lever.co/acme",
        "matched": [{"title": "Data Scientist", "url": "https://a/1",
                     "location": "London", "first_seen": "2026-01-01",
                     "region": "uk", "country": "UK", "level": "mid"}]}
    app.state["agg_jobs"]["https://b/2"] = {
        "company": "Beta", "title": "ML Engineer", "url": "https://b/2",
        "location": "Leeds", "source": "Reed", "region": "uk", "country": "UK",
        "level": "senior", "first_seen": "2026-01-02"}
    rows = app.export_rows()
    urls = {r[10] for r in rows}
    assert urls == {"https://a/1", "https://b/2"}
    assert all(len(r) == len(app.EXPORT_HEADERS) for r in rows)
    assert not any(CJK.search(str(c)) for r in rows for c in r)


def test_size_labels_are_english():
    assert not any(CJK.search(v) for v in app.SIZE_LABELS.values())


# ------------------------------------------------------------ eval script

def test_eval_script_runs(monkeypatch, capsys):
    """eval/run_eval.py used to crash (it read app._CANON after the scoring code
    moved to matching.py). It must run end to end on the seed set."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "eval", "run_eval.py")
    spec = importlib.util.spec_from_file_location("run_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["run_eval.py"])
    assert mod.main() == 0
    assert "Spearman" in capsys.readouterr().out
