"""Read-only analysis of one VID-CAND-382 eval run (modelled on VID-CLIP-371's ``verify_s2.py``).

Reads ``run.json``, ``metrics.json`` and the per-clip manifests under ``<Output>/video_eval/<run_id>/``, the job
repository through a read-only SQLite URI, and (optionally) the owner's ``ratings.csv``, the pairwise result and a host
telemetry file.  It writes nothing, generates nothing and never fills a rating.  It reproduces the CLIP-371 checks
(suite digest, seed, workflow identity, frozen prompts and geometry, runtime identity, job states) and adds what this
package needs: wall time split cold and warm per arm, and the written GO/NO-GO verdict from the frozen plan.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from tools.qualification.vid_cand382.plan import THRESHOLDS

#: The catalog's keep-warm grace (``HUNYUAN15_KEEP_WARM_SECONDS``): a job started within it of a completed job of the same
#: workflow id and version reused that process.
KEEP_WARM_GRACE_SECONDS = 120.0
ACHIEVED = ("achieved", "partially_achieved")
ACTION_SCORE = {"achieved": 1.0, "partially_achieved": 0.5, "not_achieved": 0.0}
FIDELITY, STABILITY = "source_fidelity_1_to_5", "subject_stability_1_to_5"
ALLOCATION_MARKERS = ("out of memory", "oom", "allocation", "cuda error", "device lost")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def job_rows(jobs_db: Path, job_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Status and timing of each job, from the repository opened read-only."""

    connection = sqlite3.connect(f"file:{Path(jobs_db).as_posix()}?mode=ro", uri=True)
    try:
        rows: dict[str, dict[str, Any]] = {}
        for job_id in job_ids:
            found = connection.execute(
                "select status, started_at, completed_at, error_message from jobs where job_id=?",
                (job_id,),
            ).fetchone()
            if found is not None:
                rows[job_id] = dict(
                    zip(("status", "started_at", "completed_at", "error"), found, strict=True)
                )
        return rows
    finally:
        connection.close()


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def wall_by_arm(
    run: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    *,
    grace: float = KEEP_WARM_GRACE_SECONDS,
) -> dict[str, dict[str, Any]]:
    """Per arm: job states and wall seconds split cold/warm.

    A job is warm when the previous completed job (any arm, by start time) had the same workflow id and version and
    finished no more than ``grace`` seconds before this one started; the first job after anything else is cold.
    """

    forms = {arm["arm_id"]: arm.get("overrides") or {} for arm in run.get("arms", [])}
    identity = {
        arm_id: (form.get("workflow_id"), form.get("workflow_version"))
        for arm_id, form in forms.items()
    }
    timed = sorted(
        (
            (job["job_id"], job["arm_id"], rows[job["job_id"]])
            for job in run["jobs"]
            if job["job_id"] in rows and rows[job["job_id"]].get("started_at")
        ),
        key=lambda item: item[2]["started_at"],
    )
    out: dict[str, dict[str, Any]] = {
        arm_id: {"states": Counter(), "cold": [], "warm": []} for arm_id in forms
    }
    for job in run["jobs"]:
        row = rows.get(job["job_id"])
        out[job["arm_id"]]["states"][row["status"] if row else "missing"] += 1
    previous: tuple[str, str | None] | None = None  # (arm_id, completed_at)
    for _job_id, arm_id, row in timed:
        wall = _seconds_between(row["started_at"], row["completed_at"])
        warm = (
            previous is not None
            and identity[previous[0]] == identity[arm_id]
            and (gap := _seconds_between(previous[1], row["started_at"])) is not None
            and gap <= grace
        )
        if wall is not None and row["status"] == "completed":
            out[arm_id]["warm" if warm else "cold"].append(wall)
        previous = (arm_id, row["completed_at"]) if row["completed_at"] else None
    for stats in out.values():
        stats["states"] = dict(stats["states"])
        for kind in ("cold", "warm"):
            values = stats[kind]
            stats[f"{kind}_median"] = round(median(values), 1) if values else None
            stats[f"{kind}_range"] = (
                [round(min(values), 1), round(max(values), 1)] if values else None
            )
    return out


def identity_checks(
    run: Mapping[str, Any],
    suite: Mapping[str, Any],
    suite_sha256: str,
    manifests: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """The CLIP-371 checks: suite digest, seed, job count, workflow identity, frozen inputs and runtime."""

    expected = {case["case_id"]: case for case in suite["cases"]}
    arms = {arm["arm_id"]: arm["form"] for arm in suite["arms"]}
    checks = [
        ("suite sha256 matches the frozen plan", run["suite"]["sha256"] == suite_sha256),
        ("run seed equals the suite seed", run["suite"]["seed"] == suite["seed"]),
        ("job count equals cases x arms", len(run["jobs"]) == len(expected) * len(arms)),
    ]
    wrong_workflow = wrong_input = 0
    runtimes: Counter[tuple[str, Any, Any]] = Counter()
    for (case_id, arm_id), manifest in manifests.items():
        form = arms[arm_id]
        wrong_workflow += (manifest.get("workflow_id"), manifest.get("workflow_version")) != (
            form["workflow_id"],
            form["workflow_version"],
        )
        inputs = (manifest.get("compiled_workflow") or {}).get("compiled_inputs") or {}
        case = expected[case_id]
        wrong_input += (
            inputs.get("seed") != suite["seed"]
            or inputs.get("prompt") != case["prompt"]
            or (inputs.get("negative_prompt") or "") != (case.get("negative_prompt") or "")
            or inputs.get("frame_count") != form["frame_count"]
        )
        actual = manifest.get("actual_runtime") or {}
        runtimes[(arm_id, actual.get("comfyui_version"), actual.get("pytorch_version"))] += 1
    checks.append(("every manifest names its arm's workflow id and version", wrong_workflow == 0))
    checks.append(
        ("seed, prompt, negative prompt and frame count are the suite's", wrong_input == 0)
    )
    checks.append(
        (
            "runtime identity is recorded for every clip",
            all(v[1] for v in runtimes) and bool(runtimes),
        )
    )
    return [{"check": name, "ok": bool(ok)} for name, ok in checks] + [
        {
            "check": "runtime identities",
            "ok": True,
            "detail": [list(k) + [n] for k, n in runtimes.items()],
        }
    ]


def read_ratings(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {(row["case_id"], row["arm_id"]): row for row in csv.DictReader(stream)}


def _number(row: Mapping[str, str], column: str) -> float | None:
    try:
        return float((row.get(column) or "").strip())
    except ValueError:
        return None


def rating_stats(
    ratings: Mapping[tuple[str, str], Mapping[str, str]], arm_id: str
) -> dict[str, Any]:
    rows = {case: row for (case, arm), row in ratings.items() if arm == arm_id}
    fidelity = [v for r in rows.values() if (v := _number(r, FIDELITY)) is not None]
    stability = [v for r in rows.values() if (v := _number(r, STABILITY)) is not None]
    actions = [(r.get("requested_action") or "").strip() for r in rows.values()]
    return {
        "cases": len(rows),
        "mean_fidelity": round(mean(fidelity), 3) if fidelity else None,
        "mean_stability": round(mean(stability), 3) if stability else None,
        "action_score": round(mean(ACTION_SCORE.get(a, 0.0) for a in actions), 3)
        if actions
        else None,
        "action_achieved": sum(a in ACHIEVED for a in actions),
        "breaks": sum(
            (r.get("critical_identity_break") or "").strip() == "yes" for r in rows.values()
        ),
        "rated": len(fidelity),
    }


def material_regression_cases(
    ratings: Mapping[tuple[str, str], Mapping[str, str]], baseline_arm: str, candidate_arm: str
) -> list[str]:
    """Cases where the candidate is >= 2 points lower on fidelity or stability, or has a break the baseline lacks."""

    rule = THRESHOLDS["no_go"]["material_regression"]
    found = []
    for (case, arm), row in ratings.items():
        base = ratings.get((case, baseline_arm))
        if arm != candidate_arm or base is None:
            continue
        drop = any(
            (b := _number(base, c)) is not None
            and (a := _number(row, c)) is not None
            and b - a >= rule["points_at_least"]
            for c in rule["dimensions"]
        )
        new_break = (row.get("critical_identity_break") or "").strip() == "yes" and (
            (base.get("critical_identity_break") or "").strip() != "yes"
        )
        if drop or new_break:
            found.append(case)
    return sorted(found)


def telemetry_summary(path: Path | None) -> dict[str, Any] | None:
    """Peak host commit fraction, lowest available RAM and peak VRAM from an owner-supplied JSON sample list.

    Each sample: ``{"time": "<ISO>", "commit_fraction": 0.71, "available_ram_gb": 6.4, "vram_used_mib": 11020}``; any
    key may be absent, and ``time`` is only needed for the per-arm split (``telemetry_by_arm``).
    """

    if path is None:
        return None
    samples = _read_json(path)
    samples = samples.get("samples", []) if isinstance(samples, dict) else samples

    def column(key: str) -> list[float]:
        return [float(s[key]) for s in samples if isinstance(s, dict) and s.get(key) is not None]

    commit, ram, vram = (
        column("commit_fraction"),
        column("available_ram_gb"),
        column("vram_used_mib"),
    )
    return {
        "samples": len(samples),
        "peak_commit_fraction": max(commit) if commit else None,
        "min_available_ram_gb": min(ram) if ram else None,
        "peak_vram_used_mib": max(vram) if vram else None,
    }


def telemetry_by_arm(
    path: Path | None,
    run: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Peaks per arm for samples that carry an ISO ``time``, over that arm's first start to last completion."""

    if path is None:
        return None
    samples = _read_json(path)
    samples = samples.get("samples", []) if isinstance(samples, dict) else samples
    windows: dict[str, list[str]] = defaultdict(list)
    for job in run["jobs"]:
        row = rows.get(job["job_id"]) or {}
        if row.get("started_at") and row.get("completed_at"):
            windows[job["arm_id"]] += [row["started_at"], row["completed_at"]]
    out: dict[str, dict[str, Any]] = {}
    for arm_id, stamps in windows.items():
        start, end = datetime.fromisoformat(min(stamps)), datetime.fromisoformat(max(stamps))
        inside = [
            s
            for s in samples
            if isinstance(s, dict)
            and s.get("time")
            and start <= datetime.fromisoformat(str(s["time"])) <= end
        ]

        def peak(key: str, pick, inside=inside) -> float | None:
            values = [float(s[key]) for s in inside if s.get(key) is not None]
            return pick(values) if values else None

        out[arm_id] = {
            "samples": len(inside),
            "peak_commit_fraction": peak("commit_fraction", max),
            "min_available_ram_gb": peak("available_ram_gb", min),
            "peak_vram_used_mib": peak("vram_used_mib", max),
        }
    return out


def verdict(
    *,
    stage: str,
    candidate_arm: str,
    baseline_arm: str,
    stats: Mapping[str, Mapping[str, Any]],
    wall: Mapping[str, Mapping[str, Any]],
    ratings: Mapping[tuple[str, str], Mapping[str, str]] | None,
    errors: Mapping[str, Sequence[str]],
    telemetry: Mapping[str, Any] | None,
    pairwise: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Apply the frozen plan's thresholds.  Anything not evidenced is reported as such, never assumed to pass."""

    no_go_rules, good, fast = (
        THRESHOLDS["no_go"],
        THRESHOLDS["as_good_or_better"],
        THRESHOLDS["faster"],
    )
    reasons: list[str] = []
    not_evidenced: list[str] = []
    for message in errors.get(candidate_arm, ()):
        if any(marker in message.lower() for marker in ALLOCATION_MARKERS):
            reasons.append(f"allocation failure or device loss: {message[:120]}")
    peak = (telemetry or {}).get("peak_commit_fraction")
    if peak is None:
        not_evidenced.append("host commit (no telemetry supplied)")
    elif peak >= no_go_rules["host_commit_fraction_at_or_above"]:
        reasons.append(
            f"host commit {peak:.2f} >= {no_go_rules['host_commit_fraction_at_or_above']}"
        )
    candidate, baseline = stats.get(candidate_arm, {}), stats.get(baseline_arm, {})
    if not candidate.get("rated"):
        not_evidenced.append("owner ratings (ratings.csv has no rated rows for the candidate)")
    else:
        needed = no_go_rules["stage1_action_achieved_cases_below"] / 8 * candidate["cases"]
        if stage == "stage1" and candidate["action_achieved"] < needed:
            reasons.append(
                f"action achieved {candidate['action_achieved']}/{candidate['cases']} (below {needed:g})"
            )
        if candidate["breaks"] > no_go_rules["critical_identity_breaks_above"]:
            reasons.append(f"{candidate['breaks']} critical identity breaks")
        if candidate["mean_fidelity"] < no_go_rules["mean_source_fidelity_below"]:
            reasons.append(f"mean fidelity {candidate['mean_fidelity']}")
        if candidate["mean_stability"] < no_go_rules["mean_subject_stability_below"]:
            reasons.append(f"mean stability {candidate['mean_stability']}")
        regressions = material_regression_cases(ratings or {}, baseline_arm, candidate_arm)
        if len(regressions) >= no_go_rules["material_regression"]["cases_at_least"]:
            reasons.append(f"material regression vs {baseline_arm} on {', '.join(regressions)}")
    as_good: bool | None = None
    if reasons:
        as_good = False
    elif stage == "stage1" and candidate.get("rated") and baseline.get("rated"):
        gap = good["stage1_mean_gap_at_most"]
        as_good = all(
            candidate[c] >= baseline[c] - gap
            for c in ("mean_fidelity", "mean_stability", "action_score")
        )
    elif (
        stage == "stage2" and pairwise and pairwise.get("overall_candidate_preference") is not None
    ):
        as_good = (
            pairwise["overall_candidate_preference"]
            >= good["stage2_blind_pairwise_preference_at_least"]
        )
    else:
        not_evidenced.append("quality comparison (needs owner ratings or the pairwise result)")
    faster: bool | None = None
    base_warm, cand_warm = wall[baseline_arm]["warm_median"], wall[candidate_arm]["warm_median"]
    if base_warm and cand_warm:
        ratio = round(cand_warm / base_warm, 3)
        faster = ratio <= fast["warm_wall_time_median_ratio_at_most"]
    else:
        ratio = None
        not_evidenced.append("warm wall-time ratio (needs warm jobs in both arms)")
    return {
        "candidate_arm": candidate_arm,
        "no_go": bool(reasons),
        "no_go_reasons": reasons,
        "as_good_or_better": as_good,
        "faster": faster,
        "warm_median_ratio": ratio,
        "not_evidenced": not_evidenced,
        "decision": "none: the analysis reports a verdict; adoption or promotion is the owner's decision",
    }


def _locate(path: str, run_dir: Path) -> Path | None:
    """A cell's clip path may be relative to the checkout that ran the job; try the cwd and the run folder's parents."""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    for base in (Path.cwd(), *run_dir.resolve().parents):
        if (base / candidate).exists():
            return base / candidate
    return None


def manifests_from_metrics(
    metrics: Mapping[str, Any], run_dir: Path
) -> dict[tuple[str, str], dict[str, Any]]:
    """Per-clip manifest of every cell that produced a clip, read from the run folder (read-only)."""

    cells = metrics["cells"]
    cells = cells if isinstance(cells, list) else list(cells.values())
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for cell in cells:
        clip = _locate(cell["path"], run_dir) if cell.get("path") else None
        if clip is None:
            continue
        manifest_files = sorted((clip.parent / "manifests").glob("*.json"))
        if manifest_files:
            found[(cell["case_id"], cell["arm_id"])] = _read_json(manifest_files[0])
    return found


def analyze_run(
    run_dir: Path,
    *,
    jobs_db: Path,
    suite_file: Path,
    suite_sha256: str,
    stage: str,
    baseline_arm: str,
    ratings_csv: Path | None = None,
    telemetry_file: Path | None = None,
    pairwise: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run = _read_json(run_dir / "run.json")
    suite = _read_json(suite_file)
    rows = job_rows(jobs_db, (job["job_id"] for job in run["jobs"]))
    metrics_file = run_dir / "metrics.json"
    manifests = (
        manifests_from_metrics(_read_json(metrics_file), run_dir) if metrics_file.is_file() else {}
    )
    ratings = read_ratings(ratings_csv) if ratings_csv and ratings_csv.is_file() else {}
    wall = wall_by_arm(run, rows)
    arms = [arm["arm_id"] for arm in suite["arms"]]
    stats = {arm: rating_stats(ratings, arm) for arm in arms}
    errors: dict[str, list[str]] = defaultdict(list)
    for job in run["jobs"]:
        row = rows.get(job["job_id"])
        if row and row["status"] != "completed" and row.get("error"):
            errors[job["arm_id"]].append(str(row["error"]))
    telemetry = telemetry_summary(telemetry_file)
    return {
        "run_id": run_dir.name,
        "stage": stage,
        "jobs": len(run["jobs"]),
        "checks": identity_checks(run, suite, suite_sha256, manifests),
        "manifests_read": len(manifests),
        "wall_seconds": wall,
        "ratings": stats,
        "telemetry": telemetry,
        "telemetry_by_arm": telemetry_by_arm(telemetry_file, run, rows),
        "verdicts": [
            verdict(
                stage=stage,
                candidate_arm=arm,
                baseline_arm=baseline_arm,
                stats=stats,
                wall=wall,
                ratings=ratings,
                errors=errors,
                telemetry=telemetry,
                pairwise=pairwise,
            )
            for arm in arms
            if arm != baseline_arm
        ],
    }


__all__ = [
    "analyze_run",
    "identity_checks",
    "job_rows",
    "verdict",
    "telemetry_by_arm",
    "wall_by_arm",
]
