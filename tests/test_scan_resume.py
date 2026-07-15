# -*- coding: utf-8 -*-
"""深度补扫的「可中断续跑」逻辑。

运行:  pytest tests/          （在仓库根目录）
背景:  深度补扫过去把「深度探过但仍没招聘页」的公司写回 "none"，而选公司的依据
       又是 == "none"，导致每次都从头重扫十几万家。现在改成写 "none_deep"，
       深度补扫只挑 "none"（还没深度探过的）→ 停掉后能真正接着跑。
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


def _noprobe():
    """一组永远探不到招聘页的探测器。"""
    return [("Fake", lambda slug: None)]


def setup_function():
    app.ats_cache.clear()
    app._stop_event.clear()


def test_normal_probe_marks_none():
    """普通探测没找到 → "none"（深度补扫之后还会再试它）。"""
    assert app.find_ats("Acme Ltd", probes=_noprobe(), max_slugs=1) is None
    assert app.ats_cache["Acme Ltd"] == "none"


def test_deep_probe_marks_none_deep():
    """深度补扫(force)也没找到 → "none_deep"，下次深度补扫不再重复扫。"""
    app.ats_cache["Acme Ltd"] = "none"
    assert app.find_ats("Acme Ltd", probes=_noprobe(), max_slugs=1, force=True) is None
    assert app.ats_cache["Acme Ltd"] == "none_deep"


def test_deep_scan_skips_already_deep_probed():
    """选公司的依据只含 "none"：深度探过的 none_deep 被排除 → 续跑而不是从头。"""
    app.ats_cache.update({"A": "none", "B": "none_deep",
                          "C": {"ats": "Greenhouse", "slug": "c"}})
    comps = ["A", "B", "C"]
    deep_targets = [n for n in comps if app.ats_cache.get(n) == "none"]
    assert deep_targets == ["A"]          # B 已深度探过、C 已找到，都不重扫


def test_normal_scan_does_not_reprobe_none_deep():
    """非 force 的普通扫描遇到 none_deep 直接跳过，不浪费请求。"""
    app.ats_cache["Zed"] = "none_deep"
    calls = []

    def probe(slug):
        calls.append(slug)
        return None

    assert app.find_ats("Zed", probes=[("Fake", probe)], max_slugs=1) is None
    assert calls == []                    # 完全没发起探测


def test_none_deep_still_counts_as_no_board():
    """none / none_deep 都表示"没有招聘页"，统计与展示要一视同仁。"""
    assert "none" in app._NO_ATS and "none_deep" in app._NO_ATS


def test_stopped_probe_is_not_marked_none():
    """中途按停止 → 按"未知"处理，不写缓存，下次会重新探测（不会误判成没有）。"""
    app._stop_event.set()
    try:
        app.find_ats("Halted Ltd", probes=_noprobe(), max_slugs=1)
        assert "Halted Ltd" not in app.ats_cache
    finally:
        app._stop_event.clear()


# ------------------------------------------------ 落盘不能被并发写打死（"闪退"）

def test_save_ats_cache_survives_concurrent_writes(tmp_path, monkeypatch):
    """复现线上事故：扫描线程边写 ats_cache，save_ats_cache 边序列化 →
    RuntimeError: dictionary changed size during iteration，把扫描线程打死。
    现在落盘先在锁内快照，必须扛得住并发写。"""
    monkeypatch.setattr(app, "ATS_CACHE_FILE", str(tmp_path / "ats_cache.json"))
    app.ats_cache.update({f"seed{i}": "none" for i in range(3000)})

    errors, stop = [], threading.Event()

    def writer():                      # 模拟 32 个扫描线程持续写入
        i = 0
        while not stop.is_set():
            app._ats_set(f"live{i}", "none")
            i += 1

    threads = [threading.Thread(target=writer, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for _ in range(25):
            try:
                app.save_ats_cache()
            except Exception as e:     # noqa: BLE001 —— 任何异常都算回归
                errors.append(repr(e))
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)

    assert not errors, f"并发写时落盘崩了: {errors[:2]}"


def test_save_ats_cache_is_atomic(tmp_path, monkeypatch):
    """原子写：落盘后文件必须是完整可解析的 JSON（旧版 open(...,'w') 崩在半路
    会留下被截断的文件，load_all 静默当空 → 12 万家全量重扫）。"""
    dest = tmp_path / "ats_cache.json"
    monkeypatch.setattr(app, "ATS_CACHE_FILE", str(dest))
    app.ats_cache.update({"Acme": {"ats": "Greenhouse", "slug": "acme"},
                          "Beta": "none_deep"})
    app.save_ats_cache()
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["Acme"] == {"ats": "Greenhouse", "slug": "acme"}
    assert loaded["Beta"] == "none_deep"
