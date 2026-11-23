"""Rank task-relevant StableNew navigation references without reading source bodies."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import PurePosixPath

TOKEN = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+|[A-Z]+")
STOP = frozenset(
    "a an and are as at be by can change check could does find fix for from how i in into is it "
    "look me of on or our should show task that the their this to up use want we what when where with".split()
)
MAX_RESULTS = 12
DEFAULT_RESULTS = 5


def terms(value: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in TOKEN.findall(value)
        if len(token) > 1 and token.casefold() not in STOP
    }
    return {
        token[:-1] if len(token) > 4 and token.endswith("s") and not token.endswith("ss") else token
        for token in tokens
    }


def ordered(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda row: (-round(row["score"], 8), row["path"]))


def recommendation(path: str, score: float, reason: str, evidence: str) -> dict:
    return {"path": path, "score": score, "why": reason, "evidence": evidence}


def ownership(path: str) -> str:
    parts = path.split("/")
    if parts[0] != "src":
        return "Development tooling"
    owners = {
        "gui": "Tk presentation",
        "gui_v2": "Toolkit-neutral presentation",
        "controller": "Application coordination",
        "pipeline": "Compilation and execution",
        "queue": "Queue and repository",
        "history": "History projection",
        "video": "Video adapters",
        "learning": "Learning and evidence",
        "image_backends": "Image backend policy and adapters",
        "api": "Backend transport and process adapters",
    }
    return owners.get(parts[1], "Source")


def route(index: dict, task: str, *, limit: int = DEFAULT_RESULTS, broader: bool = False) -> dict:
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"Result limit must be between 1 and {MAX_RESULTS}.")
    query = terms(task)
    modules = index["modules"]
    explicit_paths = set(re.findall(r"[\w./\\-]+\.(?:py|yml)\b", task.replace("\\", "/")))
    explicit_symbols = set(re.findall(r"\b[A-Za-z_]\w*\b", task))
    vocabulary = {
        path: (
            terms(PurePosixPath(path).stem) if not path.endswith("/__init__.py") else set(),
            terms(path.rsplit("/", 1)[0]),
            terms(entry["summary"]),
            set().union(
                *(
                    terms(name)
                    for name, symbol in entry["symbols"].items()
                    if symbol["kind"] != "binding" or symbol["explicit_export"]
                )
            ),
        )
        for path, entry in modules.items()
    }
    count = Counter(token for fields in vocabulary.values() for token in set().union(*fields))
    weight = {term: min(5.0, math.log1p(len(modules) / (1 + count[term]))) for term in query}

    def word_score(tokens: set[str]) -> float:
        return sum(weight[term] for term in sorted(tokens & query))

    row_scores = []
    for row in index["navigation"]:
        overlap = query & terms(row["title"])
        if len(overlap) >= 2:
            row_scores.append((word_score(overlap), row))
    row_scores.sort(key=lambda item: (-item[0], item[1]["title"]))
    row_bonus = {}
    for score, row in row_scores[:3]:
        candidates = (path for path in row["paths"] if path in modules or path in index["tools"])
        for position, path in enumerate(candidates):
            row_bonus.setdefault(path, (min(28, score * 3) / (1 + position / 4), row["title"]))

    direct = []
    for path, fields in vocabulary.items():
        stem, directory, summary, names = fields
        exact = path in explicit_paths or PurePosixPath(path).name in explicit_paths
        original = modules[path]["symbols"]
        symbol_hits = sorted(
            symbol
            for symbol in original.keys() & explicit_symbols
            if original[symbol]["kind"] != "binding" or original[symbol]["explicit_export"]
            if "_" in symbol or any(char.isupper() for char in symbol[1:]) or task.strip() == symbol
        )
        structural = (stem | names) & query
        overlap = (stem | directory | summary | names) & query
        bonus, row = row_bonus.get(path, (0, ""))
        score = 3 * word_score(stem) + 0.6 * word_score(directory) + word_score(summary)
        score += 0.9 * word_score(names) + bonus
        if exact:
            score += 150 if path in explicit_paths else 120
            why, evidence = "Exact path or filename", "direct"
        elif symbol_hits:
            score += 95
            symbol = symbol_hits[0]
            line = original[symbol]["line"]
            why, evidence = (
                f"Exact symbol {symbol}" + (f" at line {line}" if line else ""),
                "direct",
            )
        elif len(overlap) >= 2 and (structural or bonus) and score >= (6 if broader else 10):
            why = "Matched " + ", ".join(sorted(overlap)[:5])
            if row:
                why += f" and task-map row {row}"
            evidence = "lexical"
        elif bonus and score >= 10 and overlap:
            why, evidence = f"Task-map row {row}", "inferred"
        else:
            continue
        direct.append(recommendation(path, score, why, evidence))

    anchors = ordered(direct)[:2]
    for anchor in anchors:
        path = anchor["path"]
        entry = modules[path]
        if anchor["evidence"] == "direct":
            continue
        for row in direct:
            candidate = row["path"]
            forward = candidate in entry["dependencies"]
            reverse = candidate in entry["dependents"] and len(entry["dependents"]) <= 20
            if (
                not (forward or reverse)
                or candidate.endswith("/__init__.py")
                or len(modules[candidate]["dependents"]) > 20
                or len((vocabulary[candidate][0] | vocabulary[candidate][2]) & query) < 2
                or "relation" in row
            ):
                continue
            row["score"] += 14 if forward else 10
            row["why"] += f". {'Imported by' if forward else 'Imports'} {path}"
            row["relation"] = "static import"

    for path in index["tools"]:
        exact = path in explicit_paths or PurePosixPath(path).name in explicit_paths
        tool_words = terms(PurePosixPath(path).stem) | terms(index["tool_terms"].get(path, ""))
        overlap = query & tool_words
        bonus, _ = row_bonus.get(path, (0, ""))
        if exact or len(overlap) >= 2:
            direct.append(
                recommendation(
                    path,
                    150 if exact else 3 * word_score(overlap) + bonus,
                    "Exact development-tool path"
                    if exact
                    else "Tool name or job matches " + ", ".join(sorted(overlap)),
                    "direct" if exact else "lexical",
                )
            )
    ranked = ordered(direct)
    best = ranked[:limit]
    if best:
        floor = best[0]["score"] * (0.25 if broader else 0.46)
        best = [
            row
            for row in best
            if row["score"] >= floor
            and (best[0]["evidence"] != "direct" or row["evidence"] == "direct" or broader)
        ]

    dependencies = {}
    test_hits = {}
    documents = {}
    primary = {row["path"] for row in best}
    for row in best:
        path = row["path"]
        row["owner"] = ownership(path)
        entry = modules.get(path)
        if entry is None:
            continue
        row["summary"] = entry["summary"]
        if not entry["parsed"]:
            row["issue"] = "Source could not be parsed."
        gaps = Counter(
            edge["state"]
            for edge in entry["imports"]
            if edge["state"] in ("unresolved", "dynamic-syntax", "attribute-unverified")
        )
        if gaps:
            row["import_uncertainty"] = dict(gaps)
        for direction, candidates in (
            ("imports", entry["dependencies"]),
            ("imported by", entry["dependents"]),
        ):
            # Keep shared hubs and package initializers out of graph expansion.
            for related in candidates:
                other = modules[related]
                if (
                    related in primary
                    or related.endswith("/__init__.py")
                    or len(other["dependents"]) > 20
                ):
                    continue
                overlap = query & terms(PurePosixPath(related).stem)
                if len(query & terms(other["summary"])) >= 2:
                    overlap |= query & terms(other["summary"])
                same_area = path.split("/")[:2] == related.split("/")[:2]
                if not overlap and (not same_area or direction == "imported by") and not broader:
                    continue
                score = (
                    word_score(overlap)
                    + (2 if same_area else 0)
                    + (1 if direction == "imports" else 0)
                )
                if score <= dependencies.get(related, {}).get("score", 0):
                    continue
                dependencies[related] = recommendation(
                    related, score, f"{path} {direction} this module", "static"
                )
                if direction == "imported by":
                    dependencies[related]["why"] = f"This module imports {path}"
        for test_path, relation in entry["tests"].items():
            score = (4 if relation == "static import" else 1) + word_score(terms(test_path))
            if score > test_hits.get(test_path, {}).get("score", 0):
                test_hits[test_path] = recommendation(
                    test_path,
                    score,
                    f"{relation}: {path}",
                    "static" if relation == "static import" else "inferred",
                )
        for doc, relation in entry["docs"].items():
            score = (4 if relation.startswith("living") else 1) + word_score(
                terms(PurePosixPath(doc).stem)
            )
            if score > documents.get(doc, {}).get("score", 0):
                documents[doc] = recommendation(doc, score, relation, "inferred")
    for row_score, row in row_scores[:2]:
        if not best or not any(
            candidate == path or path.endswith("/") and candidate.startswith(path)
            for candidate in primary
            for path in row["paths"]
        ):
            continue
        for path in row["paths"]:
            if path.startswith("docs/") and path.endswith(".md"):
                documents.setdefault(
                    path,
                    recommendation(path, row_score, f"Task-map row {row['title']}", "inferred"),
                )
            if path.startswith("tests/") and path.endswith(".py"):
                test_hits.setdefault(
                    path,
                    recommendation(path, row_score, f"Task-map row {row['title']}", "inferred"),
                )
    for path, test in index["tests"].items():
        if path in explicit_paths or PurePosixPath(path).name in explicit_paths:
            test_hits[path] = recommendation(path, 150, "Exact test path", "direct")
        elif test["parsed"] and any(
            symbol in explicit_symbols for symbol in test["symbols"] if symbol.startswith("test_")
        ):
            test_hits[path] = recommendation(path, 100, "Exact test symbol", "direct")

    ambiguous = len(best) > 1 and (
        best[0]["evidence"] == best[1]["evidence"] == "direct"
        or best[1]["score"] >= 0.85 * best[0]["score"]
        and best[0]["owner"] != best[1]["owner"]
    )
    confidence = "ambiguous" if ambiguous else "match" if best or test_hits else "no-match"
    return {
        "task": task,
        "confidence": confidence,
        "sources": best,
        "dependencies": ordered(list(dependencies.values()))[: min(limit, 4 if broader else 2)],
        "tests": ordered(list(test_hits.values()))[: min(limit, 4 if broader else 2)],
        "docs": ordered(list(documents.values()))[: min(limit, 4 if broader else 2)],
        "limit": limit,
        "broader": broader,
    }
