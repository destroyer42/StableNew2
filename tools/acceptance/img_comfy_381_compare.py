"""IMG-COMFY-381 Forge-vs-ComfyUI SDXL comparison harness (PR B).

A thin observer around production authority, modelled on ``img_forge_100_acceptance``. For every matched pair it
freezes TWO NJRs through the normal compile (``build_cli_njr``) that differ only in ``backend_id``, submits each through

    JobService.submit_njrs -> SQLite JobRepository/JobQueue -> SingleNodeJobRunner ->
    PipelineController -> PipelineRunner.run_njr -> image backend registry -> backend

and reports what happened. It adds no second queue, runner, compiler or runtime owner: Forge runs under
``WebUIProcessManager`` (``ManagedWebUIRuntime``) and ComfyUI is owned by ``ComfyImageBackend`` itself. That backend
keeps its owned ComfyUI warm between consecutive SDXL jobs (PR-IMG-COMFY-382), so the first ComfyUI job is cold and later
ones are warm; the harness ends the hold when an arm finishes.

Outputs (new evidence directory only): ``plan.json``, ``compare.json``, ``review/contact_sheet.png``, ``review/review.csv``, ``review/rater.html`` (a blind A/B rating page that exports the CSV),
``review/images/*`` (metadata-free copies, blind A/B) and ``review_key.json`` (the only place the A/B mapping is recorded;
withhold it from the reviewer until ratings are in).

The verdict is always ``OWNER_REVIEW_PENDING`` and no numeric quality threshold exists. A physical run (no ``--dry``)
requires the owner's approved plan digest (``--approved-plan-sha256``); an agent never self-authorizes it.

    python -m tools.acceptance.img_comfy_381_compare --dry --reports-dir <new dir>
    python -m tools.acceptance.img_comfy_381_compare --runtime-profile <forge profile.json> --reports-dir <new dir> \
        --approved-plan-sha256 <digest from plan.json>
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.services.runtime_warm_hold import end_runtime_warm_hold, get_runtime_warm_hold
from tools.acceptance.img_forge_100_acceptance import (
    _DEVICE_LOSS,
    DEFAULT_INTENT,
    EXIT_COMPLETED,
    EXIT_DRY,
    EXIT_FAILED,
    EXIT_NOT_SUBMITTED,
    EXIT_STOPPED,
    AmbiguousDispatch,
    InjectedRuntime,
    ManagedWebUIRuntime,
    _artifacts,
    _await_terminal,
    _write_new,
    digest,
    freeze_njr,
    intent_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_ID = "IMG-COMFY-381"
SCHEMA_VERSION = 1
FORGE, COMFY = "forge_webui", "comfyui"
ARMS = (FORGE, COMFY)
VERDICT = "OWNER_REVIEW_PENDING"

# PR-IMG-BACKEND-QUAL-100 "Fairness critiques" (verbatim; wrapped lines joined by a space).
FAIRNESS_CAVEATS = (
    "Same weights/geometry/steps/seed mean controlled intent, not identical computation. Sampler implementations, "
    "schedulers (including Automatic resolution), precision/quantization and RNG behavior need explicit evidence. "
    "The proposal marks sampler/CLIP-skip mappings approximate and seed equality unverified. Forge Automatic VAE "
    "does not prove checkpoint-baked VAE identity. Reference-latent mechanisms differ. Torch versions differ. "
    "Historical Forge resource measurements were collected in other sessions/platform states and cannot establish "
    "a contemporary speed/VRAM advantage. Blind owner review of matched outputs is needed for keeper quality; "
    "no invented numerical quality threshold or default change is justified by the source ledger."
)
NOT_COMPARABLE = {
    "flux": "single-backend today (Forge only); not comparable",
    "qwen_image": "single-backend today (ComfyUI only); not comparable",
}
# Five neutral scene prompts after the frozen intent's own prompt; S1 uses all six, S3 the first two.
EXTRA_PROMPTS = (
    "a lighthouse on a rocky coast at dusk, long exposure, dramatic clouds",
    "a bowl of fresh citrus on a wooden table, soft window light, shallow depth of field",
    "an old library with tall shelves and floating dust motes, warm light",
    "a lone cyclist on a misty mountain road at dawn",
    "a bustling night market with paper lanterns and steam rising from food stalls",
)
REVIEW_COLUMNS = (
    "pair_id", "workload", "prompt_id", "seed", "image_a", "image_b",
    "fidelity_a", "fidelity_b", "detail_a", "detail_b", "artifacts_a", "artifacts_b", "preference_a_b_tie", "notes",
)  # fmt: skip
WORKLOADS = ("S1", "S3")


class PairMismatch(RuntimeError):
    """The two arms of a pair differ in something other than ``backend_id``."""


@dataclass(frozen=True)
class PairSpec:
    pair_id: str
    workload: str
    prompt_id: int
    prompt: str
    seed: int
    lora: bool


# --- Plan: matched pairs, frozen through production builders --------------------------------------------


def load_settings(intent_path: Path) -> dict[str, Any]:
    return json.loads(Path(intent_path).read_text(encoding="utf-8"))["settings"]


def build_pairs(settings: dict[str, Any], workloads: tuple[str, ...] = WORKLOADS) -> list[PairSpec]:
    """S1: SDXL baseline, 6 prompts x 2 seeds. S3: the same SDXL with the frozen LoRA, first 2 prompts x 2 seeds."""

    prompts = (str(settings["prompt"]), *EXTRA_PROMPTS)
    seeds = (int(settings["seed"]), int(settings["seed"]) + 1)
    pairs: list[PairSpec] = []
    for workload in workloads:
        if workload not in WORKLOADS:
            raise ValueError(f"unknown workload {workload!r}; choose from {WORKLOADS}")
        limit, lora = (len(prompts), False) if workload == "S1" else (2, True)
        for prompt_id, prompt in enumerate(prompts[:limit]):
            for seed in seeds:
                pairs.append(
                    PairSpec(
                        f"{workload}-p{prompt_id}-s{seed}", workload, prompt_id, prompt, seed, lora
                    )
                )
    return pairs


def job_id_for(spec: PairSpec, arm: str) -> str:
    return f"c381-{spec.pair_id}-{arm}"


def freeze_pair(settings: dict[str, Any], spec: PairSpec, output_root: Path) -> dict[str, Any]:
    """One NJR per arm, both through the normal compile; the pair must differ only in ``backend_id``."""

    values = {**settings, "prompt": spec.prompt, "seed": spec.seed}
    njrs = {
        arm: freeze_njr(
            values,
            arm,
            job_id=job_id_for(spec, arm),
            output_dir=output_root / arm,
            case="B" if spec.lora else "A",
        )
        for arm in ARMS
    }
    assert_matched(njrs[FORGE], njrs[COMFY])
    return njrs


_ARM_PATHS = (
    ("backend_options", "image", "backend_id"),
    ("workload", "backend_options", "image", "backend_id"),
)
_IDENTITY_PATHS = (
    ("job_id",),
    ("output_plan",),
    ("source", "display_name"),
    ("provenance", "metadata", "run_name"),
    ("workload", "metadata", "run_name"),
    ("workload", "intent_config", "requested_job_label"),
    ("provenance", "metadata", "batch_id"),
    ("provenance", "metadata", "review_batch", "batch_id"),
    ("workload", "metadata", "batch_id"),
    ("workload", "metadata", "review_batch", "batch_id"),
)


def _without(njr: Any, paths: tuple[tuple[str, ...], ...]) -> dict[str, Any]:
    data = json.loads(json.dumps(njr.to_dict(), default=str))
    for path in paths:
        node: Any = data
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return data


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: json.dumps(value, sort_keys=True, default=str)}


def assert_matched(forge_njr: Any, comfy_njr: Any) -> None:
    """Job identity and the backend id are the only permitted differences."""

    left = _flatten(_without(forge_njr, (*_IDENTITY_PATHS, *_ARM_PATHS)))
    right = _flatten(_without(comfy_njr, (*_IDENTITY_PATHS, *_ARM_PATHS)))
    differing = sorted(key for key in {*left, *right} if left.get(key) != right.get(key))
    if differing:
        raise PairMismatch(
            "the Forge and ComfyUI NJRs differ beyond backend_id: " + ", ".join(differing[:8])
        )
    for arm, njr in ((FORGE, forge_njr), (COMFY, comfy_njr)):
        recorded = (njr.backend_options or {}).get("image", {}).get("backend_id")
        if recorded != arm:
            raise PairMismatch(f"the {arm} NJR carries backend_id {recorded!r}")


def build_plan(
    settings: dict[str, Any], workloads: tuple[str, ...], output_root: Path
) -> dict[str, Any]:
    pairs = build_pairs(settings, workloads)
    frozen = []
    for spec in pairs:
        njrs = freeze_pair(settings, spec, output_root)
        frozen.append(
            {
                "pair_id": spec.pair_id, "workload": spec.workload, "prompt_id": spec.prompt_id, "prompt": spec.prompt,
                "seed": spec.seed, "lora": spec.lora,
                "intent_sha256": {arm: intent_digest(njrs[arm]) for arm in ARMS},
            }
        )  # fmt: skip
    body = {
        "spec": SPEC_ID, "schema_version": SCHEMA_VERSION, "workloads": list(workloads), "arms": list(ARMS),
        "settings_sha256": digest(settings), "pairs": frozen,
    }  # fmt: skip
    return {**body, "plan_sha256": digest(body)}


# --- Stack: the canonical wiring with an injectable image-backend registry ---------------------------------


def build_stack(
    state_dir: Path, output_dir: Path, client: Any, registry: Any = None, prepare: Any = None
) -> SimpleNamespace:
    from src.controller.job_service import JobService
    from src.controller.pipeline_controller import PipelineController
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.queue.single_node_runner import SingleNodeJobRunner
    from src.utils import StructuredLogger

    state_dir.mkdir(parents=True, exist_ok=True)
    repository = JobRepository(state_dir / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    worker = SingleNodeJobRunner(queue, run_callable=None, poll_interval=0.05)
    service = JobService(queue, runner=worker, history_store=repository)
    runner = PipelineRunner(
        api_client=client,
        structured_logger=StructuredLogger(),
        runs_base_dir=str(output_dir),
        image_backend_registry=registry,
    )
    if prepare is not None:
        prepare(runner)
    worker.run_callable = PipelineController(pipeline_runner=runner, job_service=service)._run_job
    service.auto_run_enabled = True
    return SimpleNamespace(service=service, repository=repository, client=client)


class ArmRuntime:
    """What one arm needs around its jobs: a runtime lifecycle, a client and (in tests) a registry."""

    def __init__(
        self,
        runtime: Any,
        client: Any = None,
        registry: Any = None,
        prepare: Any = None,
        sampler: Any = None,
    ) -> None:
        self.runtime, self.client, self.registry, self.prepare, self.sampler = (
            runtime,
            client,
            registry,
            prepare,
            sampler,
        )


# --- Run ---------------------------------------------------------------------------------------------------


def _manifest_facts(path: str | None) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        key: data[key]
        for key in ("image_backend_id", "model", "seed", "comfy_sdxl", "model_identity")
        if key in data
    }


def _run_arm(
    arm: str, jobs: list[tuple[PairSpec, Any]], context: ArmRuntime, reports: Path, timeout: float
) -> tuple[dict[str, Any], int]:
    """Run every job of one arm sequentially: the first is ``cold`` and the rest ``warm`` (no retries)."""

    from src.controller.submission_policy_v26 import SubmissionPolicy

    record: dict[str, Any] = {"arm": arm, "jobs": []}
    code, stack = EXIT_COMPLETED, None
    try:
        record["runtime_start"] = context.runtime.start()
        stack = build_stack(
            reports / "state" / arm,
            reports / "output" / arm,
            context.client,
            context.registry,
            context.prepare,
        )
        for index, (spec, njr) in enumerate(jobs):
            job_id = job_id_for(spec, arm)
            started = time.monotonic()
            with context.sampler or nullcontext() as peaks:
                stack.service.submit_njrs([njr], SubmissionPolicy(start_when_idle=True))
                entry = _await_terminal(stack.repository, job_id, timeout)
            status, error = entry.status.value, str(entry.error_message or "")
            artifacts = _artifacts(entry.result)
            record["jobs"].append(
                {
                    "pair_id": spec.pair_id, "job_id": job_id, "phase": "cold" if index == 0 else "warm", "status": status,
                    "error": error, "wall_seconds": round(time.monotonic() - started, 3),
                    "peaks": peaks.peaks.as_dict() if hasattr(peaks, "peaks") else None,
                    "result_metadata": (entry.result or {}).get("metadata"), "artifacts": artifacts,
                    "warm_hold_after_job": get_runtime_warm_hold().snapshot(),
                    "manifest": _manifest_facts(artifacts[0].get("manifest")) if artifacts else {},
                }
            )  # fmt: skip
            if any(marker in error.lower() for marker in _DEVICE_LOSS):
                return record, EXIT_STOPPED
            if status != "completed":
                return record, EXIT_FAILED  # stop rules: no retry, no substitution
    except AmbiguousDispatch as exc:
        record["classification"], record["error"], code = (
            "AMBIGUOUS_DISPATCH",
            str(exc),
            EXIT_STOPPED,
        )
    except Exception as exc:  # noqa: BLE001 - evidence first: record, stop, never retry
        record["error"], code = f"{type(exc).__name__}: {exc}", EXIT_STOPPED
    finally:
        if stack is not None:
            stack.service.stop()
            stack.repository.close()
        # A held ComfyUI would otherwise outlive its arm: end it through its registered owner before the next arm.
        record["warm_hold_end"] = end_runtime_warm_hold("comparison arm finished")
        record["runtime_stop"] = context.runtime.stop()
    return record, code


def _neutral_copy(source: str, target: Path) -> None:
    """A metadata-free re-encode (StableNew PNGs embed the backend id and prompt), so the review is blind."""

    from PIL import Image

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        pixels = image.convert("RGB")
    with target.open("xb") as stream:
        pixels.save(stream, format="PNG")


def _image_size(path: str) -> list[int]:
    from PIL import Image

    with Image.open(path) as image:
        return list(image.size)


def write_review(
    plan: dict[str, Any], arms: dict[str, dict[str, Any]], reports: Path, shuffle_seed: int
) -> dict[str, Any]:
    """Blind A/B images, contact sheet, CSV and (separately) the key."""

    from tools.qualification.img_forge_100.contact_sheet import create_contact_sheet

    by_pair: dict[str, dict[str, dict[str, Any]]] = {}
    for arm, record in arms.items():
        for job in record["jobs"]:
            if job["status"] == "completed" and job["artifacts"]:
                by_pair.setdefault(job["pair_id"], {})[arm] = job
    rng = random.Random(shuffle_seed)
    review = reports / "review"
    rows, key, sheet_pairs = [], {}, []
    for pair in plan["pairs"]:
        jobs = by_pair.get(pair["pair_id"], {})
        if set(jobs) != set(ARMS):
            continue
        order = list(ARMS)
        rng.shuffle(order)
        paths = {}
        for label, arm in zip(("A", "B"), order, strict=True):
            target = review / "images" / f"{pair['pair_id']}_{label}.png"
            _neutral_copy(jobs[arm]["artifacts"][0]["path"], target)
            paths[label] = target
        key[pair["pair_id"]] = {"A": order[0], "B": order[1]}
        sheet_pairs.append((pair["pair_id"], paths["A"], paths["B"]))
        rows.append(
            {
                "pair_id": pair["pair_id"], "workload": pair["workload"], "prompt_id": pair["prompt_id"], "seed": pair["seed"],
                "image_a": str(paths["A"].relative_to(review)), "image_b": str(paths["B"].relative_to(review)),
            }
        )  # fmt: skip
    if sheet_pairs:
        create_contact_sheet(sheet_pairs, review / "contact_sheet.png", labels=("A", "B"))
    review.mkdir(parents=True, exist_ok=True)
    with (review / "review.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    _write_new(reports / "review_key.json", {"shuffle_seed": shuffle_seed, "pairs": key})
    rater = None
    if rows:
        try:  # a convenience page: a failure to write it must never fail a finished physical run
            from tools.acceptance.img_comfy_381_rater import write_rater

            write_rater(review)
            rater = "review/rater.html"
        except Exception:  # noqa: BLE001
            rater = None
    return {
        "pairs_reviewed": len(rows),
        "contact_sheet": "review/contact_sheet.png" if sheet_pairs else None,
        "csv": "review/review.csv",
        "rater": rater,
    }


def build_compare(
    plan: dict[str, Any],
    arms: dict[str, dict[str, Any]],
    review: dict[str, Any],
    shuffle_seed: int,
    authorization: str,
) -> dict[str, Any]:
    pairs = []
    index = {arm: {job["pair_id"]: job for job in record["jobs"]} for arm, record in arms.items()}
    for pair in plan["pairs"]:
        entry: dict[str, Any] = {
            k: pair[k] for k in ("pair_id", "workload", "prompt_id", "seed", "lora")
        }
        for arm in ARMS:
            job = index.get(arm, {}).get(pair["pair_id"])
            artifact = (job or {}).get("artifacts") or [{}]
            entry[arm] = None if job is None else {
                "status": job["status"], "phase": job["phase"], "wall_seconds": job["wall_seconds"],
                "output_sha256": artifact[0].get("sha256"),
                "size": _image_size(artifact[0]["path"]) if artifact[0].get("path") else None,
                "approximations": (job["manifest"].get("comfy_sdxl") or {}).get("approximations") if arm == COMFY else None,
            }  # fmt: skip
        entry["seed_equality"] = "unverified"
        pairs.append(entry)
    return {
        "spec": SPEC_ID, "schema_version": SCHEMA_VERSION, "plan_sha256": plan["plan_sha256"], "authorization": authorization,
        "verdict": VERDICT, "perceptual_threshold": None, "shuffle_seed": shuffle_seed,
        "fairness_caveats": FAIRNESS_CAVEATS, "not_comparable": NOT_COMPARABLE,
        "timing_note": "ComfyUI is held warm by its backend between its own consecutive jobs (comfy_image_keep_warm_seconds); the first job of an arm is cold, later jobs reuse the running ComfyUI and its loaded model.",
        "arms": {arm: {k: v for k, v in record.items() if k != "jobs"} for arm, record in arms.items()},
        "pairs": pairs, "review": review,
    }  # fmt: skip


def run(args: argparse.Namespace, contexts: dict[str, ArmRuntime] | None, *, physical: bool) -> int:
    reports = Path(args.reports_dir).resolve()
    if reports.exists() and any(reports.iterdir()):
        raise FileExistsError(f"{reports} already holds evidence; choose a new --reports-dir")
    reports.mkdir(parents=True, exist_ok=True)
    settings = load_settings(Path(args.intent))
    workloads = tuple(args.workloads)
    plan = build_plan(settings, workloads, reports / "output")
    shuffle_seed = (
        int(args.shuffle_seed)
        if args.shuffle_seed is not None
        else int(plan["plan_sha256"][:8], 16)
    )
    _write_new(
        reports / "plan.json", {**plan, "shuffle_seed": shuffle_seed, "cwd": str(Path.cwd())}
    )
    if args.dry:
        print(
            json.dumps(
                {
                    "dry": True,
                    "plan_sha256": plan["plan_sha256"],
                    "pairs": len(plan["pairs"]),
                    "reports_dir": str(reports),
                }
            )
        )
        return EXIT_DRY
    if physical and args.approved_plan_sha256 != plan["plan_sha256"]:
        raise PermissionError(
            f"Physical execution requires the owner's approved plan digest {plan['plan_sha256']}"
        )
    if not contexts:
        raise ValueError("no arm runtimes were supplied")

    specs = {
        pair["pair_id"]: PairSpec(
            pair["pair_id"],
            pair["workload"],
            pair["prompt_id"],
            pair["prompt"],
            pair["seed"],
            pair["lora"],
        )
        for pair in plan["pairs"]
    }
    frozen = {pid: freeze_pair(settings, spec, reports / "output") for pid, spec in specs.items()}
    arms: dict[str, dict[str, Any]] = {}
    code = EXIT_NOT_SUBMITTED
    for arm in ARMS:
        jobs = [(specs[pid], frozen[pid][arm]) for pid in specs]
        arms[arm], code = _run_arm(arm, jobs, contexts[arm], reports, float(args.timeout_seconds))
        if code != EXIT_COMPLETED:
            break
    review = write_review(plan, arms, reports, shuffle_seed)
    compare = build_compare(
        plan, arms, review, shuffle_seed, args.approved_plan_sha256 if physical else "not_physical"
    )
    compare["exit_code"] = code
    _write_new(reports / "compare.json", compare)
    print(
        json.dumps(
            {
                "exit_code": code,
                "plan_sha256": plan["plan_sha256"],
                "verdict": VERDICT,
                "reports_dir": str(reports),
            }
        )
    )
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runtime-profile",
        type=Path,
        help="JSON launch profile for the Forge arm: command, working_dir, env_overrides, endpoint",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=None,
        help="a NEW evidence directory (default: reports/img_comfy_381_compare/<time>)",
    )
    parser.add_argument("--intent", type=Path, default=DEFAULT_INTENT)
    parser.add_argument("--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS))
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=None,
        help="seed for the blind A/B order (default: derived from the plan digest)",
    )
    parser.add_argument(
        "--approved-plan-sha256",
        default="",
        help="the owner-approved plan digest (from plan.json); required for a physical run",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--dry",
        action="store_true",
        help="freeze and write the plan only; start and submit nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.reports_dir = args.reports_dir or REPO_ROOT / "reports" / "img_comfy_381_compare" / str(
        int(time.time())
    )
    if args.dry:
        return run(args, None, physical=False)
    if args.runtime_profile is None:
        raise SystemExit("--runtime-profile (the Forge arm) is required for a physical run")
    if not args.approved_plan_sha256:
        raise SystemExit(
            "a physical run requires --approved-plan-sha256 (the owner's authorization of plan.json)"
        )
    profile = json.loads(args.runtime_profile.read_text(encoding="utf-8"))
    forge = ManagedWebUIRuntime(profile, FORGE)
    from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts
    from tools.qualification.vid110.monitor import ResourceSampler

    reports = Path(args.reports_dir).resolve()
    client = DefaultImageRuntimePorts(runtime_identity=FORGE).create_client(base_url=forge.endpoint)
    contexts = {
        FORGE: ArmRuntime(
            forge, client=client, sampler=ResourceSampler(log_path=reports / "telemetry_forge.csv")
        ),
        # ComfyUI is started, leased and released by ComfyImageBackend itself; the harness never owns it.
        COMFY: ArmRuntime(
            InjectedRuntime(),
            client=client,
            sampler=ResourceSampler(log_path=reports / "telemetry_comfyui.csv"),
        ),
    }
    return run(args, contexts, physical=True)


if __name__ == "__main__":
    sys.exit(main())
