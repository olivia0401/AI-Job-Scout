# Give every test a fresh, disk-independent user state.
#
# `app.state` is a proxy onto the module-global `user_states[<current user>]`
# dict, which otherwise persists for the whole test session and is lazily
# populated from data/state.json on first access. Without a reset, one test's
# writes (or whatever happens to be on disk) leak into the next, which made
# ordering/hash-seed-dependent failures possible (e.g. test_resume_gap_report).
#
# This autouse fixture installs a clean blank_state() for the active user before
# each test, so tests are isolated and never touch the developer's real data.

import pytest

import app


@pytest.fixture(autouse=True)
def isolate_state():
    app._ctx_user.set(None)
    app.user_states.clear()
    app.user_states[app._uid()] = app.blank_state()
    yield
    app.user_states.clear()
