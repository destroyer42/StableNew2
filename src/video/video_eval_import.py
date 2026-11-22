"""Copy a video suite into Evaluation Plans while keeping its source references usable."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from src.state.eval_plans_paths import initialize_eval_plans
from src.utils.atomic_io import atomic_publish_json
from src.video.video_eval_suite import EvalSuiteError, parse_eval_suite


def is_private_suite(path: Path) -> bool:
    return path.name.casefold().endswith(".private.json")


def import_suite(source: Path, root: Path, *, apply: bool = False) -> Path:
    if is_private_suite(source) or is_private_suite(source.resolve()):
        raise EvalSuiteError("Private suite skipped. Review it in its original location.")
    source = source.resolve(strict=True)
    target = root / "video" / source.name
    raw = source.read_bytes()
    suite = parse_eval_suite(source, raw)
    record = json.loads(raw)
    for case, validated in zip(record["cases"], suite.cases, strict=True):
        case["image"] = str(validated.image_path)

    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Destination already exists: {target}")
    if not apply:
        return target

    initialize_eval_plans(root)
    atomic_publish_json(target, record, indent=2, ensure_ascii=False)
    event = {
        "imported_at": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "destination": str(target),
    }
    log_path = root / "_imported" / "imports.jsonl"
    try:
        # A single append keeps records together when two imports finish concurrently.
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            line = (json.dumps(event) + "\n").encode("utf-8")
            if os.write(fd, line) != len(line):
                raise OSError("Incomplete provenance log append")
        finally:
            os.close(fd)
    except OSError as exc:
        raise OSError(f"Suite copied to {target}, but could not log provenance: {exc}") from exc
    return target


def suite_templates(examples: Path, root: Path, *, apply: bool = False) -> list[Path]:
    targets = []
    for source in sorted(examples.glob("*.suite.json")):
        target = root / "templates" / source.name
        if apply:
            # Bundled examples are known JSON. Publish without replacing edited copies.
            try:
                atomic_publish_json(target, json.loads(source.read_bytes()), indent=2)
            except FileExistsError:
                continue
        elif target.exists() or target.is_symlink():
            continue
        targets.append(target)
    return targets
