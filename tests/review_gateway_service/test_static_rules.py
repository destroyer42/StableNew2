"""Cheap checks on the page's own files (PHONE-CORE 2.2 and 5.2): no markup sinks, and a module graph that links.

A browser links the whole module graph before it runs any of it, so one wrong path or name would leave the page on its
fallback text.
"""

from __future__ import annotations

import posixpath
import re

from tests.review_gateway_service.conftest import GATEWAY_ROOT

STATIC = GATEWAY_ROOT / "review_gateway" / "static"
SINKS = re.compile(
    r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|\bFunction\(|createContextualFragment"
)
IMPORT = re.compile(
    r'^import\s+(?:\{(?P<names>[^}]*)\}|\*\s+as\s+(?P<alias>\w+))\s+from\s+"(?P<path>[^"]+)";',
    re.MULTILINE,
)
DECLARED = re.compile(r"^export\s+(?:async\s+function|function|const|class)\s+(\w+)", re.MULTILINE)
LISTED = re.compile(r"^export\s+\{(?P<names>[^}]*)\};", re.MULTILINE)


def sources(suffix: str) -> dict[str, str]:
    return {
        path.relative_to(STATIC).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(STATIC.rglob(f"*{suffix}"))
    }


def names(group: str, *, position: int) -> list[str]:
    """``a, b as c``: position 0 is the name on the module's side, -1 the name it is known by outside."""

    return [entry.split()[position] for entry in group.split(",") if entry.strip()]


def exports(source: str) -> set[str]:
    found = set(DECLARED.findall(source))
    for listed in LISTED.finditer(source):
        found.update(names(listed["names"], position=-1))
    return found


def test_the_page_has_modules_to_check() -> None:
    assert {"core/main.js", "core/store.js", "core/router.js"} <= set(sources(".js"))


def test_nothing_writes_markup_or_evaluates_text() -> None:
    for name, source in {**sources(".js"), **sources(".html")}.items():
        assert not SINKS.search(source), name


def test_markup_has_no_inline_handler_or_style() -> None:
    for name, source in sources(".html").items():
        assert not re.search(r"<[^>]*\s(on\w+|style)\s*=", source), name


def test_every_import_names_a_page_module_and_something_it_exports() -> None:
    modules = sources(".js")
    for name, source in modules.items():
        found = list(IMPORT.finditer(source))
        # A form the pattern does not know would go unchecked, so there must be none.
        assert len(found) == len(re.findall(r"^\s*import\b", source, re.MULTILINE)), name
        assert not re.search(r"\bimport\s*\(", source), name
        for match in found:
            path = match["path"]
            assert path.startswith(("./", "../")), (name, path)
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            assert target in modules, (name, path)  # also refuses a path that climbs out of static/
            if match["alias"]:
                used = set(re.findall(rf"(?<![\w.]){match['alias']}\.(\w+)", source))
            else:
                used = set(names(match["names"], position=0))
            assert used <= exports(modules[target]), (name, path, used - exports(modules[target]))


def test_no_module_exports_a_binding_that_changes() -> None:
    # Shared state is read and changed through functions: an importer cannot assign another module's binding.
    for name, source in sources(".js").items():
        assert not re.search(r"^export\s+(let|var)\b", source, re.MULTILINE), name
        changing = set(re.findall(r"^(?:let|var)\s+(\w+)", source, re.MULTILINE))
        assert not changing & exports(source), name
