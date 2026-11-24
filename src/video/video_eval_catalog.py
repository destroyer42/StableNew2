"""Read-only discovery of video evaluation plans and runs."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.video.video_eval_ratings_store import RatingsFileError, load_ratings
from src.video.video_eval_report import load_run_manifest
from src.video.video_eval_rubric import row_has_content
from src.video.video_eval_run import EVAL_OUTPUT_FOLDER, RUN_MANIFEST_NAME
from src.video.video_eval_suite import load_eval_suite

RUN_ID_PATTERN = re.compile(r"\d{8}_\d{6}_[a-zA-Z0-9_-]{1,150}")
_MAX_RUNS = 100


@dataclass(frozen=True)
class PlanEntry:
    path: Path
    mtime: float
    suite_id: str = ""
    cases: int = 0
    arms: int = 0
    jobs: int = 0
    experimental: bool = False
    error: str = ""
    #: PR-VID-MOTION-410: at least one case binds a driving-motion reference.
    motion: bool = False

    @property
    def label(self) -> str:
        if self.error:
            return f"Unavailable · {self.path.name}"
        experimental = " · experimental" if self.experimental else ""
        motion = " · driving motion" if self.motion else ""
        return (
            f"{self.suite_id} — {self.cases} cases × {self.arms} arms "
            f"({self.jobs} jobs){experimental}{motion} · {self.path.name}"
        )


@dataclass(frozen=True)
class RunEntry:
    path: Path
    created_at: str
    suite_id: str
    jobs: int
    built: bool
    report_path: Path | None
    rated: int | None
    #: PR-VID-MOTION-410: at least one case of the run binds a driving-motion reference.
    motion: bool = False

    @property
    def label(self) -> str:
        status = "report built" if self.built else "report pending"
        rated = (
            f"rated {self.rated}/{self.jobs}" if self.rated is not None else "ratings unreadable"
        )
        motion = " · driving motion" if self.motion else ""
        return (
            f"{self.created_at} · {self.suite_id} · {self.jobs} jobs{motion} · {status} · {rated}"
            f" · {self.path.name[-8:]}"
        )


def list_plans(folder: Path) -> list[PlanEntry]:
    entries = []
    for path in folder.glob("*.json"):
        if path.name.casefold().endswith(".private.json") or not path.is_file():
            continue
        mtime = 0.0
        try:
            mtime = path.stat().st_mtime
            suite = load_eval_suite(path)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            entries.append(PlanEntry(path, mtime, error=str(exc)))
            continue
        entries.append(
            PlanEntry(
                path,
                mtime,
                suite.suite_id,
                len(suite.cases),
                len(suite.arms),
                suite.job_count,
                any(arm.requests_experimental for arm in suite.arms),
                motion=suite.has_motion,
            )
        )
    return sorted(entries, key=lambda entry: (-entry.mtime, entry.path.name.casefold()))


def list_run_ids(
    output_root: Path,
    *,
    include_unbuilt: bool,
    resolve_path: Callable[[Path], Path],
    path_error: type[Exception] = OSError,
) -> list[str]:
    """Find run IDs using the caller's existing path boundary."""
    try:
        root = resolve_path(output_root / EVAL_OUTPUT_FOLDER)
        candidates = sorted(
            (path.name for path in root.iterdir() if RUN_ID_PATTERN.fullmatch(path.name)),
            reverse=True,
        )
    except (OSError, path_error):
        return []
    runs = []
    for name in candidates:
        try:
            # The Site resolves both files before testing either when listing built runs.
            base = root if include_unbuilt else output_root / EVAL_OUTPUT_FOLDER
            directory = resolve_path(base / name)
            manifest = resolve_path(directory / RUN_MANIFEST_NAME)
            metrics = None if include_unbuilt else resolve_path(directory / "metrics.json")
            if manifest.is_file() and (metrics is None or metrics.is_file()):
                runs.append(name)
        except (OSError, path_error):
            continue
        if len(runs) == _MAX_RUNS:
            break
    return runs


def list_runs(output_root: Path, *, include_unbuilt: bool = True) -> list[RunEntry]:
    root = output_root.resolve()

    def local_path(path: Path) -> Path:
        if not path.resolve().is_relative_to(root):
            raise ValueError("Run path is outside Output")
        return path

    names = list_run_ids(
        root, include_unbuilt=include_unbuilt, resolve_path=local_path, path_error=ValueError
    )
    entries = []
    for name in names:
        directory = root / EVAL_OUTPUT_FOLDER / name
        try:
            manifest = load_run_manifest(directory)
            if manifest.get("run_id") != name:
                continue
            report = local_path(directory / "index.html")
            built = local_path(directory / "metrics.json").is_file()
            report_path = report if report.is_file() else None
        except (OSError, ValueError, RecursionError):
            continue
        jobs = manifest["jobs"]
        ids = {str(job.get("job_id")) for job in jobs if isinstance(job, dict)}
        try:
            ratings = load_ratings(local_path(directory / "ratings.csv"))
            rated = len(
                {
                    row["job_id"]
                    for row in ratings.rows
                    if row["job_id"] in ids and row_has_content(row)
                }
            )
        except (OSError, ValueError, RatingsFileError):
            rated = None
        suite = manifest.get("suite")
        suite_id = suite.get("suite_id") if isinstance(suite, dict) else ""
        entries.append(
            RunEntry(
                directory,
                str(manifest.get("created_at") or name)[:16].replace("T", " "),
                str(suite_id or ""),
                len(jobs),
                built,
                report_path,
                rated,
                motion=any(
                    isinstance(case, dict) and isinstance(case.get("motion"), dict)
                    for case in manifest.get("cases", [])
                ),
            )
        )
    return entries
