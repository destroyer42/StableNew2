"""Shared fixtures for the P4-2A golden suite.

Every record built here gets an injected identity; nothing is masked afterwards.  Binary inputs come from
``tests/golden/assets`` (fixed bytes), because a digest recorded in a snapshot must not depend on the zlib build that
a platform's image library happens to encode with.
"""

from __future__ import annotations

import itertools
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline import reprocess_builder

ASSETS = Path(__file__).resolve().parent / "assets"


@pytest.fixture
def fixed_reprocess_ids(monkeypatch: pytest.MonkeyPatch) -> Callable[[], str]:
    """Make every ``ReprocessJobBuilder`` created during the test mint ``reprocess-1``, ``reprocess-2``, ...

    Several routes (SVD, Learning, masked edit, Review) construct their own builder, so the default identity function
    is the only seam; the module-level ``uuid`` name is what that default resolves at call time.
    """

    counter = itertools.count(1)

    def next_id() -> str:
        return f"reprocess-{next(counter)}"

    monkeypatch.setattr(
        reprocess_builder, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next_id()))
    )
    return next_id


@pytest.fixture
def copy_asset(tmp_path: Path) -> Callable[..., Path]:
    """Copy a fixed asset into the test's temp directory and return the copy."""

    def copy(name: str, target: str | None = None) -> Path:
        destination = tmp_path / (target or name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ASSETS / name, destination)
        return destination

    return copy


@pytest.fixture
def deterministic_uuid(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Replace the ``uuid`` module name inside the given modules with a counter (``0000...0001``, ``...0002``).

    Learning mints job and experiment identities with ``uuid.uuid4().hex`` at several construction sites; the module
    attribute is the only seam, and nothing in a snapshot is masked afterwards.
    """

    counter = itertools.count(1)

    def install(*modules: object) -> None:
        stub = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=f"{next(counter):032x}"))
        for module in modules:
            monkeypatch.setattr(module, "uuid", stub)

    return install
