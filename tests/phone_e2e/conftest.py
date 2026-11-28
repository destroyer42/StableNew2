"""Browser end-to-end tests of the phone review page (PHONE-CORE slice PC-0).

Headless Chromium (Playwright) with a phone's viewport and touch drives the real page against a real gateway on
loopback; the PC is played through the real sync API. They run only when asked, because they need Playwright and its
browser, which the application environment does not have:

    pip install --require-hashes -r tests/phone_e2e/requirements-e2e.txt
    python -m playwright install chromium
    STABLENEW_PHONE_E2E=1 python -m pytest tests/phone_e2e --confcutdir=tests/phone_e2e -p no:cacheprovider

``--confcutdir`` keeps the application's test conftest (Tk, ``src`` isolation fixtures) out of this run: these tests
import nothing from ``src``. In the ordinary census the files are not collected. CI runs them in the ``phone-e2e`` job.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ENABLED = os.environ.get("STABLENEW_PHONE_E2E") == "1"

if not ENABLED:
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(scope="session")
def playwright() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser(playwright: Any) -> Iterator[Any]:
    chromium = playwright.chromium.launch(headless=True)
    try:
        yield chromium
    finally:
        chromium.close()


@pytest.fixture(scope="session")
def phone_device(playwright: Any) -> dict[str, Any]:
    """A Pixel-class phone: viewport, device scale, mobile user agent and touch."""

    return dict(playwright.devices["Pixel 7"])


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[Any]:
    from tests.phone_e2e.harness import TestGateway

    instance = TestGateway(tmp_path / "gateway")
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def phone(browser: Any, phone_device: dict[str, Any], gateway: Any) -> Iterator[Any]:
    """A fresh phone (its own cookies and storage) on the test gateway, not yet paired."""

    context = browser.new_context(**phone_device, base_url=gateway.url)
    context.set_default_timeout(10_000)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield page
        assert not errors, f"the page threw: {errors}"
    finally:
        context.close()
