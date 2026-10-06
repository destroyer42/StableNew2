"""Opt-in proof that a test module never reads or writes the operator's real GlobalPrompts store.

A module opts in by importing the fixture (no shared ``conftest`` involved)::

    from tests.helpers.global_prompt_isolation import real_global_prompt_store_untouched  # noqa: F401

The per-user data roots point at an empty temporary directory for the module's tests. Any default-resolved
``ConfigManager`` prompt read lazily creates its store, so the store existing afterwards proves a leak.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def real_global_prompt_store_untouched(tmp_path_factory, monkeypatch):
    user_data_root = tmp_path_factory.mktemp("real-user-data")
    monkeypatch.setenv("LOCALAPPDATA", str(user_data_root))
    monkeypatch.setenv("XDG_DATA_HOME", str(user_data_root))
    monkeypatch.setenv("HOME", str(user_data_root))
    monkeypatch.setenv("USERPROFILE", str(user_data_root))
    monkeypatch.delenv("STABLENEW_GLOBAL_PROMPT_DIR", raising=False)
    yield user_data_root
    leaked = sorted(str(p.relative_to(user_data_root)) for p in user_data_root.rglob("*"))
    assert not leaked, f"test reached the per-user GlobalPrompts store: {leaked}"
