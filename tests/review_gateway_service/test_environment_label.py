"""PHONE-CORE PS-1: the environment label ("Staging") in the page header, from the gateway's settings."""

from __future__ import annotations

import re

import pytest
from review_gateway.config import ConfigError, load_settings
from review_gateway.static_files import STATIC_DIR

from tests.review_gateway_service.conftest import FakeClock, Rig

BADGE = re.compile(r'<h1 id="title">Review</h1>\s*<span id="environment">([^<]*)</span>')


def version(page: str) -> str:
    return re.search(r"/s/([0-9a-f]{12})/core/main\.js", page)[1]


def test_production_sets_no_label_and_its_page_shows_none(rig) -> None:
    page = rig.phone.get("/").text

    assert 'id="environment"' not in page and "{{ENVIRONMENT}}" not in page


def test_the_label_is_in_the_header_and_names_its_own_version(rig, tmp_path) -> None:
    labelled = Rig(tmp_path / "staging", FakeClock(), environment_label="Staging")
    try:
        page = labelled.phone.get("/").text
        assert BADGE.search(page)[1] == "Staging"
        # A changed label is a changed page, so an installed shell is refreshed.
        assert version(page) != version(rig.phone.get("/").text)
        listed = labelled.phone.get(f"/s/{version(page)}/files.json")
        assert listed.json()["version"] == version(page)
    finally:
        labelled.close()


def test_the_badge_is_styled_by_a_stylesheet_the_page_links() -> None:
    assert "#environment" in (STATIC_DIR / "features" / "status" / "status.css").read_text("utf-8")


def write(path, label: str):
    path.write_text(
        'data_dir = "d"\nmedia_dir = "m"\nsecret_file = "s"\nsync_host = "127.0.0.1"\n'
        f"environment_label = {label}\n",
        encoding="utf-8",
    )
    return path


def test_the_setting_is_read_from_the_gateways_config(tmp_path) -> None:
    assert load_settings(write(tmp_path / "c.toml", '"Staging"')).environment_label == "Staging"


@pytest.mark.parametrize("label", ['"<b>x</b>"', "'a\"b'", f'"{"x" * 25}"', "7", '"a\\nb"'])
def test_a_label_that_is_not_a_short_plain_word_is_refused(tmp_path, label) -> None:
    with pytest.raises(ConfigError, match="environment_label"):
        load_settings(write(tmp_path / "c.toml", label))
