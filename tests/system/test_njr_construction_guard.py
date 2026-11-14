"""P4-2F: the repository-wide guard for the single NJR assembly boundary.

``src/pipeline/njr_compiler.py`` is the only module that assembles a ``NormalizedJobRecord`` (``compile_njr``) or gives
one a new identity (``derive_njr``). Outside it, a new site fails here unless it is listed below with a reason. The
allow-lists are exact file paths with an exact site count, never patterns: a second site in an allowed file, or an
allowed site that disappeared, fails too, so an entry cannot hide a new site and cannot go stale.

The guard reads source with ``ast``. It is a tripwire for the shapes the P4-2 audit found, not a proof: it cannot see a
record built through ``type(record)(...)``, ``getattr`` or ``cls(...)``, or a ``replace`` on a differently named value.
Test code is out of scope (fixtures build records freely); ``tests/`` never ships.

Three rules:

* **construction**: a call of ``NormalizedJobRecord`` (also under an import alias or as ``module.NormalizedJobRecord``);
* **re-identification**: ``dataclasses.replace(<anything>, job_id=...)``;
* **rebuild**: ``dataclasses.replace(<record-named value>, <workload/stages/provenance/...>=...)``, i.e. a copy of a
  record with an envelope part swapped (the name test is ``record``, ``njr`` or ``parent``, as the migrated code
  names its records).

A fourth check keeps model-family names out of the core.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("src", "tools", "scripts")
CORE = "src/pipeline/njr_compiler.py"

#: The envelope parts of a record whose replacement is a rebuild. ``source`` is left out on purpose: other frozen
#: dataclasses carry a ``source`` field, and a re-sourced record always also changes ``job_id`` (rule 2).
ENVELOPE_PARTS = frozenset(
    {"job_id", "workload", "stages", "output_plan", "provenance", "workload_kind", "schema_version"}
)
RECORD_NAMED = re.compile(r"(?:^|_)(?:record|njr|parent)$")

#: Rule 1. path -> (exact number of ``NormalizedJobRecord(...)`` calls, reason).
CONSTRUCTION_ALLOWED: dict[str, tuple[int, str]] = {
    CORE: (1, "compile_njr: the single assembly boundary"),
    "src/pipeline/njr_core_v26.py": (
        1,
        "migrate_legacy_njr: the read/migration path that lifts a pre-2.6 payload; no route compiles through it",
    ),
    "tools/qualification/img_forge_100/run.py": (
        1,
        "operator-only qualification driver (never imported by src, never in CI); P4-2 excluded it",
    ),
}

#: Rules 2 and 3 outside the core, ``replace`` calls on a record. path -> (exact number of sites, reason).
#: The core itself is exempt: it is the owner of re-identification.
REPLACE_ALLOWED: dict[str, tuple[int, str]] = {
    "src/learning/qualification_batch.py": (
        1,
        "admission comparison: a fresh compile is given the stored identity only to compare to_dict() with the stored "
        "record; the copy is never kept, queued or returned",
    ),
    "src/pipeline/replay_njr_compiler.py": (
        2,
        "preparation of the parent's run directives before derive_njr mints the new identity; the copy keeps the "
        "parent's job_id and is never a submitted record",
    ),
    "src/learning/learning_controller_services/embedding_experiment.py": (
        1,
        "Learning: attaches the declared embeddings to a record materialize_njr just built; same identity, no new job",
    ),
    "src/learning/learning_controller_services/prompt_slot.py": (
        1,
        "Learning: attaches the declared embeddings to a record materialize_njr just built; same identity, no new job",
    ),
    "tools/acceptance/img_116_klein_acceptance.py": (
        1,
        "operator-only acceptance tool: redirects the record's output directory to its report folder",
    ),
    "tools/acceptance/img_156_zimage_acceptance.py": (
        1,
        "operator-only acceptance tool: names the record after the attempt and redirects its output directory",
    ),
    "tools/acceptance/img_forge_100_acceptance.py": (
        1,
        "operator-only acceptance tool: redirects the record's output directory to its report folder",
    ),
    "tools/acceptance/img_forge_120_default_acceptance.py": (
        1,
        "operator-only acceptance tool: redirects the record's output directory to its report folder",
    ),
}

FAMILY_IDENTIFIERS = re.compile(
    r"z_?image|klein|flux|sdxl|sd15|animatediff|qwen|hunyuan|wan2|ltx", re.IGNORECASE
)


@dataclass(frozen=True)
class Site:
    rule: str  # "construction" | "replace"
    path: str
    line: int


def _bound_names(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    """Local names for ``NormalizedJobRecord``, for ``dataclasses.replace`` and for the ``dataclasses`` module."""

    record_names = {"NormalizedJobRecord"}
    replace_names: set[str] = set()
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "NormalizedJobRecord":
                    record_names.add(alias.asname or alias.name)
                if node.module == "dataclasses" and alias.name == "replace":
                    replace_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dataclasses":
                    module_names.add(alias.asname or alias.name)
    return record_names, replace_names, module_names


def _tail_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def scan_source(path: str, text: str) -> list[Site]:
    """Every construction or record ``replace`` site in one module."""

    tree = ast.parse(text, filename=path)
    record_names, replace_names, module_names = _bound_names(tree)
    sites: list[Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id in record_names) or (
            isinstance(func, ast.Attribute) and func.attr == "NormalizedJobRecord"
        ):
            sites.append(Site("construction", path, node.lineno))
            continue
        is_replace = (isinstance(func, ast.Name) and func.id in replace_names) or (
            isinstance(func, ast.Attribute)
            and func.attr == "replace"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_names
        )
        if not is_replace or not node.args:
            continue
        keywords = {keyword.arg for keyword in node.keywords if keyword.arg}
        target = _tail_name(node.args[0]) or ""
        if "job_id" in keywords or (keywords & ENVELOPE_PARTS and RECORD_NAMED.search(target)):
            sites.append(Site("replace", path, node.lineno))
    return sites


def _python_files(root: Path, scan_roots: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for name in scan_roots:
        base = root / name
        if base.is_dir():
            files.extend(
                path
                for path in base.rglob("*.py")
                if "__pycache__" not in path.parts and ".venv" not in path.parts
            )
    return sorted(files)


def violations(
    root: Path,
    *,
    scan_roots: Iterable[str] = SCAN_ROOTS,
    construction_allowed: dict[str, tuple[int, str]] = CONSTRUCTION_ALLOWED,
    replace_allowed: dict[str, tuple[int, str]] = REPLACE_ALLOWED,
) -> list[str]:
    """Problems found under ``root``: an unlisted site, a changed count, or an allow-list entry with no file."""

    found: dict[str, Counter[str]] = {"construction": Counter(), "replace": Counter()}
    lines: dict[tuple[str, str], list[int]] = {}
    for path in _python_files(root, scan_roots):
        relative = path.relative_to(root).as_posix()
        for site in scan_source(relative, path.read_text(encoding="utf-8")):
            if site.rule == "replace" and relative == CORE:
                continue  # the core owns re-identification
            found[site.rule][relative] += 1
            lines.setdefault((site.rule, relative), []).append(site.line)

    problems: list[str] = []
    for rule, allowed in (("construction", construction_allowed), ("replace", replace_allowed)):
        for relative, count in sorted(found[rule].items()):
            expected = allowed.get(relative, (0, ""))[0]
            where = ", ".join(f"line {line}" for line in sorted(lines[(rule, relative)]))
            if relative not in allowed:
                problems.append(
                    f"{relative}: new {rule} site ({where}); assemble through "
                    "src/pipeline/njr_compiler.py (compile_njr / derive_njr)"
                )
            elif count != expected:
                problems.append(
                    f"{relative}: {count} {rule} site(s) ({where}), the allow-list names {expected}; "
                    "route a new site through the core, or lower the entry when a site is removed"
                )
        for relative in sorted(set(allowed) - set(found[rule])):
            if rule == "replace" and relative == CORE:
                continue
            problems.append(
                f"{relative}: allow-listed for {rule} but no such site exists; remove the stale entry"
            )
    for relative in sorted(set(construction_allowed) | set(replace_allowed)):
        if not (root / relative).is_file():
            problems.append(f"{relative}: allow-listed but the file does not exist")
    return problems


def test_no_unlisted_njr_construction_or_re_identification_site() -> None:
    assert violations(REPO) == []


def test_the_allow_lists_are_exact_files_with_reasons() -> None:
    for table in (CONSTRUCTION_ALLOWED, REPLACE_ALLOWED):
        for path, (count, reason) in table.items():
            assert path.endswith(".py") and not any(ch in path for ch in "*?[]"), path
            assert count >= 1 and reason.strip(), path
    # Only the core and the legacy read path may construct inside src; a route never joins this list without an
    # owner decision (the plan names the core and migrate_legacy_njr alone).
    assert sorted(p for p in CONSTRUCTION_ALLOWED if p.startswith("src/")) == [
        CORE,
        "src/pipeline/njr_core_v26.py",
    ]


def test_the_core_names_no_model_family() -> None:
    source = (REPO / CORE).read_text(encoding="utf-8")

    assert FAMILY_IDENTIFIERS.findall(source) == []


# --- the guard itself: it fails on a deliberately added site and passes without it --------------------------------------


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


CLEAN_ROUTE = (
    "from src.pipeline.njr_compiler import compile_njr\n"
    "def build(draft):\n"
    "    return compile_njr(draft)\n"
)


def test_a_route_that_assembles_through_the_core_passes(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"src/pipeline/new_route.py": CLEAN_ROUTE})

    assert violations(root, construction_allowed={}, replace_allowed={}) == []


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "direct construction",
            "from src.pipeline.job_models_v2 import NormalizedJobRecord\n"
            "def build(**parts):\n    return NormalizedJobRecord(**parts)\n",
        ),
        (
            "aliased construction",
            "from src.pipeline.job_models_v2 import NormalizedJobRecord as Envelope\n"
            "def build(**parts):\n    return Envelope(**parts)\n",
        ),
        (
            "module attribute construction",
            "from src.pipeline import job_models_v2\n"
            "def build(**parts):\n    return job_models_v2.NormalizedJobRecord(**parts)\n",
        ),
        (
            "re-identification",
            "from dataclasses import replace\n"
            "def again(record, new_id):\n    return replace(record, job_id=new_id)\n",
        ),
        (
            "re-identification through an aliased replace",
            "from dataclasses import replace as dc_replace\n"
            "def again(thing, new_id):\n    return dc_replace(thing, job_id=new_id)\n",
        ),
        (
            "re-identification through the module",
            "import dataclasses\n"
            "def again(thing, new_id):\n    return dataclasses.replace(thing, job_id=new_id)\n",
        ),
        (
            "rebuild of a record",
            "from dataclasses import replace\n"
            "def rebuild(njr, provenance):\n    return replace(njr, provenance=provenance)\n",
        ),
    ],
)
def test_the_guard_fails_on_a_deliberately_added_site(
    tmp_path: Path, label: str, source: str
) -> None:
    root = _tree(tmp_path, {"src/pipeline/new_route.py": source})

    problems = violations(root, construction_allowed={}, replace_allowed={})

    assert len(problems) == 1, label
    assert problems[0].startswith("src/pipeline/new_route.py: new "), problems


def test_the_guard_ignores_replaces_that_are_not_record_rebuilds(tmp_path: Path) -> None:
    source = (
        "from dataclasses import replace\n"
        "def other(draft, final, stage, text, record):\n"
        "    a = replace(draft, workload=1)\n"  # a draft is not a record
        "    b = replace(final, source=2)\n"  # `source` alone is another dataclass's field
        "    c = replace(record.workload, config={})\n"  # a part, not the envelope
        "    d = replace(stage, extra={})\n"
        "    e = text.replace('a', 'b')\n"
        "    return a, b, c, d, e\n"
    )
    root = _tree(tmp_path, {"src/pipeline/other.py": source})

    assert violations(root, construction_allowed={}, replace_allowed={}) == []


def test_an_allowed_file_cannot_gain_a_second_site(tmp_path: Path) -> None:
    two_sites = (
        "from dataclasses import replace\n"
        "def a(record):\n    return replace(record, provenance=None)\n"
        "def b(record):\n    return replace(record, stages=())\n"
    )
    root = _tree(tmp_path, {"tools/acceptance/one.py": two_sites})

    problems = violations(
        root,
        construction_allowed={},
        replace_allowed={"tools/acceptance/one.py": (1, "operator-only")},
    )

    assert len(problems) == 1 and "2 replace site(s)" in problems[0], problems


def test_an_allow_list_entry_without_a_site_is_stale(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"tools/acceptance/one.py": CLEAN_ROUTE})

    problems = violations(
        root,
        construction_allowed={},
        replace_allowed={"tools/acceptance/one.py": (1, "operator-only")},
    )

    assert problems == [
        "tools/acceptance/one.py: allow-listed for replace but no such site exists; remove the stale entry"
    ]


def test_the_core_may_re_identify_and_construct_exactly_once(tmp_path: Path) -> None:
    core = (
        "from dataclasses import replace\n"
        "from src.pipeline.job_models_v2 import NormalizedJobRecord\n"
        "def compile_njr(d):\n    return NormalizedJobRecord(**d)\n"
        "def derive_njr(parent, new_id):\n    return replace(parent, job_id=new_id)\n"
    )
    root = _tree(tmp_path, {CORE: core})
    allowed = {CORE: (1, "compile_njr")}

    assert violations(root, construction_allowed=allowed, replace_allowed={}) == []

    second = core + "def sneaky(d):\n    return NormalizedJobRecord(**d)\n"
    root = _tree(tmp_path, {CORE: second})
    problems = violations(root, construction_allowed=allowed, replace_allowed={})
    assert len(problems) == 1 and "2 construction site(s)" in problems[0], problems
