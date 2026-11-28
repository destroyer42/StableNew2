"""PHONE-CORE PC-2: a feature's own rules live in ``features/<id>/<id>.css``; ``core.css`` keeps what is shared.

A class belongs to a feature when only that feature's modules put it on an element. A feature that has its own
stylesheet leaves no rule about such a class behind in ``core.css``.
"""

from __future__ import annotations

import re

from tests.review_gateway_service.conftest import GATEWAY_ROOT

STATIC = GATEWAY_ROOT / "review_gateway" / "static"
#: Where the page's modules write class names: ``class:``, ``className =`` and the tile's list.
WRITTEN = re.compile(r'(?:class:|className\s*=|const classes = \[)\s*(["`])(?P<text>.*?)\1')
TOGGLED = re.compile(r'classList\.(?:add|toggle|remove)\(\s*"([\w-]+)"')


def classes_in(source: str) -> set[str]:
    found = set(TOGGLED.findall(source))
    for match in WRITTEN.finditer(source):
        # In a template, ``${...}`` contributes only the strings written inside it.
        text = re.sub(
            r"\$\{[^}]*\}", lambda part: " ".join(re.findall(r'"([^"]*)"', part[0])), match["text"]
        )
        found.update(re.findall(r"[\w-]+", text))
    return found


def modules() -> list[tuple[str, str]]:
    """Each page module as ``(owner, source)``: the owner is ``core`` or a feature's id."""

    found = []
    for path in STATIC.rglob("*.js"):
        parts = path.relative_to(STATIC).parts
        owner = parts[1] if parts[0] == "features" else "core"
        found.append((owner, path.read_text(encoding="utf-8")))
    return found


def own_classes(feature: str) -> set[str]:
    """Classes only this feature writes, and that nobody else even names in a string.

    Some class names are put together at run time, so a word another module mentions is treated as shared.
    """

    written = {owner: set() for owner, _source in modules()}
    named = {owner: set() for owner in written}
    for owner, source in modules():
        written[owner] |= classes_in(source)
        for literal in re.findall(r'"([^"\n]*)"|`([^`]*)`', source):
            named[owner].update(re.findall(r"[\w-]+", "".join(literal)))
    others = set().union(*(written[o] | named[o] for o in written if o != feature))
    return written[feature] - others


def selectors(name: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.DOTALL)
    return [part.strip() for group in re.findall(r"([^{}]+)\{", css) for part in group.split(",")]


def styled(selector: str) -> set[str]:
    return set(re.findall(r"\.([A-Za-z_][\w-]*)", selector))


def test_a_feature_with_a_stylesheet_leaves_none_of_its_own_rules_in_the_core() -> None:
    with_styles = [path.parent.name for path in STATIC.glob("features/*/*.css")]
    assert {"inbox", "rating"} <= set(with_styles)
    for feature in with_styles:
        own = own_classes(feature)
        assert own, feature
        left = [one for one in selectors("core/core.css") if styled(one) & own]
        assert not left, (feature, left)
