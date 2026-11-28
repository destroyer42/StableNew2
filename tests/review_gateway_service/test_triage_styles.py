"""PHONE-CORE PC-2b: the swipe hint, the reason tags and the full-resolution viewer are styled by the triage's own file.

``test_feature_styles.py`` cannot see ``.tags``: other modules use the word, so it counts as shared there.
"""

from __future__ import annotations

from tests.review_gateway_service.test_feature_styles import selectors, styled

OWN = {"hint", "tags", "viewer", "viewer-status", "viewer-close"}


def test_the_triage_stylesheet_has_the_rules_for_what_only_the_triage_draws() -> None:
    moved = set().union(*(styled(one) for one in selectors("features/triage/triage.css")))
    assert moved == OWN | {"keep", "delete", "favorite"}  # the hint's three colours
    assert not [one for one in selectors("core/core.css") if styled(one) & OWN]
