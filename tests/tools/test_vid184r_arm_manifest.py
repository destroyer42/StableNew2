"""PR-VID-184R: deterministic proof that Arm B differs from Arm A only by --disable-pinned-memory
(plus arm/evidence metadata) and that the frozen workload constants match PR-VID-184. No GPU."""

from __future__ import annotations

import json
from pathlib import Path

from tools.qualification.vid184 import scoring_contract as sc
from tools.qualification.vid184r import arm_manifest as am


def test_only_allowed_keys_differ() -> None:
    diff = am.diff_manifests(am.arm_manifest("A"), am.arm_manifest("B"))
    assert set(diff) <= am.ALLOWED_DIFF_KEYS
    assert set(diff) == {"arm", "launch_args", "evidence_dir", "pinned_memory_expected"}


def test_launch_difference_is_exactly_the_pinned_memory_flag() -> None:
    a, b = am.arm_manifest("A"), am.arm_manifest("B")
    assert am.launch_arg_difference(a, b) == ["--disable-pinned-memory"]
    assert b["launch_args"][:-1] == a["launch_args"]


def test_no_second_variable_flag_in_either_arm() -> None:
    for arm in ("A", "B"):
        joined = " ".join(am.launch_args(arm))
        for flag in am.FORBIDDEN_FLAGS:
            assert flag not in joined, (arm, flag)


def test_both_arms_bind_loopback_only_on_the_qualification_port() -> None:
    for arm in ("A", "B"):
        args = am.launch_args(arm)
        assert args[args.index("--listen") + 1] == "127.0.0.1"
        assert args[args.index("--port") + 1] == "8189"


def test_frozen_workload_matches_pr_vid_184_evidence() -> None:
    ev = json.loads(
        Path("tools/qualification/vid184/local_attempt_evidence.json").read_text(encoding="utf-8")
    )
    fw = am.FROZEN_WORKLOAD
    assert ev["environment"]["comfyui_sha"] == fw["comfyui_sha"]
    assert ev["frozen_inputs"]["reference_sha256"] == fw["reference_sha256"]
    assert ev["frozen_inputs"]["driving_39f_sha256"] == fw["driving_39f_sha256"]
    assert ev["frozen_inputs"]["seed"] == fw["seed"]
    assert ev["frozen_inputs"]["generation_length"] == fw["generation_length"]
    assert ev["frozen_inputs"]["evidence_frames"] == fw["evidence_frames"]
    for name, meta in ev["environment"]["models"].items():
        assert fw["model_sha256"][name] == meta["sha256"]


def test_frozen_scoring_contract_is_unchanged() -> None:
    assert (
        sc.contract_sha256() == sc.FROZEN_CONTRACT_SHA256 == am.FROZEN_WORKLOAD["contract_sha256"]
    )


def test_unknown_arm_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        am.launch_args("C")
