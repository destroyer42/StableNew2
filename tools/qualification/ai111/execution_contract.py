"""Qualification-only immutable contract selection. No artifact discovery or execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ai_assist.argv import ALLOWED_FLAGS, RunLimits, Sampling, assert_argv_allowed, build_argv
from src.ai_assist.manifests import ModelEntry, ModelRegistry, load_model_registry
from tools.qualification.ai111 import plan as legacy
from tools.qualification.ai111.corpus import Case, build_corpus, stage_a_subset


@dataclass(frozen=True)
class ExecutionSpec:
    selector: str
    sha256: str
    _document_json: str

    @property
    def document(self) -> dict[str, Any]:
        # A caller gets a copy, never a mutable reference to this specification.
        return json.loads(self._document_json)

    @property
    def runtime(self) -> dict[str, Any]:
        doc = self.document
        return (
            doc["runtime"]["candidates"][doc["runtime"]["selected"]]
            if self.selector == "lfm3-v1"
            else doc["runtime_intent"]
        )

    @property
    def members(self) -> dict[str, str]:
        if self.selector == "lfm3-v1":
            return self.runtime["members"]
        from tools.qualification.ai111.d12a import AUTHORIZED_MEMBERS

        return dict(AUTHORIZED_MEMBERS)

    def cases(self, stage: str) -> tuple[Case, ...]:
        if stage not in ("A", "B"):
            raise ValueError("unknown qualification stage")
        if self.selector == "lfm3-v1":
            from tools.qualification.ai111.final_plan import final_corpus
            from tools.qualification.ai111.lfm3_contract import STAGE_A_SEED

            cases = final_corpus()
            return tuple(stage_a_subset(cases, 30, STAGE_A_SEED) if stage == "A" else cases)
        doc = self.document
        cases = build_corpus(doc["corpus"]["seed"], doc["corpus"]["counts"])
        return tuple(
            stage_a_subset(cases, doc["stages"]["A"]["cases_per_arm"], doc["corpus"]["seed"])
            if stage == "A"
            else cases
        )

    def arm(self, arm_id: str) -> ArmSpec:
        doc = self.document
        registry = load_model_registry(legacy.REGISTRY_PATH)
        if self.selector == "lfm3-v1":
            arm = next(
                (a for a in doc["arms"] if a["arm_id"] == arm_id and a["kind"] != "baseline"), None
            )
            if arm is None:
                raise ValueError("unknown executable arm")
            model_id = arm.get("model_id") or arm["model"]["model_id"]
            registry = ModelRegistry(
                (
                    *registry.entries,
                    *load_model_registry(
                        json.dumps({"schema_version": 1, "models": doc["candidates"]})
                    ).entries,
                )
            )
            profile = arm["sampling"]
        else:
            model_id, profile = arm_id, "qwen_frozen"
        model = next((m for m in registry.entries if m.model_id == model_id), None)
        if model is None:
            raise ValueError("unknown model")
        return ArmSpec(self, arm_id, model, profile)

    def registry(self, arm_ids: list[str]) -> ModelRegistry:
        return ModelRegistry(
            tuple({a.model.model_id: a.model for a in map(self.arm, arm_ids)}.values())
        )

    def execution_plan(self) -> dict[str, Any]:
        if self.selector == "qwen-frozen":
            return self.document
        plan = legacy.frozen_plan()
        plan["runtime_intent"] = self.runtime
        plan["limits"] = self.document["limits"]
        return plan


@dataclass(frozen=True)
class ArmSpec:
    contract: ExecutionSpec
    arm_id: str
    model: ModelEntry
    profile: str

    @property
    def sampling(self) -> dict[str, Any]:
        return (
            self.contract.document["sampling"][self.profile]
            if self.contract.selector == "lfm3-v1"
            else self.contract.document["sampling"]
        )

    def argv(
        self, model: Path, prompt: Path, schema: Path, limits: RunLimits, sampling: Sampling
    ) -> list[str]:
        if self.profile.startswith("lfm3_"):
            from tools.qualification.ai111.lfm3_contract import LFM3_ALLOWED_FLAGS, lfm3_argv

            argv = lfm3_argv(self.profile, model, prompt, schema, limits)
            assert_argv_allowed(argv, LFM3_ALLOWED_FLAGS)
        else:
            argv = build_argv(model, prompt, schema, limits, Sampling(**self.sampling))
            assert_argv_allowed(argv, ALLOWED_FLAGS)
        return argv

    def identity(self, executable: str) -> dict[str, Any]:
        if executable not in self.contract.members:
            raise ValueError("executable is not explicitly permitted")
        return {
            "contract_sha256": self.contract.sha256,
            "arm": self.arm_id,
            "model_id": self.model.model_id,
            "model_sha256": self.model.sha256,
            "sampling_profile": self.profile,
            "sampling_values": self.sampling,
            "runtime_asset_sha256": self.contract.runtime["sha256"],
            "runtime_member_sha256": self.contract.members[executable],
            "executable": executable,
        }


def select_contract(selector: str = "qwen-frozen", sha256: str | None = None) -> ExecutionSpec:
    if selector == "qwen-frozen":
        document = legacy.frozen_plan()
    elif selector == "lfm3-v1":
        from tools.qualification.ai111.lfm3_contract import contract, validate_contract

        document = contract()
        problems = validate_contract(document)
        if problems:
            raise ValueError("invalid frozen contract: " + "; ".join(problems))
    else:
        raise ValueError("unknown qualification contract/version")
    actual = legacy.digest(document)
    if selector == "qwen-frozen":
        from tools.qualification.ai111.lfm3_contract import QWEN_FROZEN

        if actual != QWEN_FROZEN["screening_plan_sha256"]:
            raise ValueError("Qwen frozen plan identity changed")
    if sha256 is not None and sha256 != actual:
        raise ValueError("contract digest mismatch")
    return ExecutionSpec(selector, actual, json.dumps(document, sort_keys=True))
