# -*- coding: utf-8 -*-
"""导入公司名单：自动识别「官方工签赞助商 CSV」和「自己的公司清单」。

运行:  pytest tests/          （在仓库根目录）
背景:  过去导入只能靠 /api/import_register 传一个服务器本地路径，界面上没有入口，
       新用户按 README 第一步做不了；那个接口还能被用来探测服务器上有哪些文件。
       现在统一走 /api/upload 上传文件，格式由表头自动判断。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


REG_HEADER = ["Organisation Name", "Town/City", "County", "Type & Rating", "Route"]


def test_official_register_takes_only_skilled_worker():
    """官方名单：只要 Skilled Worker 这条路线，其它签证路线不进库。"""
    rows = [
        ["Acme Ltd", "London", "Greater London", "Worker (A rating)", "Skilled Worker"],
        ["Gamma Co", "Leeds", "", "Temporary Worker", "Creative Worker"],
        ["Beta PLC", "Manchester", "", "Worker (A rating)", "Skilled Worker"],
    ]
    names, towns, tag = app._extract_companies(REG_HEADER, rows)
    assert tag == "register"
    assert names == ["Acme Ltd", "Beta PLC"]      # Creative Worker 被剔除
    assert towns == ["London", "Manchester"]      # Town/City 一并带上


def test_official_register_dedupes_case_insensitively():
    """同一家公司在官方名单里常出现多次（多个 rating/路线），只留一条。"""
    rows = [
        ["Acme Ltd", "London", "", "", "Skilled Worker"],
        ["ACME LTD", "London", "", "", "Skilled Worker"],
        ["acme ltd", "London", "", "", "Skilled Worker"],
    ]
    names, _, tag = app._extract_companies(REG_HEADER, rows)
    assert tag == "register" and names == ["Acme Ltd"]


def test_plain_company_list_is_tagged_curated():
    """自己的清单：按表头找公司名那一列，打 curated 标签。"""
    names, towns, tag = app._extract_companies(
        ["Company", "Notes"], [["Foo Inc", "x"], ["Bar Ltd", "y"]])
    assert tag == "curated" and names == ["Foo Inc", "Bar Ltd"] and towns is None


def test_headerless_list_treats_every_row_as_a_company():
    """没有表头的裸清单：第一行也是公司名，不能被当表头吃掉。"""
    names, _, tag = app._extract_companies(["Zeta Ltd"], [["Eta Ltd"]])
    assert tag == "curated" and names == ["Zeta Ltd", "Eta Ltd"]


def test_formula_cells_are_skipped():
    """Excel 导出的公式残留（=SUM...）不当成公司名。"""
    names, _, _ = app._extract_companies(["Company"], [["=SUM(A1:A2)"], ["Real Ltd"]])
    assert names == ["Real Ltd"]


def test_csv_upload_end_to_end_detects_register(monkeypatch, tmp_path):
    """走真实的 /api/upload：官方名单 CSV 应被认出来并入库为 register。"""
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
    """老的 /api/import_register 收服务器本地路径，能被拿来探测服务器文件 —— 已移除。"""
    routes = {r.rule for r in app.app.url_map.iter_rules()}
    assert "/api/import_register" not in routes
