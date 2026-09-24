# -*- coding: utf-8 -*-
"""Stop-and-resume logic for the deep rescan.

Run:        pytest tests/          (from the repo root)
Background: the deep rescan used to write companies "deep-probed, still no careers page" back as "none",
            yet it selected companies by == "none", so each run rescanned 100k+ from scratch. Now it writes "none_deep",
            and the deep rescan picks only "none" (not yet deep-probed) → it truly resumes after a stop.
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


def _noprobe():
    """A set of probes that never find a careers page."""
    return [("Fake", lambda slug: None)]


def setup_function():
    app.ats_cache.clear()
    app._stop_event.clear()


def test_normal_probe_marks_none():
    """Normal probe finds nothing → "none" (the deep rescan will retry it later)."""
    assert app.find_ats("Acme Ltd", probes=_noprobe(), max_slugs=1) is None
    assert app.ats_cache["Acme Ltd"] == "none"


def test_deep_probe_marks_none_deep():
    """Deep rescan (force) also finds nothing → "none_deep", so the next deep rescan skips it."""
    app.ats_cache["Acme Ltd"] = "none"
    assert app.find_ats("Acme Ltd", probes=_noprobe(), max_slugs=1, force=True) is None
    assert app.ats_cache["Acme Ltd"] == "none_deep"


def test_deep_scan_skips_already_deep_probed():
    """Selection only takes "none": deep-probed none_deep is excluded → resume instead of restart."""
    app.ats_cache.update({"A": "none", "B": "none_deep",
                          "C": {"ats": "Greenhouse", "slug": "c"}})
    comps = ["A", "B", "C"]
    deep_targets = [n for n in comps if app.ats_cache.get(n) == "none"]
    assert deep_targets == ["A"]          # B already deep-probed, C already found: neither rescanned


def test_normal_scan_does_not_reprobe_none_deep():
    """A normal (non-force) scan skips none_deep outright, wasting no requests."""
    app.ats_cache["Zed"] = "none_deep"
    calls = []

    def probe(slug):
        calls.append(slug)
        return None

    assert app.find_ats("Zed", probes=[("Fake", probe)], max_slugs=1) is None
    assert calls == []                    # no probe issued at all


def test_none_deep_still_counts_as_no_board():
    """none / none_deep both mean "no careers page"; stats and display must treat them alike."""
    assert "none" in app._NO_ATS and "none_deep" in app._NO_ATS


def test_stopped_probe_is_not_marked_none():
    """Stopped midway → treated as "unknown": not cached, re-probed next time (not misjudged as none)."""
    app._stop_event.set()
    try:
        app.find_ats("Halted Ltd", probes=_noprobe(), max_slugs=1)
        assert "Halted Ltd" not in app.ats_cache
    finally:
        app._stop_event.clear()


# ------------------------------------------------ saving must survive concurrent writes (the "crash")

def test_save_ats_cache_survives_concurrent_writes(tmp_path, monkeypatch):
    """Reproduces a production incident: scan threads write ats_cache while save_ats_cache serialises it →
    RuntimeError: dictionary changed size during iteration, killing the scan thread.
    Saving now snapshots under a lock first and must survive concurrent writes."""
    monkeypatch.setattr(app, "ATS_CACHE_FILE", str(tmp_path / "ats_cache.json"))
    app.ats_cache.update({f"seed{i}": "none" for i in range(3000)})

    errors, stop = [], threading.Event()

    def writer():                      # simulate 32 scan threads writing continuously
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
            except Exception as e:     # noqa: BLE001 —— any exception counts as a regression
                errors.append(repr(e))
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)

    assert not errors, f"save crashed during concurrent writes: {errors[:2]}"


def test_save_ats_cache_is_atomic(tmp_path, monkeypatch):
    """Atomic write: the saved file must be complete, parseable JSON (the old open(...,'w') crashing midway
    left a truncated file that load_all silently treated as empty → full rescan of 120k companies)."""
    dest = tmp_path / "ats_cache.json"
    monkeypatch.setattr(app, "ATS_CACHE_FILE", str(dest))
    app.ats_cache.update({"Acme": {"ats": "Greenhouse", "slug": "acme"},
                          "Beta": "none_deep"})
    app.save_ats_cache()
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["Acme"] == {"ats": "Greenhouse", "slug": "acme"}
    assert loaded["Beta"] == "none_deep"
