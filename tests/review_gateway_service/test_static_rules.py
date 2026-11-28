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
#: The one dynamic import: main.js loads the features the server names.
LOADER = "import(`../features/${name}/feature.js`)"
#: PHONE-CORE 2.2 and 7: lines a file. A listed file is over its cap and may only shrink; PC-2 splits it.
CAPS = {"core": 300, "features": 400}
OVERSIZED = {"features/rating/rating.js": 528}


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
        rest = source.replace(LOADER, "") if name == "core/main.js" else source
        assert not re.search(r"\bimport\s*\(", rest), name
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


def features() -> list[str]:
    return sorted(path.name for path in (STATIC / "features").iterdir() if path.is_dir())


def legacy_imports(modules: dict[str, str], feature: str) -> set[str]:
    """What the feature's own entry still declares it takes from outside, as paths below ``static/``."""

    entry = modules.get(f"features/{feature}/feature.js", "")
    declared = re.search(
        r"^export const legacyImports = \[(?P<paths>[^\]]*)\];", entry, re.MULTILINE
    )
    return set(re.findall(r'"([^"]+)"', declared["paths"])) if declared else set()


def crossings(modules: dict[str, str]) -> list[str]:
    """Undeclared imports that leave their side: core into a feature, or a feature into another feature."""

    found = []
    for name, source in modules.items():
        feature = name.split("/")[1] if name.startswith("features/") else None
        allowed = legacy_imports(modules, feature) if feature else set()
        for match in IMPORT.finditer(source):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), match["path"]))
            inside = target.startswith("core/") or (
                feature is not None and target.startswith(f"features/{feature}/")
            )
            if not inside and target not in allowed:
                found.append(f"{name} -> {target}")
    return found


def test_the_core_imports_no_feature_and_a_feature_imports_only_itself_and_the_core() -> None:
    assert not crossings(sources(".js"))


def test_the_boundary_check_sees_both_directions_and_honours_a_declared_exception() -> None:
    modules = {
        "core/a.js": 'import { x } from "../features/one/one.js";\n',
        "features/one/one.js": 'import { y } from "../two/two.js";\nimport { z } from "../../core/a.js";\n',
        "features/two/two.js": 'import { x } from "../one/one.js";\n',
        "features/two/feature.js": 'export const legacyImports = ["features/one/one.js"];\n',
    }

    assert crossings(modules) == [
        "core/a.js -> features/one/one.js",
        "features/one/one.js -> features/two/two.js",
    ]


def test_every_feature_has_an_entry_that_names_itself_and_its_order() -> None:
    orders = []
    for feature in features():
        entry = sources(".js").get(f"features/{feature}/feature.js", "")
        assert re.search(rf'^  id: "{feature}",$', entry, re.MULTILINE), feature
        order = re.search(r"^  order: (\d+),", entry, re.MULTILINE)
        assert order, feature
        orders.append(int(order[1]))
    assert len(orders) == len(set(orders)), "two features share an order"


def test_files_stay_under_their_caps_and_the_exceptions_only_shrink() -> None:
    lines = {name: source.count("\n") for name, source in sources(".js").items()}
    over = {name: count for name, count in lines.items() if count > CAPS[name.split("/")[0]]}
    assert not set(over) - set(OVERSIZED), {name: over[name] for name in set(over) - set(OVERSIZED)}
    assert not set(OVERSIZED) - set(over), "no longer over its cap: take it off the list"
    for name, count in over.items():
        assert count <= OVERSIZED[name], f"{name} grew to {count} lines"
