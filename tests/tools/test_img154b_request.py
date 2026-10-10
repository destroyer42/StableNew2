"""PR-IMG-MODELS-154B T01-T08: pinned request semantics, the immutable payload constructor and option/infotext verification.

Synthetic source text and fakes only. The optional real-source check is read-only and opt-in
(``STABLENEW_IMG154B_FORGE_SOURCE=<managed Forge source dir>``): it reads text, never imports or executes it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path

import pytest

from tools.qualification.img154 import manifest as mf
from tools.qualification.img154b import request as rq

#: The frozen intent digest of PR-IMG-MODELS-154A. The 154B reconciliation changed an ENCODING, never a sampling value.
FROZEN_INTENT_DIGEST_154A = "03edcf1c1b99e7a57a711e481271c354051da32db7a9bba2c68ecf6ea105522a"

SERVED = {
    "transformer": "C:/qual/forge-data/models/Stable-diffusion/zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors",
    "text_encoder": "C:/qual/forge-data/models/text_encoder/qwen3_4b_2964436.safetensors",
    "vae": "C:/qual/forge-data/models/VAE/flux1AE_v10.safetensors",
}

FIELD_LINES = {
    "prompt": '    prompt: str = ""',
    "negative_prompt": '    negative_prompt: str = ""',
    "seed": "    seed: int = -1",
    "steps": "    steps: int = 50",
    "sampler_name": "    sampler_name: str = None",
    "scheduler": "    scheduler: str = None",
    "cfg_scale": "    cfg_scale: float = 7.0",
    "distilled_cfg_scale": "    distilled_cfg_scale: float = 3.5",
    "width": "    width: int = 512",
    "height": "    height: int = 512",
    "batch_size": "    batch_size: int = 1",
    "n_iter": "    n_iter: int = 1",
    "send_images": '{"key": "send_images", "type": bool, "default": True},',
    "save_images": '{"key": "save_images", "type": bool, "default": False},',
}


def synthetic_source(*, drop=(), reorder=(), add=None, omit_files=()):
    """A text tree that contains exactly the anchored fragments, optionally mutated."""

    files: dict[str, list[str]] = {}
    for anchor in rq.PINNED_ANCHORS:
        lines = files.setdefault(anchor.file, [])
        for fragment in (*anchor.present, *anchor.ordered):
            if anchor.anchor_id in drop and fragment in drop:
                continue
            lines.append(fragment)
        if anchor.anchor_id in reorder:
            lines[:] = list(reversed(lines))
    for key, (relative, _) in rq.PAYLOAD_KEY_SOURCES.items():
        if key in drop:
            continue
        files.setdefault(relative, []).append(FIELD_LINES[key])
    for relative, extra in (add or {}).items():
        files.setdefault(relative, []).append(extra)
    return {
        relative: "\n".join(lines) + "\n"
        for relative, lines in files.items()
        if relative not in omit_files
    }


def reader(tree):
    return lambda relative: tree.get(relative)


# --- T01: frozen values and payload shape --------------------------------------------------------------------------------


def test_t01_the_frozen_sampling_intent_is_unchanged_by_the_reconciliation():
    plan = mf.build_manifest()
    assert plan.request_digest() == FROZEN_INTENT_DIGEST_154A
    intent = plan.intent
    assert (intent.cfg_scale, intent.shift, intent.scheduler, intent.sampler) == (
        1.0,
        9.0,
        "Beta",
        "Euler",
    )
    assert (intent.steps, intent.seed, intent.width, intent.height) == (9, 424254, 1024, 1024)
    assert (intent.batch_size, intent.n_iter, intent.negative_prompt) == (1, 1, "")


def test_t01_payload_encodes_shift_as_distilled_cfg_scale_and_never_as_a_shift_or_guidance_key():
    payload = rq.build_txt2img_payload()
    body = dict(payload.body)
    assert payload.endpoint == "/sdapi/v1/txt2img"
    assert tuple(body) == rq.PAYLOAD_KEYS
    assert body["distilled_cfg_scale"] == 9.0
    assert (
        body["cfg_scale"] == 1.0
    )  # NOT the model card's 0.0, which would select the unconditional prediction
    assert body["scheduler"] == "Beta" and body["sampler_name"] == "Euler"
    assert body["steps"] == 9 and body["seed"] == 424254
    assert "shift" not in body and "guidance_scale" not in body
    assert body["send_images"] is True and body["save_images"] is False
    assert not set(body) & set(mf.FORBIDDEN_REQUEST_KEYS)
    assert rq.INTENT_TO_PAYLOAD_KEY["shift"] == "distilled_cfg_scale"


def test_t01_payload_is_immutable_and_its_wire_bytes_are_canonical_and_stable():
    payload = rq.build_txt2img_payload()
    with pytest.raises(TypeError):
        payload.body["cfg_scale"] = 0.0  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        payload.endpoint = "/other"  # type: ignore[misc]
    assert json.loads(payload.wire_bytes) == dict(payload.body)
    assert payload.wire_bytes == rq.build_txt2img_payload().wire_bytes
    assert payload.payload_digest == rq.build_txt2img_payload().payload_digest
    assert payload.intent_digest == FROZEN_INTENT_DIGEST_154A
    assert b" " not in payload.wire_bytes.replace(
        b"A ceramic teapot on a wooden table beside a window, soft daylight, studio photograph.",
        b"",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"cfg_scale": 0.0},
        {"cfg_scale": 2.0},
        {"shift": 0.0},
        {"shift": float("nan")},
        {"shift": float("inf")},
        {"negative_prompt": "blurry"},
        {"batch_size": 2},
        {"n_iter": 2},
        {"workflow": "img2img"},
        {"seed": 1},
        {"automatic_retry": True},
        {"automatic_replay": True},
    ],
)
def test_t01_any_intent_other_than_the_frozen_one_is_refused(mutation):
    plan = mf.QualificationManifest(intent=mf.FrozenIntent(**mutation))
    with pytest.raises(rq.RequestRefused):
        rq.build_txt2img_payload(plan)


def test_t01_non_frozen_construction_still_refuses_unestablished_semantics():
    # A different seed is a different case (allowed when not requiring the frozen digest) but CFG 0.0 is never established.
    plan = mf.QualificationManifest(intent=mf.FrozenIntent(seed=1))
    assert rq.build_txt2img_payload(plan, require_frozen=False).body["seed"] == 1
    with pytest.raises(rq.RequestRefused):
        rq.build_txt2img_payload(
            mf.QualificationManifest(intent=mf.FrozenIntent(cfg_scale=0.0)), require_frozen=False
        )


# --- T02: verify_payload -------------------------------------------------------------------------------------------------


def test_t02_the_constructed_body_verifies_and_any_drift_or_plausible_key_does_not():
    good = dict(rq.build_txt2img_payload().body)
    assert rq.verify_payload(good) == []
    assert [f.code for f in rq.verify_payload(None)] == ["PAYLOAD_NOT_PRESENTED"]
    cases = {
        "shift_key": {**good, "shift": 9.0},  # plausible and silently ignored by the pinned model
        "guidance": {**good, "guidance_scale": 0.0},
        "hires": {**good, "enable_hr": False},
        "override": {**good, "override_settings": {}},
        "scripts": {**good, "alwayson_scripts": {}},
        "extra": {**good, "restore_faces": False},
        "missing": {k: v for k, v in good.items() if k != "distilled_cfg_scale"},
        "drift": {**good, "seed": 7},
        "cfg_zero": {**good, "cfg_scale": 0.0},
    }
    for name, body in cases.items():
        findings = rq.verify_payload(body)
        assert findings, name
        assert all(f.severity == "refuse" for f in findings), name


# --- T03: source anchors -------------------------------------------------------------------------------------------------


def test_t03_a_source_that_states_every_anchor_verifies():
    assert rq.verify_pinned_semantics(reader(synthetic_source())) == []


def test_t03_every_anchor_is_necessary_dropping_any_one_fragment_refuses():
    for anchor in rq.PINNED_ANCHORS:
        for fragment in anchor.present:
            tree = synthetic_source()
            tree[anchor.file] = tree[anchor.file].replace(fragment, "")
            findings = rq.verify_pinned_semantics(reader(tree))
            assert any(
                f.code == "SEMANTICS_ANCHOR_MISSING" and anchor.anchor_id in f.detail
                for f in findings
            ), (
                anchor.anchor_id,
                fragment,
            )


def test_t03_ordering_anchors_refuse_when_the_order_changes():
    for anchor in (a for a in rq.PINNED_ANCHORS if len(a.ordered) > 1):
        tree = synthetic_source()
        tree[anchor.file] = "\n".join(reversed(tree[anchor.file].splitlines())) + "\n"
        findings = rq.verify_pinned_semantics(reader(tree))
        assert any(
            f.code == "SEMANTICS_ANCHOR_ORDER" and anchor.anchor_id in f.detail for f in findings
        ), anchor.anchor_id


def test_t03_a_forbidden_fragment_and_an_unreadable_file_are_findings_not_passes():
    tree = synthetic_source(add={"modules/api/models.py": 'ConfigDict(extra="forbid")'})
    assert "SEMANTICS_ANCHOR_FORBIDDEN_PRESENT" in {
        f.code for f in rq.verify_pinned_semantics(reader(tree))
    }
    tree = synthetic_source(
        add={"backend/diffusion_engine/zimage.py": "self.use_distilled_cfg_scale = True"}
    )
    assert "SEMANTICS_ANCHOR_FORBIDDEN_PRESENT" in {
        f.code for f in rq.verify_pinned_semantics(reader(tree))
    }
    findings = rq.verify_pinned_semantics(
        reader(synthetic_source(omit_files=("modules/sd_schedulers.py",)))
    )
    assert {f.code for f in findings} == {"SEMANTICS_SOURCE_UNREADABLE"}
    assert all(f.severity == "inconclusive" for f in findings)

    def raising(relative):
        raise OSError("denied")

    assert {f.code for f in rq.verify_pinned_semantics(raising)} == {"SEMANTICS_SOURCE_UNREADABLE"}


def test_t03_a_payload_key_the_pinned_model_does_not_define_is_refused():
    findings = rq.verify_pinned_semantics(reader(synthetic_source(drop=("distilled_cfg_scale",))))
    assert [f.code for f in findings] == ["PAYLOAD_KEY_NOT_DEFINED_BY_PINNED_MODEL"]
    assert "distilled_cfg_scale" in findings[0].detail


def test_t03_crlf_source_text_is_accepted():
    tree = {k: v.replace("\n", "\r\n") for k, v in synthetic_source().items()}
    assert rq.verify_pinned_semantics(reader(tree)) == []


def test_t03_forge_source_reader_is_confined_to_the_named_tree(tmp_path):
    (tmp_path / "src" / "modules").mkdir(parents=True)
    (tmp_path / "src" / "modules" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    read = rq.forge_source_reader(tmp_path / "src")
    assert read("modules/a.py") == "x = 1\n"
    assert read("modules/missing.py") is None
    assert read("../secret.txt") is None
    assert read("../../" + tmp_path.name + "/secret.txt") is None


@pytest.mark.skipif(
    not os.environ.get("STABLENEW_IMG154B_FORGE_SOURCE"),
    reason="opt-in read-only check against a managed Forge source tree (STABLENEW_IMG154B_FORGE_SOURCE)",
)
def test_t03_real_pinned_source_states_every_anchor():
    source = Path(os.environ["STABLENEW_IMG154B_FORGE_SOURCE"])
    assert rq.verify_pinned_semantics(rq.forge_source_reader(source)) == []


# --- T04: sampling options -----------------------------------------------------------------------------------------------


def default_options(**overrides):
    options = dict(rq.EXPECTED_SAMPLING_OPTIONS)
    options["hide_schedulers"] = []
    options.update(overrides)
    return options


def test_t04_default_sampling_options_verify():
    assert rq.verify_sampling_options(default_options()) == []
    assert rq.verify_sampling_options(default_options(beta_dist_alpha=0.6000000001)) == []


@pytest.mark.parametrize(
    "name,value",
    [
        ("beta_dist_alpha", 0.5),
        ("beta_dist_beta", 1.0),
        ("sigma_max", 14.6),
        ("rho", 7.0),
        ("skip_early_cond", 0.1),
        ("s_min_uncond", 1.0),
        ("s_min_uncond_all", True),
        ("always_discard_next_to_last_sigma", True),
        ("sgm_noise_multiplier", True),
        ("eta_noise_seed_delta", 31337),
        ("randn_source", "GPU"),
        ("face_restoration", True),
        ("tiling", True),
        ("forge_unet_storage_dtype", "fp8e4m3fn"),
    ],
)
def test_t04_a_non_default_sampling_option_refuses(name, value):
    findings = rq.verify_sampling_options(default_options(**{name: value}))
    assert [f.code for f in findings] == ["OPTION_NOT_DEFAULT"]


def test_t04_missing_options_unread_options_and_a_hidden_beta_scheduler_fail_closed():
    options = default_options()
    del options["beta_dist_alpha"]
    assert [f.code for f in rq.verify_sampling_options(options)] == ["OPTION_MISSING"]
    assert [f.code for f in rq.verify_sampling_options(None)] == ["OPTIONS_NOT_READ"]
    assert [
        f.code for f in rq.verify_sampling_options(default_options(hide_schedulers=["Beta"]))
    ] == ["SCHEDULER_HIDDEN"]
    assert [
        f.code for f in rq.verify_sampling_options(default_options(hide_schedulers=["beta"]))
    ] == ["SCHEDULER_HIDDEN"]
    broken = default_options()
    del broken["hide_schedulers"]
    assert [f.code for f in rq.verify_sampling_options(broken)] == ["OPTION_MISSING"]
    # a boolean is not a number: False must not satisfy a 0.0 default silently
    assert [f.code for f in rq.verify_sampling_options(default_options(sigma_min=False))] == [
        "OPTION_NOT_DEFAULT"
    ]


# --- T05: selection ------------------------------------------------------------------------------------------------------


def test_t05_selection_payload_names_the_checkpoint_and_exactly_the_two_served_modules():
    body = rq.selection_payload(SERVED)
    assert body == {
        "sd_model_checkpoint": "zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors",
        "forge_additional_modules": [SERVED["text_encoder"], SERVED["vae"]],
    }
    with pytest.raises(rq.RequestRefused):
        rq.selection_payload({k: v for k, v in SERVED.items() if k != "vae"})


def read_back(**overrides):
    options = {
        "sd_model_checkpoint": "zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors [59610861d4]",
        "forge_additional_modules": [
            SERVED["vae"],
            SERVED["text_encoder"],
        ],  # Forge sorts the module paths
    }
    options.update(overrides)
    return options


def identity(path):
    return path


def test_t05_the_exact_served_selection_verifies_in_either_order():
    assert rq.verify_selection(read_back(), SERVED, resolve=identity) == []
    assert (
        rq.verify_selection(
            read_back(forge_additional_modules=[SERVED["text_encoder"], SERVED["vae"]]),
            SERVED,
            resolve=identity,
        )
        == []
    )
    # case and separator differences on the same path are not a different file (Windows)
    shouting = [SERVED["vae"].upper().replace("/", "\\"), SERVED["text_encoder"]]
    assert (
        rq.verify_selection(read_back(forge_additional_modules=shouting), SERVED, resolve=identity)
        == []
    )


@pytest.mark.parametrize(
    "overrides,code",
    [
        (
            {"forge_additional_modules": [SERVED["text_encoder"]]},
            "SELECTION_MODULES_MISMATCH",
        ),  # silently dropped name
        ({"forge_additional_modules": []}, "SELECTION_MODULES_MISMATCH"),
        (
            {
                "forge_additional_modules": [
                    SERVED["text_encoder"],
                    SERVED["vae"],
                    "C:/lib/other.safetensors",
                ]
            },
            "SELECTION_MODULES_MISMATCH",
        ),
        (
            {
                "forge_additional_modules": [
                    SERVED["text_encoder"],
                    "C:/library/VAE/flux1AE_v10.safetensors",
                ]
            },
            "SELECTION_MODULES_MISMATCH",  # same name, a different (library) file
        ),
        (
            {"forge_additional_modules": [SERVED["vae"], SERVED["vae"]]},
            "SELECTION_MODULES_MISMATCH",
        ),
        ({"forge_additional_modules": None}, "SELECTION_MODULES_UNKNOWN"),
        ({"forge_additional_modules": [1, 2]}, "SELECTION_MODULES_UNKNOWN"),
        ({"sd_model_checkpoint": "sdxl_base.safetensors"}, "SELECTION_CHECKPOINT_MISMATCH"),
        ({"sd_model_checkpoint": ""}, "SELECTION_CHECKPOINT_UNKNOWN"),
        ({"sd_model_checkpoint": None}, "SELECTION_CHECKPOINT_UNKNOWN"),
    ],
)
def test_t05_any_other_selection_does_not_verify(overrides, code):
    findings = rq.verify_selection(read_back(**overrides), SERVED, resolve=identity)
    assert code in {f.code for f in findings}
    assert [f.code for f in rq.verify_selection(None, SERVED)] == ["OPTIONS_NOT_READ"]


# --- T06: infotext -------------------------------------------------------------------------------------------------------

INFOTEXT = (
    "A ceramic teapot on a wooden table beside a window, soft daylight, studio photograph.\n"
    "Steps: 9, Sampler: Euler, Schedule type: Beta, CFG scale: 1.0, Shift: 9.0, Seed: 424254, Size: 1024x1024, "
    "Model hash: 59610861d4, Model: zImageTurboQuantized_fp8ScaledE4m3fnKJ, Module 1: flux1AE_v10, "
    "Module 2: qwen3_4b_2964436, RNG: CPU, Version: neo"
)


def test_t06_the_effective_infotext_of_the_frozen_request_verifies():
    findings, facts = rq.verify_infotext(INFOTEXT)
    assert findings == []
    assert facts["parsed"] and facts["model_hash_reported"] and facts["modules_reported"] == 2


def test_t06_a_dropped_shift_is_visible_in_the_infotext_as_the_default_not_the_frozen_value():
    # The failure the reconciliation prevents: 'shift' ignored -> distilled_cfg_scale default 3.5 -> "Shift: 3.5".
    findings, _ = rq.verify_infotext(INFOTEXT.replace("Shift: 9.0", "Shift: 3.5"))
    assert [(f.code, f.severity) for f in findings] == [("INFOTEXT_FIELD_MISMATCH", "refuse")]


@pytest.mark.parametrize(
    "old,new,code",
    [
        ("Steps: 9", "Steps: 20", "INFOTEXT_FIELD_MISMATCH"),
        ("Sampler: Euler", "Sampler: DPM++ 2M", "INFOTEXT_FIELD_MISMATCH"),
        ("Schedule type: Beta", "Schedule type: Simple", "INFOTEXT_FIELD_MISMATCH"),
        ("CFG scale: 1.0", "CFG scale: 0.0", "INFOTEXT_FIELD_MISMATCH"),
        ("Seed: 424254", "Seed: 1", "INFOTEXT_FIELD_MISMATCH"),
        ("Size: 1024x1024", "Size: 512x512", "INFOTEXT_FIELD_MISMATCH"),
        ("Model hash: 59610861d4", "Model hash: deadbeef00", "INFOTEXT_MODEL_HASH_MISMATCH"),
        ("Module 1: flux1AE_v10, ", "Module 1: other_vae, ", "INFOTEXT_MODULES_MISMATCH"),
        ("Module 1: flux1AE_v10, ", "", "INFOTEXT_MODULES_MISMATCH"),
        (", Shift: 9.0", "", "INFOTEXT_FIELD_ABSENT"),
        ("Model hash: 59610861d4, ", "", "INFOTEXT_MODEL_HASH_ABSENT"),
    ],
)
def test_t06_each_effective_field_is_checked(old, new, code):
    assert old in INFOTEXT
    findings, _ = rq.verify_infotext(INFOTEXT.replace(old, new))
    assert code in {f.code for f in findings}


def test_t06_absent_infotext_is_inconclusive_and_quoted_values_parse():
    assert [f.code for f in rq.verify_infotext(None)[0]] == ["INFOTEXT_ABSENT"]
    assert [f.code for f in rq.verify_infotext("   ")[0]] == ["INFOTEXT_ABSENT"]
    pairs = rq.parse_infotext('Steps: 9, Model: "a, b", Seed: 1')
    assert pairs == {"Steps": "9", "Model": "a, b", "Seed": "1"}
    assert rq.modules_in_infotext({"Module 2": "b", "Module 10": "c", "Module 1": "a"}) == [
        "a",
        "b",
        "c",
    ]


# --- T07: report ---------------------------------------------------------------------------------------------------------


def test_t07_semantics_report_is_bounded_redacted_and_marks_verification_state():
    verified = rq.semantics_report([])
    assert verified["status"] == "reconciled_pinned_forge_source"
    assert verified["frozen_intent_values_changed"] is False
    text = json.dumps(verified)
    assert not re.search(r"(?i)[A-Z]:[\\/]", text) and "Users" not in text
    failing = rq.semantics_report(rq.verify_pinned_semantics(reader({})))
    assert failing["status"] == "NOT_VERIFIED" and failing["findings"]
    assert verified["payload_digest"] == rq.build_txt2img_payload().payload_digest
