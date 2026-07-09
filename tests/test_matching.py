# -*- coding: utf-8 -*-
"""简历-JD 匹配逻辑的单元测试。

运行:  pytest tests/          （在仓库根目录）
覆盖:  技能同义词识别 / 职级识别 / 保守评分 / 必备-加分拆分 /
       hit-miss 正确性 / 签证淘汰项 / JD抓取失败重试 / 简历解析。
"""
import io
import os
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


# ---------------------------------------------------------------- 技能识别
def test_extract_skills_basic():
    got = app.extract_skills("Strong Python and PyTorch, plus SQL")
    assert {"python", "pytorch", "sql"} <= got


def test_extract_skills_canonicalizes_synonyms():
    # 同义词应归并到规范名，避免同一技能算两次
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
    # 'r' 是词表里的语言，但不能被 'nearer' 之类的子串误命中
    assert "r" not in app.extract_skills("we work nearer to the customer")
    # 'go' 来自 golang 同义词，不能被 'going' 误命中
    assert "go" not in app.extract_skills("we are going to scale")


# ---------------------------------------------------------------- 职级识别
@pytest.mark.parametrize("title,expected", [
    ("Senior Machine Learning Engineer", "senior"),
    ("Graduate AI Engineer", "grad"),
    ("ML Intern", "grad"),
    ("Staff Software Engineer", "staff"),
    ("Principal Research Scientist", "staff"),
    ("Head of Data Science", "mgmt"),
    ("Junior Data Analyst", "junior"),
    ("Machine Learning Engineer", "mid"),   # 无级别词 → 默认 mid
])
def test_classify_level(title, expected):
    assert app.classify_level(title) == expected


# ---------------------------------------------------------------- 评分
def test_title_only_is_conservative():
    """抓不到 JD、只有标题时，评分应偏低（置信度只占 5%）。"""
    res = app.analyze_job("Machine Learning Engineer", "",
                          {"python", "pytorch"}, my_years=2, level="mid")
    assert res["score"] < 30
    assert res["n"] >= 1


def test_required_vs_preferred_split():
    """nice-to-have 段内的技能算加分项，不进必备缺失。"""
    jd = ("You must have Python and SQL. "
          "Nice to have: Kubernetes and Terraform experience.")
    res = app.analyze_job("Data Engineer", jd,
                          {"python"}, my_years=2, level="mid")
    # SQL 是必备且简历缺 → 进 must_miss；kubernetes 是加分缺失 → 进 nice_miss
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
    """同样的技能覆盖，年限贴合职级的岗位应得分不低于严重错配的。"""
    jd = "Python and machine learning required. " * 10
    kws = {"python", "machine learning"}
    grad_fit = app.analyze_job("Graduate ML Engineer", jd, kws, my_years=0, level="grad")
    grad_misfit = app.analyze_job("Graduate ML Engineer", jd, kws, my_years=10, level="grad")
    assert grad_fit["score"] >= grad_misfit["score"]


def test_empty_jd_and_no_skills_not_stored():
    """既无 JD 又无标题技能 → n=0，run_match 会据此跳过存储。"""
    res = app.analyze_job("Business Development Manager", "",
                          {"python"}, my_years=2, level="mid")
    assert res["n"] == 0


# ---------------------------------------------------------------- JD抓取重试
def test_should_retry_logic():
    now = time.time()
    assert app._should_retry("u1", {}) is True                 # 从未失败 → 抓
    assert app._should_retry("u1", {"u1": now}) is False        # 刚失败 → 不抓
    assert app._should_retry("u1", {"u1": now - app.FAIL_RETRY_SEC - 10}) is True  # 超 24h → 重试
    assert app._should_retry("u1", {"u1": "garbage"}) is True   # 脏数据 → 容错重试


# ---------------------------------------------------------------- 岗位召回 match_job
KWS = [k.lower() for k in app.DEFAULT_KEYWORDS]


def test_match_job_title_direct():
    assert app.match_job("Senior Machine Learning Engineer", "", KWS) == "title"
    assert app.match_job("AI Engineer", "", KWS) == "title"


def test_match_job_broad_title_confirmed_by_jd():
    # 标题没写 AI，但属于工程类且 JD 正文实打实在讲 AI（≥2 次命中）→ 靠 JD 召回
    via = app.match_job(
        "Software Engineer, Search",
        "You will build LLM retrieval systems and fine-tune large language models "
        "for production nlp workloads.", KWS)
    assert via == "jd"


def test_match_job_boilerplate_mention_rejected():
    # 公司简介一嘴带过 AI（只命中 1 次）→ 不召回；这是误命中的最大来源
    assert app.match_job(
        "Senior Software Engineer",
        "We are an artificial intelligence powered fintech. You will build "
        "microservices in Go and own our Kubernetes platform.", KWS) is None


def test_match_job_blacklisted_title_not_widened():
    # 售前/支持/QA 等黑名单标题不走 JD 宽通道，哪怕 JD 全是 AI
    jd = ("Our machine learning platform serves LLM workloads. You will demo "
          "our generative ai products to customers.")
    assert app.match_job("Solutions Architect", jd, KWS) is None
    assert app.match_job("QA Automation Engineer", jd, KWS) is None
    assert app.match_job("Support Engineer", jd, KWS) is None
    # 但同样的 JD 配研发类标题依然召回
    assert app.match_job("Platform Engineer", jd, KWS) == "jd"


def test_classify_region_empty_location_is_unknown_not_uk():
    # 没写地点 ≠ 英国：必须单列，否则"英国"筛选会混入大量地点缺失的岗位
    assert app.classify_region("") == ("unknown", "")
    assert app.classify_region(None) == ("unknown", "")
    assert app.classify_region("London, UK")[0] == "uk"
    assert app.classify_region("Berlin")[0] == "europe"


def test_visa_certainty_layers():
    no = {"flags": [{"t": "JD 声明不担保签证", "lv": "warn"}]}
    yes = {"flags": [{"t": "明确提供签证担保", "lv": "good"}]}
    assert app.visa_certainty(no, True) == "no"        # JD 明说不担保 > 名单
    assert app.visa_certainty(yes, False) == "yes"
    assert app.visa_certainty({}, True) == "register"  # 名单内但 JD 未说明
    assert app.visa_certainty(None, False) == "uncertain"


def test_job_tier_layers():
    assert app.job_tier(80, {}, "register") == "strong"
    assert app.job_tier(45, {}, "register") == "maybe"
    assert app.job_tier(20, {}, "register") == "weak"
    assert app.job_tier(None, None, "register") == "lowconf"           # 没算分
    lowconf = {"flags": [{"t": "未抓到 JD，仅按标题估分", "lv": "warn"}]}
    assert app.job_tier(65, lowconf, "register") == "lowconf"          # 标题估分
    assert app.job_tier(90, {}, "no") == "risk"                        # 不担保
    clear = {"flags": [{"t": "需安全许可/国籍要求", "lv": "warn"}]}
    assert app.job_tier(90, clear, "register") == "risk"


def test_title_match_direction():
    # 目标岗位
    assert app.title_match("Machine Learning Engineer") == "target"
    assert app.title_match("Senior LLM Engineer") == "target"
    assert app.title_match("NLP Engineer, Search") == "target"
    # 可接受
    assert app.title_match("Applied Scientist") == "acceptable"
    assert app.title_match("Research Engineer") == "acceptable"
    assert app.title_match("Data Scientist") == "acceptable"
    # 写法千变万化的真实相关岗位（词元启发式兜住，别误判 off_target）
    assert app.title_match("Software Engineer, Machine Learning") == "target"
    assert app.title_match("ML Platform Engineer") == "target"
    assert app.title_match("AI Platform Software Engineer") == "target"
    assert app.title_match("Search & Recommendations Engineer") == "target"
    # "research engineer" 命中可接受短语 → acceptable（仍算对口、仍可进 strong）
    assert app.title_match("NLP Research Engineer") in ("target", "acceptable")
    assert app.title_match("Research Scientist, Foundation Models") == "acceptable"
    assert app.title_match("Data Scientist, Personalisation") == "acceptable"
    # 方向不对：技能可能重合，但不是目标岗位
    assert app.title_match("IT Support Engineer") == "off_target"
    assert app.title_match("Solutions Architect") == "off_target"
    assert app.title_match("QA Engineer") == "off_target"
    assert app.title_match("Sales Executive") == "off_target"
    assert app.title_match("Frontend Engineer") == "off_target"    # 有 engineer 但无 AI 方向词
    assert app.title_match("Financial Analyst") == "off_target"


def test_off_target_never_strong():
    """验收核心：技能分再高，方向不对(off_target)也绝不能进 strong。"""
    # IT Support + 高技能重合（python/docker/aws）→ 高分，但方向不对 → 不能 strong
    assert app.job_tier(94, {}, "register", "off_target") == "weak"
    assert app.job_tier(90, {}, "yes", "off_target") == "weak"
    # 目标/可接受方向 + 高分 → 才能 strong
    assert app.job_tier(94, {}, "register", "target") == "strong"
    assert app.job_tier(70, {}, "register", "acceptable") == "strong"
    # 方向对但分不够 → maybe / weak（分层照旧）
    assert app.job_tier(45, {}, "register", "target") == "maybe"
    assert app.job_tier(20, {}, "register", "target") == "weak"
    # 风险/低置信优先级高于方向判断
    assert app.job_tier(94, {}, "no", "target") == "risk"
    # 默认 tmatch=target，保持对旧调用的向后兼容
    assert app.job_tier(80, {}, "register") == "strong"


def test_rank_score_orders_by_direction_and_visa():
    # 同分下：方向对口 + 签证明确 + 新 > 方向不对 / 签证未知 / 旧
    strong = app.rank_score(80, "high", "yes", "target", 0)
    offdir = app.rank_score(80, "high", "yes", "off_target", 0)
    novisa = app.rank_score(80, "high", "uncertain", "target", 0)
    old = app.rank_score(80, "high", "yes", "target", 200)
    assert strong > offdir       # 方向不对分更低
    assert strong > novisa       # 签证未知分更低
    assert strong > old          # 老岗位分更低
    # 分数单调
    assert app.rank_score(90, "high", "register", "target", 5) > \
           app.rank_score(50, "high", "register", "target", 5)
    # 范围 0..100
    assert 0 <= app.rank_score(0, "low", "no", "off_target", 999) <= 100
    assert 0 <= app.rank_score(100, "high", "yes", "target", 0) <= 100


def test_exclude_suggestions_learns_from_hidden(monkeypatch):
    hidden = {f"u{i}": {"title": t} for i, t in enumerate([
        "Salesforce Developer", "Senior Salesforce Engineer", "Salesforce Architect",
        "Backend Engineer",  # 只出现一次的词不建议
    ])}
    monkeypatch.setitem(app.state, "hidden", hidden)
    monkeypatch.setitem(app.state, "exclude_keywords", [])
    sug = app.exclude_suggestions()
    assert "salesforce" in sug          # 出现 3 次 → 学到
    assert "backend" not in sug         # 出现 1 次 → 不建议
    assert "engineer" not in sug        # 通用词永不建议


def test_match_job_title_only_keywords_not_matched_in_body():
    # "recommendations" 这类泛词只在标题里算数，正文里是万能句式
    assert app.match_job(
        "Backend Engineer",
        "You will make recommendations to stakeholders and present "
        "recommendations to the board.", KWS) is None


def test_match_job_broad_title_non_ai_jd_rejected():
    # 工程类标题但 JD 与 AI 无关 → 不召回，保住精度
    assert app.match_job("Backend Engineer",
                         "We use Java, Spring and PostgreSQL.", KWS) is None


def test_match_job_non_tech_title_not_widened():
    # 非工程/数据/研究类标题不进 JD 确认通道，即使 JD 提到 ML
    assert app.match_job("Marketing Manager",
                         "We love machine learning campaigns.", KWS) is None


def test_match_job_no_jd_is_conservative():
    # 抓不到 JD（如 Workable/SmartRecruiters）时只走标题
    assert app.match_job("Data Engineer", "", KWS) is None


def test_match_job_new_keywords_catch_ml_adjacent_titles():
    assert app.match_job("Backend Engineer, Recommendations", "", KWS) == "title"
    assert app.match_job("Applied Scientist", "", KWS) == "title"


# ---------------------------------------------------------------- 新平台接入
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
    # 后缀差异不应妨碍与 sponsor 名单对齐
    assert app._norm_company("Acme AI Ltd") == app._norm_company("Acme AI Limited")
    assert app._norm_company("DeepMind Technologies Limited") == "deepmind"


def test_run_aggregators_filters_and_crossrefs(monkeypatch):
    monkeypatch.setattr(app, "api_keys", {"adzuna_app_id": "x", "adzuna_app_key": "y"})
    # 聚合器搜索词跟随用户关键词，不再有硬编码的 AGG_QUERIES
    monkeypatch.setitem(app.state, "keywords", ["machine learning"])
    monkeypatch.setattr(app, "_atomic_write", lambda *a: None)  # 不碰真实 desc_cache
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
    assert len(aj) == 1                       # Chef 被 AI 过滤掉
    j = next(iter(aj.values()))
    assert j["sponsor"] is True               # Acme AI Limited ↔ Acme AI Ltd 对齐
    assert j["llm"] is True and j["source"] == "Adzuna"


def test_search_adzuna_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(app, "api_keys", {})
    assert app.search_adzuna("machine learning") == []
    assert app.search_reed("machine learning") == []


# ---------------------------------------------------------------- 简历提升建议
def test_mine_frequent_terms_catches_out_of_vocab():
    descs = [
        "Strong experience with Kubernetes and Terraform",
        "proficiency in Kubernetes is required",
        "hands-on experience with Kubernetes in production",
    ]
    terms = dict(app.mine_frequent_terms(descs, known={"terraform"}))
    # kubernetes 反复出现且不在 known 里 → 应被挖出，且频次最高
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
    # rag 缺于 2 个岗位（都中等匹配）→ 排第一
    assert r["gaps"][0]["skill"] == "rag" and r["gaps"][0]["jobs"] == 2
    assert r["gaps"][0]["near"] == 2
    assert "python" in r["have"]


def test_resume_gap_report_no_resume(monkeypatch):
    monkeypatch.setitem(app.state, "resume", None)
    assert app.resume_gap_report()["ready"] is False


# ---------------------------------------------------------------- 简历解析
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
    # utf-8-sig 编码会加 BOM 字节，解析时应被剥掉，不残留在文本里
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
