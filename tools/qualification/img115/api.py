"""Forge API payloads, the dispatch ledger (no retry, no replay) and reference resolution. No network here."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .spec import (
    ASSETS,
    CASES,
    EDIT_DENOISE,
    EDIT_ENDPOINT,
    GUIDANCE,
    SAMPLER,
    SCHEDULER,
    STEPS,
    STITCH_MAX_DIM,
    STITCH_SCRIPT,
    T2I_ENDPOINT,
    digest,
    sha256_file,
)

PASS_STATES = {"passed"}


def options_payload(models_dir: Path) -> dict[str, Any]:
    """Select the checkpoint and the two modules through Forge's supported /options path (never override_settings)."""

    return {
        "sd_model_checkpoint": ASSETS["transformer"].filename,
        "forge_additional_modules": [str(Path(models_dir) / ASSETS[r].models_subdir / ASSETS[r].filename) for r in ("text_encoder", "vae")],
    }


def endpoint_for(case_id: str) -> str:
    return EDIT_ENDPOINT if CASES[case_id]["kind"] == "edit" else T2I_ENDPOINT


def build_payload(case_id: str, references_b64: list[str]) -> dict[str, Any]:
    """The generation request. txt2img for A/B. Edit (C/D): /img2img where reference 1 is the init image (Forge feeds it to
    Klein as a reference latent, ``klein_do_reference``) and further references go through the built-in ImageStitch script."""

    case = CASES[case_id]
    if bool(case["references"]) != bool(references_b64) or len(case["references"]) != len(references_b64):
        raise ValueError(f"case {case_id} needs {len(case['references'])} reference image(s), got {len(references_b64)}")
    payload: dict[str, Any] = {
        "prompt": case["prompt"], "negative_prompt": case["negative_prompt"], "steps": STEPS, "cfg_scale": GUIDANCE,
        "sampler_name": SAMPLER, "scheduler": SCHEDULER, "width": case["width"], "height": case["height"], "seed": case["seed"],
        "batch_size": 1, "n_iter": 1, "restore_faces": False, "tiling": False,
        "do_not_save_samples": True, "do_not_save_grid": True,
    }
    if case["kind"] == "txt2img":
        payload["enable_hr"] = False
        return payload
    payload.update({"init_images": [references_b64[0]], "denoising_strength": EDIT_DENOISE, "resize_mode": 0})
    if len(references_b64) > 1:
        payload["alwayson_scripts"] = {STITCH_SCRIPT: {"args": [True, list(references_b64[1:]), STITCH_MAX_DIM]}}
    return payload


def encode_reference(path: Path, expected_sha256: str) -> str:
    """Base64 of a reference whose bytes still hash to the frozen value (a changed reference is refused)."""

    if sha256_file(path) != expected_sha256:
        raise ValueError(f"reference {path} changed since it was frozen")
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


class Ledger:
    """Evidence/ledger.json: one entry per case; a case is dispatched at most once, ever."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"cases": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    @property
    def hard_stop(self) -> str:
        return str(self.data.get("hard_stop") or "")

    def set_hard_stop(self, reason: str) -> None:
        self.data["hard_stop"] = reason
        self._save()

    def state(self, case_id: str) -> str:
        return str(self.data["cases"].get(case_id, {}).get("state", ""))

    def begin(self, case_id: str) -> None:
        """Gate a case. Refuses a repeat (retry), a hard-stopped package and unmet predecessors."""

        if case_id not in CASES:
            raise ValueError(f"unknown case {case_id}")
        if self.hard_stop:
            raise RuntimeError(f"package is hard-stopped: {self.hard_stop}")
        if self.state(case_id):
            raise RuntimeError(f"case {case_id} already has state {self.state(case_id)!r}: no retry, no replay")
        if case_id != "A" and self.state("A") not in PASS_STATES:
            raise RuntimeError("Case A must pass before any other case")
        if case_id in ("C", "D") and self.state("A") not in PASS_STATES:
            raise RuntimeError(f"case {case_id} needs Case A's output")
        prior = self.data["cases"].get(case_id, {})
        self.data["cases"][case_id] = {"state": "dispatching", "dispatches": 0, "dispatches_total": prior.get("dispatches_total", 0)}
        self._save()

    def mark_dispatched(self, case_id: str) -> None:
        """Written BEFORE the generation POST: a crash leaves 'dispatched' (ambiguous), never a silent replay."""

        entry = self.data["cases"][case_id]
        entry["dispatches"] += 1
        entry["state"] = "dispatched"
        if entry["dispatches"] > 1:
            raise RuntimeError("second dispatch refused")
        self._save()

    def finish(self, case_id: str, state: str, **facts: Any) -> None:
        entry = self.data["cases"][case_id]
        entry.update(facts)
        entry["state"] = state
        self._save()

    def reopen_rejected(self, case_id: str, reason: str) -> None:
        """The single, explicit exception to 'no retry': a harness (infrastructure) defect repair.

        Allowed once per package, and only when the recorded dispatch was rejected by Forge's API layer (HTTP 5xx) before any
        generation work (no image, < 2 s). The dispatch counts stay cumulative and the repair is recorded.
        """

        entry = self.data["cases"].get(case_id, {})
        if self.data.get("repairs"):
            raise RuntimeError("the one infrastructure repair of this package is already used")
        if entry.get("state") != "failed" or not str(entry.get("http_status", "")).startswith("5") or entry.get("png_path") or float(entry.get("generation_seconds", 99)) >= 2.0:
            raise RuntimeError("only an API-layer rejection with no generation work can be reopened")
        self.data["repairs"] = [{"case": case_id, "reason": reason, "prior": dict(entry)}]
        self.data["cases"][case_id] = {"dispatches_total": int(entry.get("dispatches", 0)) + int(entry.get("dispatches_total", 0))}
        self._save()

    def output(self, case_id: str) -> dict[str, Any] | None:
        entry = self.data["cases"].get(case_id, {})
        return entry if entry.get("state") in PASS_STATES and entry.get("png_path") else None


def resolve_references(case_id: str, ledger: Ledger, frozen: dict[str, Any]) -> list[tuple[Path, str]]:
    """(path, frozen sha256) for each reference. Case D's second reference is B's output, else the pre-frozen fallback."""

    refs: list[tuple[Path, str]] = []
    for source in CASES[case_id]["references"]:
        out = ledger.output(source)
        if out is not None:
            refs.append((Path(out["png_path"]), out["png_sha256"]))
        elif source == "B" and frozen.get("fallback_reference_2"):
            fallback = frozen["fallback_reference_2"]
            refs.append((Path(fallback["path"]), fallback["sha256"]))
        else:
            raise RuntimeError(f"case {case_id} needs the output of case {source}, which did not pass")
    return refs


def frozen_digest(manifest: dict[str, Any]) -> str:
    return digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})


def check_frozen(manifest: dict[str, Any]) -> None:
    if manifest.get("manifest_sha256") != frozen_digest(manifest):
        raise ValueError("The frozen manifest changed after it was frozen")
