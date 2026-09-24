# -*- coding: utf-8 -*-
"""Unit tests for the resume-JD matching logic.

Run:    pytest tests/          (from the repo root)
Covers: skill synonyms / level detection / conservative scoring / required-preferred split /
        hit-miss accuracy / visa knockout / JD fetch-failure retry / resume parsing.
"""
import io
import os
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


# ---------------------------------------------------------------- Skill detection
def test_extract_skills_basic():
    got = app.extract_skills("Strong Python and PyTorch, plus SQL")
    assert {"python", "pytorch", "sql"} <= got


def test_extract_skills_canonicalizes_synonyms():
    # synonyms should merge to the canonical name so a skill isn't counted twice
    assert "scikit-learn" in app.extract_skills("experience with sklearn")
    assert "kubernetes" in app.extract_skills("deploy on k8s")
    assert "nlp" in app.extract_skills("natural language processing background")
    assert "bedrock" in app.extract_skills("used aws bedrock in production")
    assert "weights & biases" in app.extract_skills("track runs in wandb")


def test_extract_skills_modern_llm_terms():
    txt = "LLMOps, guardrails, Azure OpenAI, model evaluation, prompt optimization"
    got = app.extract_skills(txt)
    assert {"llmops", "guardrails", "azure openai", "model evaluation",
            "prompt optimization"} <= got


def test_extract_skills_word_boundary_no_false_hit():
    # 'r' is a language in the vocab but must not match substrings like 'nearer'
    assert "r" not in app.extract_skills("we work nearer to the customer")
    # 'go' comes from the golang synonym and must not match 'going'
    assert "go" not in app.extract_skills("we are going to scale")


# ---------------------------------------------------------------- Level detection
@pytest.mark.parametrize("title,expected", [
    ("Senior Machine Learning Engineer", "senior"),
    ("Graduate AI Engineer", "grad"),
    ("ML Intern", "grad"),
    ("Staff Software Engineer", "staff"),
    ("Principal Research Scientist", "staff"),
    ("Head of Data Science", "mgmt"),
    ("Junior Data Analyst", "junior"),
    ("Machine Learning Engineer", "mid"),   # no level word → defaults to mid
])
def test_classify_level(title, expected):
    assert app.classify_level(title) == expected


# ---------------------------------------------------------------- Scoring
def test_title_only_is_conservative():
    """With no JD and only a title, the score should be low (confidence is only 5%)."""
    res = app.analyze_job("Machine Learning Engineer", "",
                          {"python", "pytorch"}, my_years=2, level="mid")
    assert res["score"] < 30
    assert res["n"] >= 1


def test_required_vs_preferred_split():
    """Skills in the nice-to-have section count as preferred, not as missing required."""
    jd = ("You must have Python and SQL. "
          "Nice to have: Kubernetes and Terraform experience.")
    res = app.analyze_job("Data Engineer", jd,
                          {"python"}, my_years=2, level="mid")
    # SQL is required and missing from the resume → must_miss; kubernetes is a missing preferred → nice_miss
    assert "sql" in res["must_miss"]
    assert "kubernetes" in res["nice_miss"]
    assert "kubernetes" not in res["must_miss"]


def test_hit_and_miss_are_accurate():
    jd = "Requires Python, PyTorch and AWS for production ML systems."
    res = app.analyze_job("ML Engineer", jd,
                          {"python", "pytorch"}, my_years=3, level="mid")
    assert "python" in res["hit"] and "pytorch" in res["hit"]
    assert "aws" in res["must_miss"]
    assert "aws" not in res["hit"]


def test_full_match_scores_higher_than_partial():
    jd = "We need Python, PyTorch, LLM and RAG experience. " * 15
    full = app.analyze_job("ML Engineer", jd,
                           {"python", "pytorch", "llm", "rag"}, 3, "mid")
    partial = app.analyze_job("ML Engineer", jd,
                              {"python"}, 3, "mid")
    assert full["score"] > partial["score"]
    assert full["score"] >= 60


def test_no_sponsorship_applies_penalty():
    jd = ("Python PyTorch LLM RAG. "
          "Unfortunately we are unable to offer visa sponsorship for this role. ") * 8
    kws = {"python", "pytorch", "llm", "rag"}
    penalized = app.analyze_job("ML Engineer", jd, kws, 3, "mid")
    clean = app.analyze_job(
        "ML Engineer", jd.replace("unable to offer visa sponsorship for this role", "offer great benefits"),
        kws, 3, "mid")
    assert penalized["score"] == max(clean["score"] - 40, 0)
    assert any("签证" in f["t"] for f in penalized["flags"])


def test_years_requirement_flagged_when_below_threshold():
    jd = "We require at least 8 years of experience in Python and machine learning. " * 5
    res = app.analyze_job("Senior ML Engineer", jd,
                          {"python", "machine learning"}, my_years=2, level="senior")
    assert any("年经验" in f["t"] for f in res["flags"])


def test_level_match_affects_score():
    """With equal skill coverage, a job fitting the candidate's years should score no lower than a bad mismatch."""
    jd = "Python and machine learning required. " * 10
    kws = {"python", "machine learning"}
    grad_fit = app.analyze_job("Graduate ML Engineer", jd, kws, my_years=0, level="grad")
    grad_misfit = app.analyze_job("Graduate ML Engineer", jd, kws, my_years=10, level="grad")
    assert grad_fit["score"] >= grad_misfit["score"]


def test_empty_jd_and_no_skills_not_stored():
    """No JD and no title skills → n=0, so run_match skips storing it."""
    res = app.analyze_job("Business Development Manager", "",
                          {"python"}, my_years=2, level="mid")
    assert res["n"] == 0


# ---------------------------------------------------------------- JD fetch retry
def test_should_retry_logic():
    now = time.time()
    assert app._should_retry("u1", {}) is True                 # never failed → fetch
    assert app._should_retry("u1", {"u1": now}) is False        # just failed → skip
    assert app._should_retry("u1", {"u1": now - app.FAIL_RETRY_SEC - 10}) is True  # over 24h → retry
    assert app._should_retry("u1", {"u1": "garbage"}) is True   # bad data → retry defensively


# ---------------------------------------------------------------- Job recall: match_job
KWS = [k.lower() for k in app.DEFAULT_KEYWORDS]


def test_match_job_title_direct():
    assert app.match_job("Senior Machine Learning Engineer", "", KWS) == "title"
    assert app.match_job("AI Engineer", "", KWS) == "title"


def test_match_job_broad_title_confirmed_by_jd():
    # title lacks AI, but it's engineering and the JD body is really about AI (≥2 hits) → recalled via JD
    via = app.match_job(
        "Software Engineer, Search",
        "You will build LLM retrieval systems and fine-tune large language models "
        "for production nlp workloads.", KWS)
    assert via == "jd"


def test_match_job_boilerplate_mention_rejected():
    # company blurb mentions AI in passing (1 hit) → not recalled; the biggest source of false hits
    assert app.match_job(
        "Senior Software Engineer",
        "We are an artificial intelligence powered fintech. You will build "
        "microservices in Go and own our Kubernetes platform.", KWS) is None


def test_match_job_blacklisted_title_not_widened():
    # blacklisted titles (presales/support/QA etc.) skip the wide JD path, even if the JD is all AI
    jd = ("Our machine learning platform serves LLM workloads. You will demo "
          "our generative ai products to customers.")
    assert app.match_job("Solutions Architect", jd, KWS) is None
    assert app.match_job("QA Automation Engineer", jd, KWS) is None
    assert app.match_job("Support Engineer", jd, KWS) is None
    # but the same JD with an R&D title is still recalled
    assert app.match_job("Platform Engineer", jd, KWS) == "jd"


def test_classify_region_empty_location_is_unknown_not_uk():
    # no location ≠ UK: must stay separate, or the "UK" filter fills up with location-less jobs
    assert app.classify_region("") == ("unknown", "")
    assert app.classify_region(None) == ("unknown", "")
    assert app.classify_region("London, UK")[0] == "uk"
    assert app.classify_region("Berlin")[0] == "europe"


def test_visa_certainty_layers():
    no = {"flags": [{"t": "JD 声明不担保签证", "lv": "warn"}]}
    yes = {"flags": [{"t": "明确提供签证担保", "lv": "good"}]}
    assert app.visa_certainty(no, True) == "no"        # JD says no sponsorship > register
    assert app.visa_certainty(yes, False) == "yes"
    assert app.visa_certainty({}, True) == "register"  # on register but the JD is silent
    assert app.visa_certainty(None, False) == "uncertain"


def test_job_tier_layers():
    assert app.job_tier(80, {}, "register") == "strong"
    assert app.job_tier(45, {}, "register") == "maybe"
    assert app.job_tier(20, {}, "register") == "weak"
    assert app.job_tier(None, None, "register") == "lowconf"           # not scored
    lowconf = {"flags": [{"t": "未抓到 JD，仅按标题估分", "lv": "warn"}]}
    assert app.job_tier(65, lowconf, "register") == "lowconf"          # title-only estimate
    assert app.job_tier(90, {}, "no") == "risk"                        # no sponsorship
    clear = {"flags": [{"t": "需安全许可/国籍要求", "lv": "warn"}]}
    assert app.job_tier(90, clear, "register") == "risk"


def test_title_match_direction():
    # Target roles
    assert app.title_match("Machine Learning Engineer") == "target"
    assert app.title_match("Senior LLM Engineer") == "target"
    assert app.title_match("NLP Engineer, Search") == "target"
    # Acceptable
    assert app.title_match("Applied Scientist") == "acceptable"
    assert app.title_match("Research Engineer") == "acceptable"
    assert app.title_match("Data Scientist") == "acceptable"
    # real relevant titles phrased every which way (caught by the token heuristic, not off_target)
    assert app.title_match("Software Engineer, Machine Learning") == "target"
    assert app.title_match("ML Platform Engineer") == "target"
    assert app.title_match("AI Platform Software Engineer") == "target"
    assert app.title_match("Search & Recommendations Engineer") == "target"
    # "research engineer" hits an acceptable phrase → acceptable (still relevant, can still be strong)
    assert app.title_match("NLP Research Engineer") in ("target", "acceptable")
    assert app.title_match("Research Scientist, Foundation Models") == "acceptable"
    assert app.title_match("Data Scientist, Personalisation") == "acceptable"
    # Wrong direction: skills may overlap, but not a target role
    assert app.title_match("IT Support Engineer") == "off_target"
    assert app.title_match("Solutions Architect") == "off_target"
    assert app.title_match("QA Engineer") == "off_target"
    assert app.title_match("Sales Executive") == "off_target"
    assert app.title_match("Frontend Engineer") == "off_target"    # has engineer but no AI domain word
    assert app.title_match("Financial Analyst") == "off_target"


def test_title_match_custom_industry_follows_user_words():
    """After switching industry, direction follows the user's own keywords/target roles,
    not the AI-only blacklist — otherwise finance/construction/mechanical would always be off_target."""
    # Finance: only keywords changed (no target roles) → a title hitting a search term is target
    fin_kws = ["accountant", "financial analyst", "audit", "tax"]
    assert app.title_match("Financial Analyst", None, None,
                           custom=True, keywords=fin_kws) == "target"
    assert app.title_match("Senior Auditor", None, None,
                           custom=True, keywords=fin_kws) == "off_target"  # audit≠auditor
    # Mechanical: always off_target via the blacklist in default AI mode; can match in custom mode
    assert app.title_match("Mechanical Engineer") == "off_target"          # AI profile
    assert app.title_match("Mechanical Engineer", ["mechanical engineer"], None,
                           custom=True) == "target"                         # user profile
    # custom mode no longer treats AI titles as relevant (finance users shouldn't be shown ML jobs)
    assert app.title_match("Machine Learning Engineer", None, None,
                           custom=True, keywords=fin_kws) == "off_target"
    # with explicit target roles, a title hitting only a search term (not a target) is acceptable
    assert app.title_match("Tax Manager", ["accountant"], None,
                           custom=True, keywords=fin_kws) == "acceptable"


def test_match_job_empty_keywords_keeps_everything():
    """Empty keywords = show all: every title is kept (returns 'all'), no industry filter."""
    assert app.match_job("Accountant", "", []) == "all"
    assert app.match_job("Site Manager", "we build bridges", []) == "all"
    assert app.match_job("Machine Learning Engineer", "", []) == "all"


def test_title_match_show_all_never_off_target():
    """In show-all mode (no keywords/targets) every job is target; nothing sinks."""
    assert app.title_match("Accountant", None, None,
                           custom=True, keywords=[]) == "target"
    assert app.title_match("Structural Engineer", None, None,
                           custom=True, keywords=[]) == "target"


def test_off_target_never_strong():
    """Core acceptance: however high the skill score, a wrong direction (off_target) must never be strong."""
    # IT Support + high skill overlap (python/docker/aws) → high score, but wrong direction → not strong
    assert app.job_tier(94, {}, "register", "off_target") == "weak"
    assert app.job_tier(90, {}, "yes", "off_target") == "weak"
    # only target/acceptable direction + high score → strong
    assert app.job_tier(94, {}, "register", "target") == "strong"
    assert app.job_tier(70, {}, "register", "acceptable") == "strong"
    # right direction but low score → maybe / weak (tiers unchanged)
    assert app.job_tier(45, {}, "register", "target") == "maybe"
    assert app.job_tier(20, {}, "register", "target") == "weak"
    # risk comes first; wrong direction next (sinks), never "needs review" even without a JD
    assert app.job_tier(94, {}, "no", "target") == "risk"
    assert app.job_tier(None, None, "register", "off_target") == "weak"    # off_target without JD → sinks
    assert app.job_tier(None, None, "register", "target") == "lowconf"     # right direction without JD → needs review
    lowconf = {"flags": [{"t": "未抓到 JD，仅按标题估分", "lv": "warn"}]}
    assert app.job_tier(70, lowconf, "register", "off_target") == "weak"   # off_target overrides lowconf
    # default tmatch=target keeps old callers backward compatible
    assert app.job_tier(80, {}, "register") == "strong"


def test_rank_score_orders_by_direction_and_visa():
    # at equal score: right direction + clear visa + new > wrong direction / unknown visa / old
    strong = app.rank_score(80, "high", "yes", "target", 0)
    offdir = app.rank_score(80, "high", "yes", "off_target", 0)
    novisa = app.rank_score(80, "high", "uncertain", "target", 0)
    old = app.rank_score(80, "high", "yes", "target", 200)
    assert strong > offdir       # wrong direction scores lower
    assert strong > novisa       # unknown visa scores lower
    assert strong > old          # old job scores lower
    # monotonic in score
    assert app.rank_score(90, "high", "register", "target", 5) > \
           app.rank_score(50, "high", "register", "target", 5)
    # range 0..100
    assert 0 <= app.rank_score(0, "low", "no", "off_target", 999) <= 100
    assert 0 <= app.rank_score(100, "high", "yes", "target", 0) <= 100


def test_exclude_suggestions_learns_from_hidden(monkeypatch):
    hidden = {f"u{i}": {"title": t} for i, t in enumerate([
        "Salesforce Developer", "Senior Salesforce Engineer", "Salesforce Architect",
        "Backend Engineer",  # words seen only once aren't suggested
    ])}
    monkeypatch.setitem(app.state, "hidden", hidden)
    monkeypatch.setitem(app.state, "exclude_keywords", [])
    sug = app.exclude_suggestions()
    assert "salesforce" in sug          # seen 3 times → learned
    assert "backend" not in sug         # seen once → not suggested
    assert "engineer" not in sug        # generic words are never suggested


def test_match_job_title_only_keywords_not_matched_in_body():
    # generic words like "recommendations" only count in titles; in the body they're filler
    assert app.match_job(
        "Backend Engineer",
        "You will make recommendations to stakeholders and present "
        "recommendations to the board.", KWS) is None


def test_match_job_broad_title_non_ai_jd_rejected():
    # engineering title but non-AI JD → not recalled, preserving precision
    assert app.match_job("Backend Engineer",
                         "We use Java, Spring and PostgreSQL.", KWS) is None


def test_match_job_non_tech_title_not_widened():
    # non-engineering/data/research titles skip the JD check path, even if the JD mentions ML
    assert app.match_job("Marketing Manager",
                         "We love machine learning campaigns.", KWS) is None


def test_match_job_no_jd_is_conservative():
    # when the JD can't be fetched (e.g. Workable/SmartRecruiters) only the title is used
    assert app.match_job("Data Engineer", "", KWS) is None


def test_match_job_new_keywords_catch_ml_adjacent_titles():
    assert app.match_job("Backend Engineer, Recommendations", "", KWS) == "title"
    assert app.match_job("Applied Scientist", "", KWS) == "title"


# ---------------------------------------------------------------- New platform integrations
class _FakeResp:
    def __init__(self, status=200, text="", content=b"", payload=None):
        self.status_code = status
        self.text = text
        self.content = content
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self._r = resp

    def get(self, *a, **k):
        return self._r

    def post(self, *a, **k):
        return self._r


PERSONIO_XML = (
    b'<?xml version="1.0"?><workzag-jobs><position>'
    b'<id>42</id><name>ML Engineer</name><office>London</office>'
    b'<jobDescriptions><jobDescription><value>We build LLM and RAG systems</value>'
    b'</jobDescription></jobDescriptions></position></workzag-jobs>')


def test_probe_personio(monkeypatch):
    resp = _FakeResp(200, PERSONIO_XML.decode(), PERSONIO_XML)
    monkeypatch.setattr(app, "_session", lambda: _FakeSession(resp))
    r = app.probe_personio("acme")
    assert r and len(r["jobs"]) == 1
    j = r["jobs"][0]
    assert j["title"] == "ML Engineer" and j["location"] == "London"
    assert "llm" in j["desc"].lower()
    assert j["url"].endswith("/job/42")


def test_probe_workday(monkeypatch):
    payload = {"total": 2, "jobPostings": [
        {"title": "ML Engineer", "externalPath": "/job/London/ML_JR1", "locationsText": "London"},
        {"title": "Data Scientist", "externalPath": "/job/Leeds/DS_JR2", "locationsText": "Leeds"}]}
    monkeypatch.setattr(app, "_session", lambda: _FakeSession(_FakeResp(200, payload=payload)))
    r = app.probe_workday_tenant("acme.wd1.myworkdayjobs.com", "External")
    assert r and len(r["jobs"]) == 2
    assert r["jobs"][0]["url"] == \
        "https://acme.wd1.myworkdayjobs.com/en-US/External/job/London/ML_JR1"


def test_workday_needs_host_and_site():
    assert app.probe_workday_tenant("", "External") is None
    assert app.probe_workday_tenant("acme.wd1.myworkdayjobs.com", "") is None


def test_norm_company_crossref():
    # suffix differences shouldn't block matching against the sponsor register
    assert app._norm_company("Acme AI Ltd") == app._norm_company("Acme AI Limited")
    assert app._norm_company("DeepMind Technologies Limited") == "deepmind"


def test_run_aggregators_filters_and_crossrefs(monkeypatch):
    monkeypatch.setattr(app, "api_keys", {"adzuna_app_id": "x", "adzuna_app_key": "y"})
    # aggregator queries follow the user's keywords; no more hard-coded AGG_QUERIES
    monkeypatch.setitem(app.state, "keywords", ["machine learning"])
    monkeypatch.setattr(app, "_atomic_write", lambda *a: None)  # don't touch the real desc_cache
    monkeypatch.setattr(app, "search_reed", lambda q: [])
    monkeypatch.setattr(app, "search_adzuna", lambda q, pages=2: [
        {"company": "Acme AI Limited", "title": "Machine Learning Engineer",
         "url": "http://a/1", "location": "London", "desc": "We build LLM systems",
         "source": "Adzuna"},
        {"company": "Random Corp", "title": "Chef", "url": "http://a/2",
         "location": "Leeds", "desc": "cooking", "source": "Adzuna"}])
    monkeypatch.setitem(app.state, "companies", {"Acme AI Ltd": {"tags": ["register"], "town": ""}})
    monkeypatch.setitem(app.state, "agg_jobs", {})
    monkeypatch.setattr(app, "save_state", lambda: None)
    app.run_aggregators()
    aj = app.state["agg_jobs"]
    assert len(aj) == 1                       # Chef is filtered out as non-AI
    j = next(iter(aj.values()))
    assert j["sponsor"] is True               # Acme AI Limited ↔ Acme AI Ltd matched
    assert j["llm"] is True and j["source"] == "Adzuna"


def test_search_adzuna_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(app, "api_keys", {})
    assert app.search_adzuna("machine learning") == []
    assert app.search_reed("machine learning") == []


# ---------------------------------------------------------------- Resume improvement suggestions
def test_mine_frequent_terms_catches_out_of_vocab():
    descs = [
        "Strong experience with Kubernetes and Terraform",
        "proficiency in Kubernetes is required",
        "hands-on experience with Kubernetes in production",
    ]
    terms = dict(app.mine_frequent_terms(descs, known={"terraform"}))
    # kubernetes recurs and isn't in known → should be mined, with the highest count
    assert any("kubernetes" in t for t in terms)


def test_mine_frequent_terms_skips_known():
    terms = dict(app.mine_frequent_terms(
        ["experience with python and pytorch"], known={"python", "pytorch"}))
    assert "python" not in terms and "pytorch" not in terms


def test_resume_gap_report_ranks_by_impact(monkeypatch):
    monkeypatch.setitem(app.state, "resume",
                        {"text": "ML engineer with Python", "keywords": ["python"],
                         "name": "cv", "updated": "2026-07-07"})
    monkeypatch.setitem(app.state, "match_scores", {
        "u1": {"score": 45, "hit": ["python"], "must_miss": ["rag", "kubernetes"],
               "nice_miss": ["aws"], "flags": [], "n": 4},
        "u2": {"score": 60, "hit": ["python"], "must_miss": ["rag"],
               "nice_miss": [], "flags": [], "n": 2},
        "u3": {"score": 80, "hit": ["python", "rag"], "must_miss": ["mlops"],
               "nice_miss": [], "flags": [], "n": 3},
    })
    monkeypatch.setattr(app, "load_desc_cache", lambda: {})
    r = app.resume_gap_report()
    assert r["ready"] and r["n_scored"] == 3
    # rag is missing from 2 jobs (both mid-match) → ranked first
    assert r["gaps"][0]["skill"] == "rag" and r["gaps"][0]["jobs"] == 2
    assert r["gaps"][0]["near"] == 2
    assert "python" in r["have"]


def test_resume_gap_report_no_resume(monkeypatch):
    monkeypatch.setitem(app.state, "resume", None)
    assert app.resume_gap_report()["ready"] is False


# ---------------------------------------------------------------- Resume parsing
class _FakeUpload:
    def __init__(self, filename, data):
        self.filename = filename
        self._data = data

    def read(self):
        return self._data


def test_extract_resume_text_txt():
    txt = "Machine Learning Engineer with Python and PyTorch."
    out = app.extract_resume_text(_FakeUpload("cv.txt", txt.encode("utf-8")))
    assert "python" in out.lower()


def test_extract_resume_text_txt_bom():
    # utf-8-sig adds BOM bytes; parsing should strip them so none remain in the text
    raw = "Data Scientist, SQL and Spark".encode("utf-8-sig")
    out = app.extract_resume_text(_FakeUpload("cv.txt", raw))
    assert "spark" in out.lower()
    assert not out.startswith("﻿")


def test_extract_resume_text_docx():
    buf = io.BytesIO()
    xml = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
           '<w:p><w:r><w:t>Python and Kubernetes</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>experience with LLM</w:t></w:r></w:p>'
           '</w:body></w:document>')
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    out = app.extract_resume_text(_FakeUpload("cv.docx", buf.getvalue()))
    low = out.lower()
    assert "python" in low and "kubernetes" in low and "llm" in low


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
