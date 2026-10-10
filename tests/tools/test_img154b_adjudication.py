"""PR-IMG-MODELS-154B T17-T22: response validation, telemetry coverage and result classification (synthetic data only)."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154b import adjudication as adj

PROMPTLESS_INFOTEXT = (
    "A ceramic teapot on a wooden table beside a window, soft daylight, studio photograph.\n"
    "Steps: 9, Sampler: Euler, Schedule type: Beta, CFG scale: 1.0, Shift: 9.0, Seed: 424254, Size: 1024x1024, "
    "Model hash: 59610861d4, Module 1: flux1AE_v10, Module 2: qwen3_4b_2964436, RNG: CPU"
)


def png_b64(size=(1024, 1024), *, constant=False, mode="RGB") -> str:
    if constant:
        image = Image.new(mode, size, (90, 90, 90) if mode == "RGB" else 90)
    else:
        image = Image.linear_gradient("L").resize(size).convert(mode)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def response_body(**overrides):
    info = {
        "seed": 424254,
        "all_seeds": [424254],
        "infotexts": [PROMPTLESS_INFOTEXT],
    }
    body = {"images": [png_b64()], "info": json.dumps(info), "parameters": {}}
    body.update(overrides)
    return body


# --- T17: response validation --------------------------------------------------------------------------------------------


def test_t17_the_expected_single_image_validates_and_is_hashed():
    result = adj.validate_response(200, response_body())
    assert result.findings == ()
    facts = result.facts
    assert facts.valid and facts.identity_complete
    assert (
        facts.images_returned == 1
        and facts.dimensions == (1024, 1024)
        and facts.seed_returned == 424254
    )
    assert result.png is not None and len(result.png) == facts.bytes_len
    import hashlib

    assert facts.sha256 == hashlib.sha256(result.png).hexdigest()
    assert facts.as_dict()["valid"] is True


@pytest.mark.parametrize(
    "body,status,code",
    [
        (response_body(images=[]), 200, "RESPONSE_IMAGE_COUNT"),
        (response_body(images=[png_b64(), png_b64()]), 200, "RESPONSE_IMAGE_COUNT"),
        (response_body(images="nope"), 200, "RESPONSE_SHAPE"),
        (response_body(images=[""]), 200, "RESPONSE_IMAGE_ENCODING"),
        (response_body(images=[12]), 200, "RESPONSE_IMAGE_ENCODING"),
        (response_body(images=["!!!not base64!!!"]), 200, "IMAGE_NOT_DECODABLE"),
        (
            response_body(images=[base64.b64encode(b"GIF89a not a png").decode()]),
            200,
            "IMAGE_NOT_DECODABLE",
        ),
        (response_body(images=[png_b64((512, 512))]), 200, "IMAGE_DIMENSIONS"),
        (response_body(images=[png_b64(constant=True)]), 200, "IMAGE_TRIVIAL"),
        (None, 200, "RESPONSE_SHAPE"),
        (response_body(), 500, "RESPONSE_STATUS"),
        (response_body(), None, "RESPONSE_STATUS"),
    ],
)
def test_t17_every_deviation_from_exactly_one_valid_image_is_a_finding(body, status, code):
    result = adj.validate_response(status, body)
    assert code in {f.code for f in result.findings}
    assert result.facts.valid is False
    assert result.png is None or code in {"IMAGE_DIMENSIONS", "IMAGE_TRIVIAL"}


def test_t17_the_requested_seed_must_be_the_returned_seed_for_every_image():
    for info in (
        {"seed": 1, "all_seeds": [1], "infotexts": [PROMPTLESS_INFOTEXT]},
        {"seed": 424254, "all_seeds": [424254, 424255], "infotexts": [PROMPTLESS_INFOTEXT]},
        {"seed": 424254, "infotexts": [PROMPTLESS_INFOTEXT]},  # all_seeds absent: not confirmed
        {"seed": True, "all_seeds": [True], "infotexts": [PROMPTLESS_INFOTEXT]},
    ):
        result = adj.validate_response(200, response_body(info=json.dumps(info)))
        assert "SEED_NOT_CONFIRMED" in {f.code for f in result.findings}, info
        assert not result.facts.valid


def test_t17_the_infotext_is_the_effective_parameter_record():
    dropped_shift = PROMPTLESS_INFOTEXT.replace("Shift: 9.0", "Shift: 3.5")
    info = {"seed": 424254, "all_seeds": [424254], "infotexts": [dropped_shift]}
    result = adj.validate_response(200, response_body(info=json.dumps(info)))
    assert "INFOTEXT_FIELD_MISMATCH" in {f.code for f in result.findings}
    assert result.facts.infotext_ok is False and not result.facts.valid
    no_text = {"seed": 424254, "all_seeds": [424254]}
    result = adj.validate_response(200, response_body(info=json.dumps(no_text)))
    assert (
        result.facts.infotext_ok is None
        and not result.facts.valid
        and not result.facts.identity_complete
    )


def test_t17_info_may_arrive_as_an_object_and_malformed_info_is_not_a_pass():
    info = {"seed": 424254, "all_seeds": [424254], "infotexts": [PROMPTLESS_INFOTEXT]}
    assert adj.validate_response(200, response_body(info=info)).facts.valid
    assert not adj.validate_response(200, response_body(info="{not json")).facts.valid
    assert not adj.validate_response(200, response_body(info="[1,2]")).facts.valid


def test_t17_a_non_default_manifest_is_judged_against_its_own_intent():
    plan = mf.QualificationManifest(intent=replace(mf.FrozenIntent(), width=512, height=512))
    body = response_body(images=[png_b64((512, 512))])
    result = adj.validate_response(200, body, plan)
    assert (
        result.facts.dimensions_ok
    )  # sized as the manifest intends; the infotext still names 1024x1024
    assert "INFOTEXT_FIELD_MISMATCH" in {f.code for f in result.findings}


# --- T18: telemetry coverage ---------------------------------------------------------------------------------------------


def sample_record(seq, mono, **status):
    fields = dict.fromkeys(adj.REQUIRED_SAMPLE_FIELDS, "ok")
    fields.update(status)
    return {
        "kind": "sample",
        "sample_seq": seq,
        "seq": seq,
        "mono_s": mono,
        "utc": "2026-01-01T00:00:00+00:00",
        "status": fields,
    }


def stream(count=20, **status):
    return [sample_record(i, 100.0 + i, **status) for i in range(1, count + 1)]


def test_t18_a_dense_complete_stream_is_complete():
    coverage = adj.evaluate_telemetry_coverage(stream())
    assert coverage.complete and coverage.reasons == () and coverage.max_gap_s == 1.0
    assert all(fraction == 1.0 for fraction in coverage.fractions.values())


@pytest.mark.parametrize(
    "records,reason",
    [
        (stream(count=3), "too_few_samples"),
        (stream(shared_vram_bytes="missing"), "field_coverage_below_threshold"),
        (stream(forge_tree_private_bytes="error"), "field_coverage_below_threshold"),
        ([r for r in stream() if r["sample_seq"] != 10], "sequence_gap_or_disorder"),
        (list(reversed(stream())), "sequence_gap_or_disorder"),
        (
            [sample_record(i, 100.0 + (i if i < 10 else i + 5)) for i in range(1, 21)],
            "sampling_gap",
        ),
        ([sample_record(i, 100.0 - i) for i in range(1, 21)], "clock_not_monotonic"),
        ([{**r, "mono_s": None} for r in stream()], "clock_invalid"),
        ([{**r, "sample_seq": "x"} for r in stream()], "sequence_invalid"),
        ([], "too_few_samples"),
    ],
)
def test_t18_gaps_unknowns_disorder_and_a_thin_stream_are_incomplete(records, reason):
    coverage = adj.evaluate_telemetry_coverage(records)
    assert not coverage.complete and reason in coverage.reasons


def test_t18_a_rare_missing_reading_below_the_tolerance_is_allowed_but_recorded():
    records = stream(40)
    records[7]["status"]["shared_vram_bytes"] = "missing"  # 39/40 = 97.5%
    coverage = adj.evaluate_telemetry_coverage(records)
    assert coverage.complete and coverage.fractions["shared_vram_bytes"] == pytest.approx(0.975)


def test_t18_non_sample_records_are_ignored():
    mixed = [{"kind": "transition"}, *stream(), {"kind": "header"}]
    assert adj.evaluate_telemetry_coverage(mixed).complete


# --- T19: classification -------------------------------------------------------------------------------------------------


def pass_facts(**overrides) -> adj.CaseFacts:
    base = adj.CaseFacts(
        authority=adj.AUTHORITY_PHYSICAL,
        preflight_prepared=True,
        claimed=True,
        startup_observed=True,
        selection_confirmed=True,
        dispatched=True,
        response_received=True,
        shutdown=adj.SHUTDOWN_VERIFIED,
        unexplained_survivors=False,
        telemetry_complete=True,
        fault_status=ev.NO_NEW_EVENTS_COMPLETE_COVERAGE,
        output_valid=True,
        identity_complete=True,
        ledger_terminal_recorded=True,
        evidence_complete=True,
    )
    return replace(base, **overrides)


def test_t19_a_pass_needs_every_piece_of_evidence_and_is_only_a_constrained_statement():
    result = adj.classify_case(pass_facts())
    assert result.result_class == ev.TECHNICAL_PASS_CONSTRAINED and result.is_pass
    assert "does not establish general stability" in result.statement
    assert result.also == () and result.reasons == ()


def test_t19_the_default_facts_are_never_a_pass():
    assert adj.classify_case(adj.CaseFacts()).result_class == ev.PREFLIGHT_REFUSED
    assert not adj.classify_case(adj.CaseFacts()).is_pass


def test_t19_a_synthetic_authority_can_never_award_a_pass():
    result = adj.classify_case(pass_facts(authority=adj.AUTHORITY_SYNTHETIC))
    assert result.result_class == ev.INSTRUMENTATION_GAP and not result.is_pass
    assert "authority_not_physical_owner_authorized" in result.reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("claimed", False),
        ("startup_observed", False),
        ("selection_confirmed", False),
        ("identity_complete", False),
        ("ledger_terminal_recorded", False),
        ("evidence_complete", False),
        ("shutdown", adj.SHUTDOWN_UNVERIFIED),
        ("shutdown", adj.SHUTDOWN_TIMED_OUT),
        ("shutdown", adj.SHUTDOWN_NOT_ATTEMPTED),
        ("unexplained_survivors", None),
        ("unexplained_survivors", True),
        ("fault_status", ev.UNKNOWN_COVERAGE_GAP),
        ("telemetry_complete", False),
        ("output_valid", None),
        ("monitor_latched", "CANNOT_VERIFY_SAFE_STATE"),
        ("monitor_latched", "HARNESS_FAULT"),
    ],
)
def test_t19_a_single_missing_requirement_downgrades_the_pass(field, value):
    result = adj.classify_case(pass_facts(**{field: value}))
    assert not result.is_pass
    assert result.result_class != ev.TECHNICAL_PASS_CONSTRAINED


def test_t19_failure_classes_follow_the_154a_precedence_and_name_every_cause():
    cases = {
        "refused": (adj.CaseFacts(), ev.PREFLIGHT_REFUSED),
        "fault": (pass_facts(fault_status=ev.NEW_EVENTS), ev.SYSTEM_OR_GPU_FAULT),
        "boot": (pass_facts(fault_status=ev.BOOT_CHANGED), ev.SYSTEM_OR_GPU_FAULT),
        "fault_event_in_stream": (
            pass_facts(
                monitor_codes=("GPU_FAULT_EVENT:whea",), monitor_latched="CANNOT_VERIFY_SAFE_STATE"
            ),
            ev.SYSTEM_OR_GPU_FAULT,
        ),
        "device_lost": (
            pass_facts(
                monitor_codes=("GPU_DEVICE_LOST",), monitor_latched="CANNOT_VERIFY_SAFE_STATE"
            ),
            ev.SYSTEM_OR_GPU_FAULT,
        ),
        "ambiguous": (
            pass_facts(response_received=False, output_valid=None),
            ev.AMBIGUOUS_DISPATCH,
        ),
        "stop": (
            pass_facts(
                monitor_latched="REQUEST_OWNER_STOP", dispatched=False, response_received=False
            ),
            ev.RESOURCE_ABORT_REQUESTED,
        ),
        "loader": (
            pass_facts(
                loader_failed=True,
                dispatched=False,
                response_received=False,
                selection_confirmed=False,
            ),
            ev.LOADER_FAILED,
        ),
        "output": (pass_facts(output_valid=False), ev.OUTPUT_VALIDATION_FAIL),
        "gap": (pass_facts(telemetry_complete=False), ev.INSTRUMENTATION_GAP),
    }
    for name, (facts, expected) in cases.items():
        assert adj.classify_case(facts).result_class == expected, name
    # several causes: the precedence order decides the primary and the rest are reported
    both = adj.classify_case(pass_facts(fault_status=ev.NEW_EVENTS, output_valid=False))
    assert both.result_class == ev.SYSTEM_OR_GPU_FAULT and ev.OUTPUT_VALIDATION_FAIL in both.also


def test_t19_a_dispatched_case_without_a_response_is_ambiguous_even_if_nothing_else_is_known():
    result = adj.classify_case(
        adj.CaseFacts(preflight_prepared=True, claimed=True, dispatched=True)
    )
    assert result.result_class == ev.AMBIGUOUS_DISPATCH
    assert ev.INSTRUMENTATION_GAP in result.also


def test_t19_the_result_vocabulary_is_the_eight_documented_classes():
    assert set(ev.RESULT_CLASSES) == {
        "PREFLIGHT_REFUSED",
        "LOADER_FAILED",
        "RESOURCE_ABORT_REQUESTED",
        "AMBIGUOUS_DISPATCH",
        "SYSTEM_OR_GPU_FAULT",
        "INSTRUMENTATION_GAP",
        "OUTPUT_VALIDATION_FAIL",
        "TECHNICAL_PASS_CONSTRAINED",
    }
    for facts in (adj.CaseFacts(), pass_facts(), pass_facts(output_valid=False)):
        assert adj.classify_case(facts).result_class in ev.RESULT_CLASSES


def test_t18_not_applicable_samples_are_excluded_but_a_never_applicable_field_has_no_coverage():
    records = stream(40)
    for record in records[:10]:  # before the owned process existed
        record["status"]["forge_tree_private_bytes"] = "not_applicable"
    coverage = adj.evaluate_telemetry_coverage(records)
    assert coverage.complete and coverage.fractions["forge_tree_private_bytes"] == 1.0
    never = stream(40)
    for record in never:
        record["status"]["forge_tree_private_bytes"] = "not_applicable"
    result = adj.evaluate_telemetry_coverage(never)
    assert not result.complete and "forge_tree_private_bytes" in result.missing_fields
