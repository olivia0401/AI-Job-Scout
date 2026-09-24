# -*- coding: utf-8 -*-
"""Company list import: auto-detects the official work-visa sponsor register CSV vs your own company list.

Run:        pytest tests/          (from the repo root)
Background: import used to require passing a server-local path to /api/import_register, with no UI entry,
            so new users couldn't do README step one; that endpoint could also probe which files exist on the server.
            Now everything goes through /api/upload, with the format detected from the header.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


REG_HEADER = ["Organisation Name", "Town/City", "County", "Type & Rating", "Route"]


def test_official_register_takes_only_skilled_worker():
    """Official register: keep only the Skilled Worker route; other visa routes are dropped."""
    rows = [
        ["Acme Ltd", "London", "Greater London", "Worker (A rating)", "Skilled Worker"],
        ["Gamma Co", "Leeds", "", "Temporary Worker", "Creative Worker"],
        ["Beta PLC", "Manchester", "", "Worker (A rating)", "Skilled Worker"],
    ]
    names, towns, tag = app._extract_companies(REG_HEADER, rows)
    assert tag == "register"
    assert names == ["Acme Ltd", "Beta PLC"]      # Creative Worker dropped
    assert towns == ["London", "Manchester"]      # Town/City carried along


def test_official_register_dedupes_case_insensitively():
    """A company often appears several times in the register (multiple ratings/routes); keep one."""
    rows = [
        ["Acme Ltd", "London", "", "", "Skilled Worker"],
        ["ACME LTD", "London", "", "", "Skilled Worker"],
        ["acme ltd", "London", "", "", "Skilled Worker"],
    ]
    names, _, tag = app._extract_companies(REG_HEADER, rows)
    assert tag == "register" and names == ["Acme Ltd"]


def test_plain_company_list_is_tagged_curated():
    """Own list: find the company-name column from the header and tag it curated."""
    names, towns, tag = app._extract_companies(
        ["Company", "Notes"], [["Foo Inc", "x"], ["Bar Ltd", "y"]])
    assert tag == "curated" and names == ["Foo Inc", "Bar Ltd"] and towns is None


def test_headerless_list_treats_every_row_as_a_company():
    """Bare list with no header: the first row is a company too and mustn't be swallowed as a header."""
    names, _, tag = app._extract_companies(["Zeta Ltd"], [["Eta Ltd"]])
    assert tag == "curated" and names == ["Zeta Ltd", "Eta Ltd"]


def test_formula_cells_are_skipped():
    """Leftover formulas from Excel exports (=SUM...) aren't treated as company names."""
    names, _, _ = app._extract_companies(["Company"], [["=SUM(A1:A2)"], ["Real Ltd"]])
    assert names == ["Real Ltd"]


def test_csv_upload_end_to_end_detects_register(monkeypatch, tmp_path):
    """Via the real /api/upload: an official register CSV is detected and stored as register."""
    monkeypatch.setattr(app, "COMPANIES_FILE", str(tmp_path / "companies.json"))
    app._shared_companies.clear()
    csv = ("Organisation Name,Town/City,County,Type & Rating,Route\n"
           "Acme Ltd,London,,Worker (A rating),Skilled Worker\n"
           "Gamma Co,Leeds,,Temporary Worker,Creative Worker\n")
    client = app.app.test_client()
    r = client.post("/api/upload", data={
        "file": (io.BytesIO(csv.encode("utf-8")), "sponsors.csv")})
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["kind"] == "register"
    assert body["parsed"] == 1 and body["count"] == 1
    assert "Acme Ltd" in app._shared_companies
    assert app._shared_companies["Acme Ltd"]["town"] == "London"
    assert "Gamma Co" not in app._shared_companies


def test_upload_without_file_is_rejected():
    client = app.app.test_client()
    r = client.post("/api/upload", data={})
    assert r.status_code == 400


def test_path_based_import_endpoint_is_gone():
    """The old /api/import_register took a server-local path and could probe server files — removed."""
    routes = {r.rule for r in app.app.url_map.iter_rules()}
    assert "/api/import_register" not in routes
