"""The development environment is one reproducible, drift-checked authority (audit P1-2).

Covers: exact dev-tool pins shared by hosted CI and a developer machine, consistency between requirements-dev.txt,
pyproject.toml, pre-commit and the workflows, no dead runtime dependencies, and a guard that every third-party module
the application imports is declared (an undeclared ``yaml``/``numpy`` import turned the main census red once).
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT_FILES = ("requirements.txt", "requirements-svd.txt", "requirements-postprocess.txt")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _requirements(rel: str) -> list[Requirement]:
    lines = [line.split("#", 1)[0].strip() for line in _read(rel).splitlines()]
    return [Requirement(line) for line in lines if line and not line.startswith("-")]


def test_every_dev_tool_is_pinned_exactly_once() -> None:
    requirements = _requirements("requirements-dev.txt")
    names = [canonicalize_name(r.name) for r in requirements]

    assert len(names) == len(set(names))
    for requirement in requirements:
        specifiers = list(requirement.specifier)
        assert len(specifiers) == 1 and specifiers[0].operator == "==", (
            f"{requirement.name} must be pinned with =="
        )
    for tool in ("pytest", "pytest-timeout", "ruff", "mypy", "types-requests"):
        assert tool in names, f"{tool} is missing from requirements-dev.txt"


def test_the_ruff_pin_is_identical_in_every_place_it_is_declared() -> None:
    dev_pin = next(
        r for r in _requirements("requirements-dev.txt") if canonicalize_name(r.name) == "ruff"
    )
    version = next(iter(dev_pin.specifier)).version

    pyproject = tomllib.loads(_read("pyproject.toml"))
    assert f"ruff=={version}" in pyproject["project"]["optional-dependencies"]["dev"]
    assert (
        f"rev: v{version}"
        in _read(".pre-commit-config.yaml").split("astral-sh/ruff-pre-commit")[1][:80]
    )


def test_the_pytest_pin_does_not_contradict_the_runtime_constraints() -> None:
    dev = next(
        r for r in _requirements("requirements-dev.txt") if canonicalize_name(r.name) == "pytest"
    )
    pinned = next(iter(dev.specifier)).version
    constraint_lines = _read("constraints/windows-py314-cu130.txt").splitlines()
    assert f"pytest=={pinned}" in constraint_lines, (
        "dev pytest and the Windows runtime pin must agree"
    )


def test_workflows_install_the_dev_lock_instead_of_unpinned_tools() -> None:
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("pip install") and "-r " not in stripped:
                raise AssertionError(
                    f"{workflow.name}: unpinned `{stripped}`; use requirements-dev.txt"
                )
    ci = _read(".github/workflows/ci.yml")
    assert (
        ci.count("pip install -r requirements-dev.txt") >= 2
    )  # the required job and the census shards


def test_the_tooling_blocker_message_names_the_install_command() -> None:
    assert "requirements-dev.txt" in _read("tools/ci/run_pr_gate.py")


def test_dead_gui_dependencies_stay_removed() -> None:
    """ttkbootstrap and tkinterdnd2 were declared and pinned but imported nowhere; the pin verifier would demand them."""

    for rel in (*REQUIREMENT_FILES, "constraints/windows-py314-cu130.txt"):
        text = _read(rel).lower()
        assert "ttkbootstrap" not in text and "tkinterdnd2" not in text, rel
    pyproject = _read("pyproject.toml").lower()
    assert "ttkbootstrap" not in pyproject and "tkinterdnd2" not in pyproject


# --- every imported third-party module is declared -------------------------------------------------------------------

#: import root -> distribution that provides it, where the names differ
IMPORT_TO_DISTRIBUTION = {
    "PIL": "pillow",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "facelib": "codeformer",
    "spandrel_extra_arches": "spandrel-extra-arches",
}
#: Provided transitively by a declared tool (documented here so a new entry needs a conscious decision).
TRANSITIVE = {"packaging": "installed with pytest"}
LOCAL_ROOTS = {"src", "tools", "scripts", "tests", "__future__"}


def _declared_distributions() -> set[str]:
    declared: set[str] = set()
    for rel in (*REQUIREMENT_FILES, "requirements-dev.txt"):
        declared |= {canonicalize_name(r.name) for r in _requirements(rel)}
    return declared


def _imported_roots(directory: str) -> dict[str, str]:
    stdlib = set(sys.stdlib_module_names)
    roots: dict[str, str] = {}
    for path in sorted((ROOT / directory).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        siblings = {
            p.stem for p in path.parent.glob("*.py")
        }  # tools/ci modules import each other by bare name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name not in stdlib and name not in LOCAL_ROOTS and name not in siblings:
                    roots.setdefault(name, path.relative_to(ROOT).as_posix())
    return roots


def _undeclared(directory: str) -> list[str]:
    declared = _declared_distributions()
    problems = []
    for root, example in _imported_roots(directory).items():
        distribution = canonicalize_name(IMPORT_TO_DISTRIBUTION.get(root, root))
        if distribution in declared or root in TRANSITIVE:
            continue
        problems.append(f"{root} (e.g. {example})")
    return problems


def test_every_third_party_module_the_application_imports_is_declared() -> None:
    assert _undeclared("src") == []


def test_every_third_party_module_the_ci_and_runtime_tools_import_is_declared() -> None:
    assert _undeclared("tools/ci") == []
    assert _undeclared("tools/runtime") == []


def test_the_import_guard_detects_an_undeclared_module(tmp_path: Path, monkeypatch) -> None:
    """Negative case: a new module-level import that nobody declared must be reported, not silently accepted."""

    probe = ROOT / "src" / "_p1_2_probe_undeclared_module.py"
    probe.write_text("import definitely_not_a_real_distribution\n", encoding="utf-8")
    try:
        assert any(
            item.startswith("definitely_not_a_real_distribution") for item in _undeclared("src")
        )
    finally:
        probe.unlink()
