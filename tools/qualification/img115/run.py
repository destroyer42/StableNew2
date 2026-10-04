"""IMG-115 CLI: ``assets`` (verify + layout), ``freeze`` (write the frozen manifest), ``case A|B|C|D`` (one dispatch).

One process per case. Results go to <root>/evidence; a case is dispatched at most once (see api.Ledger).
Classes recorded per case: passed | technical_failure | integration_gap | resource_limit | ambiguous | hard_stop.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .api import (
    Ledger,
    build_payload,
    check_frozen,
    encode_reference,
    endpoint_for,
    frozen_digest,
    options_payload,
    resolve_references,
)
from .runtime import OwnedForge, assert_isolated, build_layout, launch_profile
from .spec import (
    ASSETS,
    CASES,
    FORGE_SHA,
    GUIDANCE,
    SAMPLER,
    SCHEDULER,
    STEPS,
    reject_substitution,
    sha256_file,
    verify_asset,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = Path.home() / "AppData" / "Local" / "StableNew" / "Qualification" / "IMG115_FLUX2_KLEIN_4B_FP8"
DEFAULT_INSTALL = Path.home() / "AppData" / "Local" / "StableNew" / "Forge" / "neo-d70373eb"
A1111 = Path.home() / "stable-diffusion-webui"
_OOM = ("out of memory", "cuda error", "cublas", "device-side assert")
_RESOURCE = ("out of memory",)


def _git_head() -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def _fallback_reference(path: Path) -> dict[str, str]:
    """A deterministic qualification-owned second reference, frozen BEFORE any dispatch (used only if Case B is invalid)."""

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1024, 1024), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 600, 450, 900), outline=(20, 20, 20), width=36)
    draw.ellipse((600, 600, 900, 900), outline=(20, 20, 20), width=36)
    draw.polygon([(300, 750), (520, 420), (780, 450), (750, 750)], fill=(190, 20, 30))
    draw.rectangle((470, 440, 700, 480), fill=(245, 245, 245))
    draw.rectangle((380, 380, 560, 430), fill=(25, 25, 25))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return {"path": str(path), "sha256": sha256_file(path)}


def cmd_assets(root: Path) -> dict[str, Any]:
    layout = build_layout(root)
    verified = {role: verify_asset(role, layout["assets"] / asset.filename) for role, asset in ASSETS.items()}
    reject_substitution({role: Path(v["path"]).name for role, v in verified.items()})
    models = layout["forge-data"] / "models"
    linked = {
        role: (models / a.models_subdir / a.filename).stat().st_ino == (layout["assets"] / a.filename).stat().st_ino
        for role, a in ASSETS.items()
    }
    return {"assets": verified, "linked_into_forge_data": linked, "total_bytes": sum(a.size for a in ASSETS.values())}


def cmd_freeze(root: Path, install: Path) -> dict[str, Any]:
    layout = build_layout(root)
    assert_isolated(root, repo_root=REPO_ROOT, managed_install=install, a1111_home=A1111)
    target = layout["evidence"] / "frozen-manifest.json"
    if target.exists():
        raise RuntimeError("the manifest is already frozen")
    assets = cmd_assets(root)
    py = install / "venv" / "Scripts" / "python.exe"
    code = "import sys,json,torch,torchvision;print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__,'torchvision':torchvision.__version__}))"
    facts = json.loads(subprocess.run([str(py), "-c", code], capture_output=True, text=True, check=True).stdout)
    profile = launch_profile(root, install)
    manifest = {
        "package": "PR-IMG-115",
        "result_class": "MODEL/RUNTIME QUALIFICATION",
        "qualification_source_sha": _git_head(),
        "forge_sha": FORGE_SHA,
        "runtime": facts,
        "assets": assets["assets"],
        "total_bytes": assets["total_bytes"],
        "forge_options": options_payload(layout["forge-data"] / "models") | {"forge_unet_storage_dtype": "Automatic (not set)"},
        "launch": {"command": profile["command"], "working_dir": profile["working_dir"], "endpoint": profile["endpoint"]},
        "inference": {
            "steps": STEPS, "guidance_cfg": GUIDANCE, "sampler": SAMPLER, "scheduler": SCHEDULER, "negative_prompt": "",
            "prompt_optimizer": False,
            "scheduler_note": "pinned Forge preset klein = Euler / Beta / 4 steps / CFG 1.0 (Automatic would resolve to Flux2)",
        },
        "cases": CASES,
        "fallback_reference_2": _fallback_reference(layout["evidence"] / "fallback-reference-2.png"),
        "roots": {k: str(v) for k, v in layout.items()},
    }
    manifest["manifest_sha256"] = frozen_digest(manifest)
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def cmd_repair(case_id: str, root: Path, reason: str) -> dict[str, Any]:
    """Record the harness repair (addendum at the current clean HEAD) and reopen ONE API-rejected case, once per package."""

    layout = build_layout(root)
    if subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
        raise RuntimeError("commit the repair before recording it")
    frozen = json.loads((layout["evidence"] / "frozen-manifest.json").read_text(encoding="utf-8"))
    check_frozen(frozen)
    record = json.loads((layout["evidence"] / f"case-{case_id}" / "record.json").read_text(encoding="utf-8"))
    ledger = Ledger(layout["evidence"] / "ledger.json")
    entry = ledger.data["cases"][case_id]
    entry.setdefault("http_status", record.get("http_status"))
    entry.setdefault("generation_seconds", record.get("generation_seconds"))
    ledger.reopen_rejected(case_id, reason)
    addendum = {"qualification_source_sha": _git_head(), "base_manifest_sha256": frozen["manifest_sha256"], "case": case_id, "reason": reason,
                "frozen_intent_changed": False}
    (layout["evidence"] / "frozen-addendum.json").write_text(json.dumps(addendum, indent=2), encoding="utf-8")
    return addendum


class _TreeSampler:
    """Forge tree RAM + system shared-GPU-memory spill evidence (typeperf is a built-in Windows tool)."""

    def __init__(self, forge: OwnedForge, csv_path: Path) -> None:
        self.forge, self.csv, self.stop = forge, csv_path, threading.Event()
        self.rows: list[tuple[float, float, float]] = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._typeperf: subprocess.Popen[str] | None = None
        self._t0 = time.monotonic()

    def __enter__(self) -> _TreeSampler:
        self.csv.parent.mkdir(parents=True, exist_ok=True)
        counters = [r"\GPU Adapter Memory(*)\Shared Usage", r"\GPU Adapter Memory(*)\Dedicated Usage"]
        try:  # measurement only (a built-in Windows tool); absence never blocks a case
            self._typeperf = subprocess.Popen(
                ["typeperf", *counters, "-si", "1", "-y", "-o", str(self.csv.with_suffix(".gpumem.csv"))],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
            )
        except OSError:
            self._typeperf = None
        self._t0 = time.monotonic()
        self._thread.start()
        return self

    def _run(self) -> None:
        import psutil

        while not self.stop.wait(1.0):
            rss = private = 0.0
            for pid in self.forge.process_tree_pids():
                try:
                    info = psutil.Process(pid).memory_info()
                    rss += info.rss / 2**20
                    private += getattr(info, "private", info.rss) / 2**20
                except psutil.Error:
                    pass
            self.rows.append((round(time.monotonic() - self._t0, 1), round(rss), round(private)))

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self._thread.join(timeout=3)
        if self._typeperf is not None:
            self._typeperf.terminate()
        header = "elapsed_s,forge_tree_rss_mib,forge_tree_private_mib\n"
        self.csv.write_text(header + "\n".join(",".join(map(str, r)) for r in self.rows), encoding="utf-8")

    def peaks(self) -> dict[str, Any]:
        shared: list[float] = []
        gpumem = self.csv.with_suffix(".gpumem.csv")
        if gpumem.exists():
            for line in gpumem.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
                cells = [c.strip('"') for c in line.split(",")[1:]]
                try:
                    nums = [float(c) for c in cells if c]
                except ValueError:
                    continue
                if nums:
                    shared.append(max(nums[: len(nums) // 2]))  # first half of the columns = Shared Usage per adapter
        return {
            "forge_tree_rss_peak_mib": max((r[1] for r in self.rows), default=0),
            "forge_tree_private_peak_mib": max((r[2] for r in self.rows), default=0),
            "shared_gpu_memory_peak_mib": round(max(shared, default=0) / 2**20, 1),
            "shared_gpu_memory_first_mib": round((shared[0] if shared else 0) / 2**20, 1),
        }


def _fault_events(start: datetime) -> list[dict[str, Any]]:
    from tools.qualification.img110r.orchestrate import fault_events_since

    return fault_events_since(start)


def _decode_png(b64: str, width: int, height: int) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image

    raw = base64.b64decode(b64.split(",")[-1])
    image = Image.open(io.BytesIO(raw))
    array = np.asarray(image.convert("RGB"), dtype=np.float32)
    facts: dict[str, Any] = {
        "size": list(image.size), "dimensions_ok": image.size == (width, height), "finite": bool(np.isfinite(array).all()),
        "pixel_std": round(float(array.std()), 2), "non_constant": bool(array.std() > 2.0),
    }
    facts["valid"] = facts["dimensions_ok"] and facts["finite"] and facts["non_constant"]
    return raw, facts


def _descendant_docs_only(frozen_sha: str) -> bool:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{frozen_sha}..HEAD"], capture_output=True, text=True)
    return out.returncode == 0 and all(n.startswith(("docs/", "STATUS.md")) for n in out.stdout.split())


def _wait_ready(http: Any, base: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if http.get(f"{base}/sdapi/v1/options", timeout=3).status_code == 200:
                return
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(1.0)
    raise RuntimeError("the owned Forge did not become ready")


def _select_model(http: Any, base: str, options: dict[str, Any], record: dict[str, Any]) -> None:
    response = http.post(f"{base}/sdapi/v1/options", json=options, timeout=600)
    record["options_status"] = response.status_code
    current = http.get(f"{base}/sdapi/v1/options", timeout=30).json()
    record["active_checkpoint"] = current.get("sd_model_checkpoint")
    record["active_modules"] = [Path(m).name for m in current.get("forge_additional_modules", [])]
    expected = [Path(m).name for m in options["forge_additional_modules"]]
    wrong = ASSETS["transformer"].filename not in str(record["active_checkpoint"]) or sorted(record["active_modules"]) != sorted(expected)
    if response.status_code != 200 or wrong:
        raise RuntimeError(f"the requested model/modules are not active: {record['active_checkpoint']} {record['active_modules']}")


def _classify_response(response: Any, case: dict[str, Any], case_dir: Path, outputs: Path, case_id: str, record: dict[str, Any]) -> tuple[str, str]:
    record["http_status"] = response.status_code
    if response.status_code != 200:
        record["error_body"] = response.text[:2000]
        text = response.text.lower()
        return "failed", ("resource_limit" if any(m in text for m in _RESOURCE) else "technical_failure")
    body = response.json()
    images = body.get("images") or []
    info = json.loads(body["info"]) if isinstance(body.get("info"), str) else (body.get("info") or {})
    record["seed_returned"] = info.get("seed")
    record["all_seeds"] = info.get("all_seeds")
    (case_dir / "response-info.json").write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
    if not images:
        return "failed", "technical_failure"
    raw, facts = _decode_png(images[0], case["width"], case["height"])
    out = outputs / f"case-{case_id}.png"
    out.write_bytes(raw)
    record.update({"png_path": str(out), "png_sha256": sha256_file(out), "image": facts, "images_returned": len(images)})
    return ("passed", "passed") if facts["valid"] else ("failed", "technical_failure")


def run_case(case_id: str, root: Path, install: Path, *, http: Any = None, forge: OwnedForge | None = None, events: Any = None) -> dict[str, Any]:
    import requests

    from tools.qualification.img110r.common import Telemetry

    http = http or requests
    events = events or _fault_events
    layout = build_layout(root)
    assert_isolated(root, repo_root=REPO_ROOT, managed_install=install, a1111_home=A1111)
    models, outputs = layout["forge-data"] / "models", layout["outputs"]
    case_dir = layout["evidence"] / f"case-{case_id}"
    frozen = json.loads((layout["evidence"] / "frozen-manifest.json").read_text(encoding="utf-8"))
    check_frozen(frozen)
    allowed = {frozen["qualification_source_sha"]}
    addendum = layout["evidence"] / "frozen-addendum.json"
    if addendum.exists():  # a recorded infrastructure repair of the harness (never of the frozen intent)
        extra = json.loads(addendum.read_text(encoding="utf-8"))
        if extra.get("base_manifest_sha256") != frozen["manifest_sha256"]:
            raise RuntimeError("the addendum does not belong to this frozen manifest")
        allowed.add(extra["qualification_source_sha"])
    if _git_head() not in allowed and not any(_descendant_docs_only(sha) for sha in allowed):
        raise RuntimeError("harness source changed since the manifest was frozen")
    ledger = Ledger(layout["evidence"] / "ledger.json")
    ledger.begin(case_id)
    case = CASES[case_id]
    refs = resolve_references(case_id, ledger, frozen)
    refs_b64 = [encode_reference(path, sha) for path, sha in refs]
    payload = build_payload(case_id, refs_b64)
    case_dir.mkdir(parents=True, exist_ok=True)
    shown = {k: v for k, v in payload.items() if k != "alwayson_scripts"}
    shown["references"] = len(refs_b64)
    (case_dir / "payload.json").write_text(json.dumps(shown, indent=2), encoding="utf-8")
    record: dict[str, Any] = {
        "case": case_id, "references": [{"path": str(p), "sha256": s} for p, s in refs], "seed_requested": case["seed"],
    }
    forge = forge or OwnedForge(launch_profile(root, install))
    pre_start = datetime.now()
    record["pre_events"] = events(datetime.fromtimestamp(time.time() - 600))
    state, klass = "failed", "technical_failure"
    progress: list[Any] = []
    stop_poll = threading.Event()
    clock = {"job": time.monotonic()}

    def poll() -> None:
        while not stop_poll.wait(1.0):
            try:
                info = http.get(f"{forge.base_url}/sdapi/v1/progress?skip_current_image=true", timeout=5).json()
                progress.append((round(time.monotonic() - clock["job"], 1), info.get("progress"), (info.get("state") or {}).get("sampling_step")))
            except Exception:  # noqa: BLE001 - observation only
                pass

    try:
        with Telemetry(case_dir / "telemetry.csv") as telemetry, _TreeSampler(forge, case_dir / "tree.csv") as tree:
            telemetry.stage = "launch"
            began = time.monotonic()
            record["runtime"] = forge.start()
            _wait_ready(http, forge.base_url, float(forge.profile["startup_timeout_seconds"]))
            record["ready_seconds"] = round(time.monotonic() - began, 1)
            record["owned_pids"] = forge.process_tree_pids()
            telemetry.stage = "model-select"
            t_select = time.monotonic()
            _select_model(http, forge.base_url, options_payload(models), record)
            record["model_select_seconds"] = round(time.monotonic() - t_select, 1)
            telemetry.stage = "generate"
            clock["job"] = time.monotonic()
            threading.Thread(target=poll, daemon=True).start()
            ledger.mark_dispatched(case_id)  # before the POST: a crash can only ever look ambiguous
            response = None
            url = f"{forge.base_url}{endpoint_for(case_id)}"  # built before the send: only a failed send is ambiguous
            try:
                response = http.post(url, json=payload, timeout=1800)
            except Exception as exc:  # noqa: BLE001 - outcome unknown: never replayed
                state, klass = "ambiguous", "ambiguous"
                record["error"] = f"{type(exc).__name__}: {exc}"
            record["generation_seconds"] = round(time.monotonic() - clock["job"], 1)
            stop_poll.set()
            if response is not None:
                state, klass = _classify_response(response, case, case_dir, outputs, case_id, record)
            telemetry.stage = "stopping"
        record["telemetry_peaks"] = telemetry.peaks.as_dict()
        record["memory_peaks"] = tree.peaks()
    except RuntimeError as exc:
        record["error"] = str(exc)
        state, klass = ("ambiguous", "ambiguous") if ledger.state(case_id) == "dispatched" else ("failed", "infrastructure")
    finally:
        stop_poll.set()
        record["stop"] = forge.stop()
        try:
            record["console_tail"] = forge.manager.get_stdout_tail_text()[-6000:] if forge.manager is not None else ""
        except Exception:  # noqa: BLE001
            record["console_tail"] = ""
    record["progress_samples"] = progress[-40:]
    record["post_events"] = events(pre_start)
    tail = str(record.get("console_tail", "")).lower()
    record["oom_markers"] = [m for m in _OOM if m in tail]
    hard = [e for e in record["post_events"] if e.get("provider") in {"nvlddmkm", "Display", "Microsoft-Windows-WHEA-Logger"} or e.get("id") == 41]
    if hard:
        state, klass = "hard_stop", "hard_stop"
        ledger.set_hard_stop(f"case {case_id}: {hard[0]}")
    elif state == "failed" and any(m in tail for m in _RESOURCE):
        klass = "resource_limit"
    record["state"], record["class"] = state, klass
    ledger.finish(case_id, state, **{k: record[k] for k in ("png_path", "png_sha256", "http_status", "generation_seconds") if k in record}, **{"class": klass})
    (case_dir / "record.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["assets", "freeze", "case", "repair"])
    parser.add_argument("case", nargs="?", choices=sorted(CASES))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    args = parser.parse_args(argv)
    if args.command == "assets":
        print(json.dumps(cmd_assets(args.root), indent=2))
    elif args.command == "repair":
        print(json.dumps(cmd_repair(args.case, args.root, "txt2img+ImageStitch rejected by the Forge API layer; edit now uses /img2img"), indent=2))
    elif args.command == "freeze":
        manifest = cmd_freeze(args.root, args.install)
        print(json.dumps({k: manifest[k] for k in ("manifest_sha256", "qualification_source_sha", "runtime")}, indent=2))
    else:
        if not args.case:
            parser.error("case requires A, B, C or D")
        record = run_case(args.case, args.root, args.install)
        keys = ("case", "state", "class", "ready_seconds", "model_select_seconds", "generation_seconds", "png_sha256", "image",
                "seed_returned", "telemetry_peaks", "memory_peaks", "oom_markers", "error")
        print(json.dumps({k: record.get(k) for k in keys}, indent=2, default=str))
        return 0 if record["state"] == "passed" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
