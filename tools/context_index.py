"""Build an offline AST index behind StableNew's existing task and code maps."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

from tools.generate_code_map import is_checkout_file, summarize_docstring

INDEX_VERSION = 1
REPOSITORY = "destroyer42/StableNew2"
TASK_MAP = "docs/CODEX_MAP.md"
CODE_MAP = "docs/CODE_MAP.md"
SUBSYSTEM_MAP = "docs/Subsystems/README.md"
AUTHORITY = ("AGENTS.md", "STATUS.md")
INPUTS = (*AUTHORITY, TASK_MAP, CODE_MAP, SUBSYSTEM_MAP)
LIMITATIONS = (
    "Static imports describe syntax, including guarded and deferred imports.",
    "Dynamic imports, reflection, registrations and plugin discovery may hide relationships.",
    "External packages and from-import attributes are not resolved at runtime.",
    "Test names and documentation co-occurrence are inferred associations.",
)
PATH_REFERENCE = re.compile(
    r"(?<=\x60)(?:python +)?([a-zA-Z0-9_.-]+/[^|\s\x60()]+)|(?<=\]\()([^#\s)]+\.md)"
)
EXCLUDED = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "cache",
        "node_modules",
        "output",
        "outputs",
        "weights",
    }
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
    )
    return result.stdout.decode("utf-8")


def checkout_status(root: Path, config: list[str]) -> str:
    # Status can otherwise run a configured clean or process filter on changed bytes.
    overrides = []
    for key in sorted(set(config)):
        driver, _, option = key.rpartition(".")
        if driver.startswith("filter.") and option in {"clean", "process", "required"}:
            overrides.extend(("-c", key + ("=false" if option == "required" else "=")))
    return git(
        root,
        *overrides,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
        "--ignore-submodules=all",
    )


def candidate_path(
    root: Path, relative: str, directories: dict[Path, bool] | None = None
) -> Path | None:
    """Resolve a Git-relative regular-file path without following links or junctions."""
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or relative != "/".join(parts)
        or any(
            part.casefold() in EXCLUDED or part == "/" or part.rstrip(" .") != part
            for part in parts
        )
        or any(character in relative for character in ("\\", ":", "\x00"))
    ):
        return None
    directories = {} if directories is None else directories
    path = root.joinpath(*parts)
    return path if is_checkout_file(path, root, directories) else None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def resolve_reference(reference: str, base: str, paths: set[str]) -> str | None:
    for candidate in (reference, f"{base}/{reference}"):
        if candidate in paths or (
            candidate.endswith("/") and any(path.startswith(candidate) for path in paths)
        ):
            return candidate
    return None


def references(line: str, base: str, paths: set[str]) -> list[str]:
    return list(
        dict.fromkeys(
            target
            for code, link in PATH_REFERENCE.findall(line)
            if (target := resolve_reference(code or link, base, paths)) is not None
        )
    )


def snapshot(root: Path) -> tuple[dict, dict[str, bytes], set[str]]:
    """Read the bounded corpus and identify its worktree bytes independently of HEAD."""
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
        raise ValueError("Select the repository worktree root.")
    remote = git(root, "config", "--local", "--get", "remote.origin.url").strip()
    accepted = ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
    if remote.casefold().rstrip("/").removesuffix(".git") not in {
        prefix + REPOSITORY.casefold() for prefix in accepted
    }:
        raise ValueError(f"Select a worktree with origin {REPOSITORY}.")
    config = git(root, "config", "--null", "--name-only", "--list").split("\0")
    head = git(root, "rev-parse", "HEAD").strip()
    status = checkout_status(root, config)
    tracked = set(git(root, "ls-files", "-z", "--cached").split("\0")) - {""}
    new = set(
        git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", "src", "tests").split(
            "\0"
        )
    )
    files = {}
    paths = set()
    directories: dict[Path, bool] = {}
    for relative in sorted(tracked | (new - {""})):
        path = candidate_path(root, relative, directories)
        if path is None:
            continue
        paths.add(relative)
        if (
            relative in INPUTS
            or relative == ".github/workflows/ci.yml"
            or relative.startswith(("src/", "tests/", "tools/ci/"))
            and path.suffix == ".py"
        ):
            files[relative] = path.read_bytes()
    if SUBSYSTEM_MAP in files:
        for line in files[SUBSYSTEM_MAP].decode("utf-8").splitlines():
            for relative in references(line, "docs/Subsystems", paths):
                if relative.startswith("docs/Subsystems/") and relative.endswith(".md"):
                    files[relative] = (root / relative).read_bytes()
    fingerprints = {path: digest(source) for path, source in sorted(files.items())}
    # Existence of named navigation paths also affects routing.
    identity = {
        "checkout": root.as_posix(),
        "repository": REPOSITORY,
        "head": head,
        "dirty": bool(status),
        "fingerprint": digest(json_text([fingerprints, sorted(paths)]).encode()),
    }
    if (head, status) != (
        git(root, "rev-parse", "HEAD").strip(),
        checkout_status(root, config),
    ):
        raise ValueError("Checkout changed during collection. Run again.")
    return identity, files, paths


def module_name(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def symbols(tree: ast.Module) -> dict[str, dict]:
    """Index direct definitions, public bindings and explicit exports."""
    result = {}
    explicit = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            result[node.name] = {"kind": kind, "line": node.lineno}
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or (
                    alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name
                )
                if name != "*":
                    result[name] = {"kind": "binding", "line": node.lineno}
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    result[target.id] = {"kind": "binding", "line": node.lineno}
                    if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                        explicit.update(
                            item.value
                            for item in node.value.elts
                            if isinstance(item, ast.Constant) and isinstance(item.value, str)
                        )
    for name in explicit:
        result.setdefault(name, {"kind": "export", "line": None})
    return {
        name: {**info, "explicit_export": name in explicit}
        for name, info in sorted(result.items())
        if name in explicit or not name.startswith("_") or info["kind"] != "binding"
    }


def import_base(module: str, package: bool, node: ast.ImportFrom) -> str | None:
    if not node.level:
        return node.module or ""
    components = module.split(".") if package else module.split(".")[:-1]
    if node.level > len(components):
        return None
    parents = components[: len(components) - node.level + 1]
    return ".".join([*parents, *([node.module] if node.module else [])])


def import_edges(
    tree: ast.Module,
    module: str,
    package: bool,
    modules: dict[str, str],
    definitions: dict,
    *,
    detailed: bool,
) -> list[dict]:
    """Record statements separately from resolved graph adjacency."""
    edges = []
    modules_aliases = {"importlib"}
    dynamic_names = {"__import__"}
    for candidate in ast.walk(tree) if detailed else ():
        if isinstance(candidate, ast.Import):
            modules_aliases.update(
                item.asname or item.name for item in candidate.names if item.name == "importlib"
            )
        elif isinstance(candidate, ast.ImportFrom) and candidate.module == "importlib":
            dynamic_names.update(
                item.asname or item.name for item in candidate.names if item.name == "import_module"
            )

    def walk(node: ast.AST, guarded: bool = False, deferred: bool = False) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            base = import_base(module, package, node) if isinstance(node, ast.ImportFrom) else ""
            for item in node.names:
                name = f"{base}.{item.name}" if base else item.name
                target = modules.get(name) if base is not None else None
                parent = modules.get(base) if base else None
                if parent and item.name in definitions.get(parent, {}):
                    # A visible package attribute can shadow a child module.
                    target = parent
                if target:
                    state = "static"
                elif parent:
                    target = parent
                    state = "attribute-unverified"
                elif base is None or name == "src" or name.startswith("src."):
                    state = "unresolved"
                else:
                    state = "external"
                edges.append(
                    {
                        "name": name,
                        "base": base,
                        "relative_level": getattr(node, "level", 0),
                        "alias": item.asname,
                        "state": state,
                        "target": target,
                        "line": node.lineno,
                        "guarded": guarded,
                        "deferred": deferred,
                    }
                )
        if detailed and isinstance(node, ast.Call):
            callee = node.func
            if (
                isinstance(callee, ast.Name)
                and callee.id in dynamic_names
                or isinstance(callee, ast.Attribute)
                and callee.attr == "import_module"
                and isinstance(callee.value, ast.Name)
                and callee.value.id in modules_aliases
            ):
                edges.append(
                    {
                        "name": ast.unparse(callee),
                        "base": None,
                        "relative_level": 0,
                        "alias": None,
                        "state": "dynamic-syntax",
                        "target": None,
                        "line": node.lineno,
                        "guarded": guarded,
                        "deferred": deferred,
                    }
                )
        for child in ast.iter_child_nodes(node) if detailed else ():
            walk(
                child,
                guarded
                or isinstance(
                    node,
                    (
                        ast.If,
                        ast.Try,
                        ast.TryStar,
                        ast.Match,
                        ast.For,
                        ast.While,
                        ast.With,
                        ast.AsyncFor,
                        ast.AsyncWith,
                    ),
                ),
                deferred or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)),
            )

    if detailed:
        walk(tree)
    else:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                walk(node)
    return sorted(edges, key=lambda edge: (edge["line"], edge["name"]))


def navigation(files: dict[str, bytes], paths: set[str]) -> tuple[list[dict], dict[str, list[str]]]:
    rows = []
    for line in files.get(TASK_MAP, b"").decode("utf-8").splitlines():
        if line.startswith("| ") and (refs := references(line, "docs", paths)):
            rows.append({"title": line.split("|")[1].strip(), "paths": refs})
    docs: dict[str, list[str]] = defaultdict(list)
    for path, data in sorted(files.items()):
        if path.startswith("docs/Subsystems/") and path != SUBSYSTEM_MAP:
            for relative in references(data.decode("utf-8"), "docs/Subsystems", paths):
                if relative.startswith("src/"):
                    docs[relative].append(path)
    return rows, dict(docs)


def parse(source: bytes, path: str) -> ast.Module | None:
    try:
        return ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError):
        return None


def build(root: Path) -> dict:
    identity, files, paths = snapshot(root)
    source_paths = sorted(
        path for path in files if path.startswith("src/") and path.endswith(".py")
    )
    test_paths = sorted(
        path for path in files if path.startswith("tests/") and path.endswith(".py")
    )
    trees = {path: parse(files[path], path) for path in source_paths}
    modules = {module_name(path): path for path in source_paths}
    definitions = {path: symbols(tree) for path, tree in trees.items() if tree is not None}
    rows, docs = navigation(files, paths)
    entries = {}
    tests = {}
    for path in (*source_paths, *test_paths):
        is_source = path.startswith("src/")
        tree = trees.pop(path) if is_source else parse(files[path], path)
        module = module_name(path)
        raw = (
            import_edges(
                tree,
                module,
                path.endswith("/__init__.py"),
                modules,
                definitions,
                detailed=is_source,
            )
            if tree
            else []
        )
        direct = {edge["target"] for edge in raw if edge["target"]}
        if not is_source:
            tests[path] = {
                "parsed": tree is not None,
                "dependencies": sorted(direct),
                "symbols": sorted(name for name in symbols(tree) if name.startswith("test"))
                if tree
                else [],
            }
            continue
        initializers = set()
        for target in direct:
            parts = module_name(target).split(".")
            for length in range(1, len(parts)):
                initializer = modules.get(".".join(parts[:length]))
                if initializer and initializer.endswith("/__init__.py"):
                    initializers.add(initializer)
        summary = summarize_docstring(ast.get_docstring(tree)) if tree else "(could not be parsed)"
        entry_docs = dict.fromkeys(docs.get(path, []), "living record references path")
        for row in rows:
            if any(
                path == ref or ref.endswith("/") and path.startswith(ref) for ref in row["paths"]
            ):
                for link in row["paths"]:
                    if link.startswith("docs/") and link.endswith(".md"):
                        entry_docs.setdefault(link, "task-map row")
        entries[path] = {
            "module": module,
            "summary": summary,
            "sha256": digest(files[path]),
            "parsed": tree is not None,
            "symbols": definitions.get(path, {}),
            "imports": raw,
            "dependencies": sorted(direct - {path}),
            "package_initializers": sorted(initializers - direct - {path}),
            "dependents": [],
            "tests": {},
            "docs": entry_docs,
        }
    by_stem: dict[str, list[str]] = defaultdict(list)
    for path, test in tests.items():
        test_name = PurePosixPath(path).stem
        if test_name.startswith("test_"):
            by_stem[test_name[5:]].append(path)
            for dependency in test["dependencies"]:
                entries[dependency]["tests"][path] = "static import"
    for path, entry in entries.items():
        for dependency in entry["dependencies"]:
            entries[dependency]["dependents"].append(path)
        for test_path in by_stem[PurePosixPath(path).stem]:
            entry["tests"].setdefault(test_path, "matching test filename")
    workflow = files.get(".github/workflows/ci.yml", b"").decode("utf-8")
    jobs = workflow.partition("\njobs:")[2]
    return {
        "schema": INDEX_VERSION,
        "identity": identity,
        "modules": entries,
        "tests": tests,
        "navigation": rows,
        "limitations": LIMITATIONS,
        "tools": sorted(
            path
            for path in files
            if path.startswith("tools/ci/") or path == ".github/workflows/ci.yml"
        ),
        "tool_terms": {
            ".github/workflows/ci.yml": " ".join(re.findall(r"^  ([\w-]+):", jobs, re.MULTILINE)),
        },
        "code_map": files.get(CODE_MAP, b"").decode("utf-8"),
    }
