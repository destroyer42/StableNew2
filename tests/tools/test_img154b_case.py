"""PR-IMG-MODELS-154B T49-T78: the one-case coordinator against fakes (no process, network, GPU or model is touched).

Every port is a fake. The synthetic authority proceeds through the whole flow but can never be classified as a pass; the
physical authority used by two tests is minted only to exercise the classification and is not a qualification result.
"""

from __future__ import annotations

import base64
import io
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154 import preflight as pf
from tools.qualification.img154.core import GIB, Finding, Observation
from tools.qualification.img154b import adjudication as adj
from tools.qualification.img154b import authorization as au
from tools.qualification.img154b import case as cs
from tools.qualification.img154b import fence as fn
from tools.qualification.img154b import request as rq
from tools.qualification.img154b import runtime as rt
from tools.qualification.img154b import sampler as sp
from tools.qualification.img154b.bundle import EvidenceBundle

UTC_NOW = "2026-01-01T12:00:00+00:00"
BOOT = "2026-01-01T00:00:00+00:00"
DEVICE = "device-digest-1"
CODE = au.CodeRevision("clean", "a" * 40, "b" * 64)
PROMPT = "A ceramic teapot on a wooden table beside a window, soft daylight, studio photograph."
SERVED = {
    "transformer": "C:/qual/forge-data/models/Stable-diffusion/zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors",
    "text_encoder": "C:/qual/forge-data/models/text_encoder/qwen3_4b_2964436.safetensors",
    "vae": "C:/qual/forge-data/models/VAE/flux1AE_v10.safetensors",
}
INFOTEXT = (
    f"{PROMPT}\n"
    "Steps: 9, Sampler: Euler, Schedule type: Beta, CFG scale: 1.0, Shift: 9.0, Seed: 424254, Size: 1024x1024, "
    "Model hash: 59610861d4, Module 1: flux1AE_v10, Module 2: qwen3_4b_2964436, RNG: CPU"
)


def png_b64() -> str:
    image = Image.linear_gradient("L").resize((1024, 1024)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


PNG = png_b64()

PASSPHRASE = "a long owner passphrase"
PASSPHRASE_SALT = "0123456789abcdef0123456789abcdef"
PASSPHRASE_ITERATIONS = 100_000
PASSPHRASE_VERIFIER = au.derive_verifier(PASSPHRASE, PASSPHRASE_SALT, PASSPHRASE_ITERATIONS)


# --- fakes ---------------------------------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 5000.0

    def mono(self):
        return self.now

    def utc(self):
        return UTC_NOW

    def sleep(self, seconds):
        self.now += seconds

    def port(self) -> cs.ClockPort:
        return cs.ClockPort(self.mono, self.utc, self.sleep)


class Events(list):
    def add(self, *item):
        self.append(item)

    def names(self):
        return [item[0] for item in self]

    def index_of(self, name):
        return self.names().index(name)


def obs(clock, name, value, units="bytes", status="ok"):
    return Observation(name, value, units, "fake", clock.mono(), UTC_NOW, status)


def baseline_window(clock, **kw):
    end = clock.mono() - 5.0
    samples = tuple(pf.BaselineSample(end - (24 - i), 2.2 * GIB, 0.3 * GIB, 2.0) for i in range(25))
    values = {
        "samples": samples,
        "device_id": DEVICE,
        "boot_id": BOOT,
        "acquired_by": pf.BASELINE_PROVIDER,
        "competing_runtime_free": True,
    }
    values.update(kw)
    return pf.QuiescentBaselineEvidence(**values)


def complete_faults(taken=UTC_NOW, boot=BOOT, ids=("100", "101")):
    sources = {
        name: ev.FaultSourceSnapshot(name, "complete", frozenset(ids)) for name in ev.FAULT_SOURCES
    }
    return ev.FaultSnapshot(taken, boot, sources)


class FakeCollector:
    def __init__(self, clock, events, *, headroom=40 * GIB, code=CODE, **inputs_overrides):
        self.clock, self.events = clock, events
        self.headroom = headroom
        self.code = code
        self.overrides = inputs_overrides
        self.remeasure_headroom = None
        self.served_findings = []
        self.device_after = DEVICE
        self.workspace = "none"
        self.runtime_sections = {"processes": [], "endpoint": []}

    def _observations(self, headroom):
        c = self.clock
        return {
            "commit_headroom_bytes": obs(c, "commit_headroom_bytes", headroom),
            "commit_limit_bytes": obs(c, "commit_limit_bytes", 49.8 * GIB),
            "ram_available_bytes": obs(c, "ram_available_bytes", 25 * GIB),
            "pagefile_volume_free_bytes": obs(c, "pagefile_volume_free_bytes", 100 * GIB),
            "vram_used_bytes": obs(c, "vram_used_bytes", 2.3 * GIB),
            "vram_total_bytes": obs(c, "vram_total_bytes", 12 * GIB),
            "evidence_volume_free_bytes": obs(c, "evidence_volume_free_bytes", 50 * GIB),
        }

    def collect(self):
        self.events.add("collect")
        inputs = pf.PreflightInputs(
            manifest_digest=mf.build_manifest().digest(),
            sections={key: [] for key in pf.SECTION_REASON},
            observations=self._observations(self.headroom),
            telemetry_coverage=dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available"),
            fault_baseline_coverage=dict.fromkeys(ev.FAULT_SOURCES, "complete"),
            evidence_dir_valid=True,
            quiescent_baseline=baseline_window(self.clock),
            launch_device_id=DEVICE,
            launch_boot_id=BOOT,
        )
        inputs = replace(inputs, **self.overrides)
        return cs.Collected(
            inputs=inputs,
            code=self.code,
            fault_before=complete_faults(),
            boot_id=BOOT,
            device_id=DEVICE,
            workspace_ledger_state=self.workspace,
            facts={"python": "3.x", "platform": "test", "timezone_utc_offset_minutes": 0},
        )

    def remeasure(self):
        self.events.add("remeasure")
        headroom = self.remeasure_headroom if self.remeasure_headroom is not None else self.headroom
        fresh = self._observations(headroom)
        fresh["gpu_device_id"] = Observation(
            "gpu_device_id", self.device_after, "id", "fake", self.clock.mono(), UTC_NOW, "ok"
        )
        result = cs.Remeasured(fresh, baseline_window(self.clock), complete_faults())
        result.sections = self.runtime_sections
        result.runtime_observed_mono_s = self.clock.mono()
        return result

    def recheck_runtime(self):
        self.events.add("recheck_runtime")
        return self.clock.mono(), self.runtime_sections

    def recheck_code(self):
        self.events.add("recheck_code")
        return self.code

    def recheck_served(self):
        self.events.add("recheck_served")
        return list(self.served_findings)


class FakeRuntime:
    """``listening`` becomes true only when the endpoint first answers (Forge binds its port tens of seconds after start)."""

    def __init__(
        self, events, *, owned=True, start_raises=None, shutdown=None, foreign_listener=False
    ):
        self.events = events
        self.owned = owned
        self.start_raises = start_raises
        self.shutdown = shutdown or rt.ShutdownResult(True, True, False, True, (), "ok")
        self.foreign_listener = foreign_listener
        self.listening = False
        self.stops = 0
        self.foreign_after_ready = False
        self.ownership_calls: list[bool] = []

    def start(self):
        self.events.add("runtime.start")
        if self.start_raises:
            raise self.start_raises
        return {"pid": 4242, "owns_process": self.owned}

    def verify_ownership(self, *, require_listener=True):
        self.events.add("verify_ownership")
        self.ownership_calls.append(require_listener)
        problems = []
        if not self.owned:
            problems.append("manager does not report launch-session ownership")
        foreign = self.foreign_listener or (self.foreign_after_ready and self.listening)
        listeners = (9999,) if foreign else ((4243,) if self.listening else ())
        if foreign:
            problems.append("a process outside the owned tree listens on the qualification port")
        elif not listeners and require_listener:
            problems.append("nothing listens on the qualification port")
        in_tree = bool(listeners) and not foreign
        return rt.OwnershipFacts(
            not problems, 4242, (4242, 4243), listeners, in_tree, True, tuple(problems)
        )

    def stop(self):
        self.events.add("runtime.stop")
        self.stops += 1
        return self.shutdown

    def output_tail(self):
        return {"stdout_tail": "ok", "stderr_tail": "", "pid": 4242, "running": False}


class FakeHttp:
    def __init__(
        self,
        events,
        clock,
        *,
        options=None,
        generation=None,
        drop_module=False,
        never_ready=False,
        boot_failures=2,
    ):
        self.events, self.clock = events, clock
        self.boot_failures = (
            boot_failures  # connection-refused answers while the endpoint is still binding
        )
        self.on_ready = None
        self.options = dict(rq.EXPECTED_SAMPLING_OPTIONS)
        self.options.update(hide_schedulers=[], sd_model_checkpoint="", forge_additional_modules=[])
        self.options.update(options or {})
        self.generation = generation
        self.drop_module = drop_module
        self.never_ready = never_ready
        self.requests: list[tuple[str, str, bytes | None]] = []
        self.on_generation = None
        self.progress = {"state": {"sampling_steps": 9, "sampling_step": 3, "job_count": 1}}

    def get_json(self, path, *, timeout_s=10.0):
        self.requests.append(("GET", path, None))
        self.events.add("http.get", path)
        if path.startswith("/sdapi/v1/progress"):
            return cs.HttpResult(200, self.progress)
        if self.never_ready or self.boot_failures > 0:
            self.boot_failures -= 1 if not self.never_ready else 0
            return cs.HttpResult(None, None, "connection refused")
        if self.on_ready is not None:
            self.on_ready()
        return cs.HttpResult(200, dict(self.options))

    def post_json(self, path, body, *, timeout_s):
        self.requests.append(("POST", path, body))
        self.events.add("http.post", path)
        if path == "/sdapi/v1/options":
            data = json.loads(body)
            modules = list(data["forge_additional_modules"])
            if self.drop_module:
                modules = modules[:1]
            self.options["sd_model_checkpoint"] = data["sd_model_checkpoint"]
            self.options["forge_additional_modules"] = modules
            return cs.HttpResult(200, {})
        if path == "/sdapi/v1/txt2img":
            if self.on_generation is not None:
                return self.on_generation(self)
            return self.generation or cs.HttpResult(200, good_body())
        return cs.HttpResult(404)

    def generation_posts(self):
        return [r for r in self.requests if r[0] == "POST" and r[1] == "/sdapi/v1/txt2img"]


def good_body(infotext=INFOTEXT, seed=424254, images=None):
    info = {"seed": seed, "all_seeds": [seed], "infotexts": [infotext]}
    return {"images": images if images is not None else [PNG], "info": json.dumps(info)}


class FakeSampler:
    """A SamplerPort whose stream and halts are scripted; it writes real sample records through the coordinator's writer."""

    def __init__(
        self,
        monitor,
        writer,
        stage,
        endpoint,
        *,
        samples=20,
        status_overrides=None,
        script=None,
        unhealthy=False,
    ):
        self.unhealthy = unhealthy
        self.writer = writer
        self.halt_event = threading.Event()
        self.halt = None
        self.harness_fault = None
        self.provenance = {}
        self.samples, self.status_overrides, self.script = samples, status_overrides or {}, script
        self.ticks = 0
        self.stopped = False
        self.stage = stage

    def write_header(self, **facts):
        self.writer.append({"kind": "header", **facts})

    def start(self):
        for index in range(1, self.samples + 1):
            status = dict.fromkeys(adj.REQUIRED_SAMPLE_FIELDS, "ok")
            status.update(self.status_overrides)
            self.writer.append(
                {
                    "kind": "sample",
                    "sample_seq": index,
                    "mono_s": 100.0 + index,
                    "utc": UTC_NOW,
                    "status": status,
                    "monitor": {"action": "NONE", "codes": [], "latched": "NONE"},
                }
            )

    @property
    def sample_count(self):
        return self.ticks

    @property
    def clean_streak(self):
        return 0 if self.unhealthy else self.ticks

    def watchdog_tick(self):
        self.ticks += 1
        if self.script is not None:
            self.script(self)

    def stop(self, timeout_s=5.0):
        self.stopped = True

    def fire(self, action, *codes):
        self.halt = sp.HaltRecord(
            action,
            tuple(codes),
            codes[0] if codes else None,
            99,
            1.0,
            UTC_NOW,
            {"vram_used_bytes": 1},
        )
        self.halt_event.set()


class Harness:
    """Wires the coordinator with fakes. ``run()`` returns the report; ``events`` is the ordered action log."""

    def __init__(self, tmp_path, *, authority=None, authorization="valid", **options):
        self.tmp = tmp_path
        self.clock = FakeClock()
        self.events = Events()
        self.manifest = mf.build_manifest()
        self.payload = rq.build_txt2img_payload(self.manifest)
        self.collector = options.pop("collector", None) or FakeCollector(self.clock, self.events)
        self.runtime = options.pop("runtime", None) or FakeRuntime(self.events)
        self.http = options.pop("http", None) or FakeHttp(self.events, self.clock)
        # the endpoint binds only after the manager returned: the runtime starts listening when the endpoint first answers
        self.http.on_ready = lambda: setattr(self.runtime, "listening", True)
        self.secret = options.pop("secret", PASSPHRASE)
        self.sampler_kwargs = options.pop("sampler", {})
        self.fault_after = options.pop("fault_after", "same")
        self.typed = options.pop("typed", None)
        self.config = options.pop("config", cs.CaseConfig(settle_s=120.0, ready_timeout_s=30.0))
        self.record_root = tmp_path / "records"
        self.fence = options.pop("fence", None) or fn.CaseFence(
            self.manifest, self.record_root, sync=lambda fd: None
        )
        self.authority = authority or cs.ExecutionAuthority.synthetic()
        self.authorization = self._authorization() if authorization == "valid" else authorization
        self.samplers: list[FakeSampler] = []
        self.bundle_dir = tmp_path / "bundle"
        assert not options, options

    def use_http(self, http):
        self.http = http
        self.http.on_ready = lambda: setattr(self.runtime, "listening", True)
        return http

    def _authorization(self, **overrides):
        base = {
            "schema": au.AUTHORIZATION_SCHEMA,
            "attempt_identity": self.manifest.attempt_identity(),
            "manifest_digest": self.manifest.digest(),
            "payload_digest": self.payload.payload_digest,
            "semantics_revision": rq.SEMANTICS_REVISION,
            "policy_revision": self.manifest.policy_revision,
            "evidence_contract_revision": self.manifest.evidence_contract_revision,
            "git_sha": CODE.sha,
            "source_sha256": CODE.source_sha256,
            "accepted_risks": [au.RISK_ID],
            "cases": 1,
            "retries": 0,
            "authorized_by": "owner",
            "authorized_utc": "2026-01-01T11:00:00+00:00",
            "expires_utc": "2026-01-01T23:00:00+00:00",
            "statement": au.REQUIRED_STATEMENT,
            "challenge": au.authorization_challenge(self.manifest, self.payload, CODE),
            "passphrase_salt": PASSPHRASE_SALT,
            "passphrase_verifier": PASSPHRASE_VERIFIER,
            "passphrase_iterations": PASSPHRASE_ITERATIONS,
        }
        base.update(overrides)
        return au.parse_authorization(base)

    def make_sampler(self, monitor, writer, stage, endpoint):
        sampler = FakeSampler(monitor, writer, stage, endpoint, **self.sampler_kwargs)
        self.samplers.append(sampler)
        return sampler

    def faults(self):
        self.events.add("faults.after")
        if self.fault_after == "same":
            return complete_faults(taken="2026-01-01T12:05:00+00:00")
        return self.fault_after() if callable(self.fault_after) else self.fault_after

    def confirm(self, summary):
        self.events.add("confirm")
        return self.typed if self.typed is not None else summary["expected_phrase"]

    def coordinator(self):
        ports = cs.CasePorts(
            collector=self.collector,
            fence=self.fence,
            runtime=self.runtime,
            http=self.http,
            sampler_factory=self.make_sampler,
            faults=self.faults,
            confirm=self.confirm,
            passphrase=lambda: self.secret,
            clock=self.clock.port(),
            bundle=EvidenceBundle(self.bundle_dir, sync=lambda fd: None),
            sample_path=self.tmp / "samples.jsonl",
            served_paths=SERVED,
        )
        ports.authorization_current = lambda approved: approved == self.authorization
        return cs.CaseCoordinator(
            ports, manifest=self.manifest, payload=self.payload, config=self.config
        )

    def run(self):
        return self.coordinator().run(self.authority, self.authorization)


def physical() -> cs.ExecutionAuthority:
    return cs.mint_physical_authority("f" * 64)


# --- T49: the whole flow with the synthetic authority --------------------------------------------------------------------


def test_t49_the_complete_flow_runs_in_the_documented_order_and_is_never_a_pass_under_a_synthetic_authority(
    tmp_path,
):
    h = Harness(tmp_path)
    report = h.run()
    names = h.events.names()
    assert report.result.result_class == ev.INSTRUMENTATION_GAP
    assert "authority_not_physical_owner_authorized" in report.result.reasons
    assert not report.result.is_pass
    assert report.claimed and report.executed
    assert report.stages == ev.LEDGER_STAGES
    # actions follow their durable records and one another
    assert (
        names.index("collect")
        < names.index("confirm")
        < names.index("remeasure")
        < names.index("runtime.start")
    )
    assert names.index("runtime.start") < names.index("runtime.stop") < names.index("faults.after")
    posts = [item for item in h.events if item[0] == "http.post"]
    assert [p[1] for p in posts] == ["/sdapi/v1/options", "/sdapi/v1/txt2img"]
    assert len(h.http.generation_posts()) == 1
    assert h.runtime.stops == 1
    assert h.fence.state().status == "terminal"


def test_t49_request_bodies_are_exactly_the_frozen_payload_and_the_selection_payload(tmp_path):
    h = Harness(tmp_path)
    h.run()
    options_post = next(
        r for r in h.http.requests if r[0] == "POST" and r[1] == "/sdapi/v1/options"
    )
    assert json.loads(options_post[2]) == rq.selection_payload(SERVED)
    generation = h.http.generation_posts()[0]
    assert generation[2] == h.payload.wire_bytes
    assert json.loads(generation[2])["distilled_cfg_scale"] == 9.0
    assert all(r[0] in ("GET", "POST") for r in h.http.requests)
    assert {r[1].split("?")[0] for r in h.http.requests} <= {
        "/sdapi/v1/options",
        "/sdapi/v1/txt2img",
        "/sdapi/v1/progress",
    }


def test_t49_a_fully_evidenced_physical_authority_run_is_the_only_pass_shape(tmp_path):
    h = Harness(tmp_path, authority=physical())
    report = h.run()
    assert report.result.result_class == ev.TECHNICAL_PASS_CONSTRAINED, report.result.reasons
    assert "does not establish general stability" in report.result.statement
    assert report.shutdown["outcome"] == "verified_clean"
    assert report.output["valid"] and report.faults["clean_claim_allowed"]


def test_t49_denoise_is_attributed_from_the_progress_signal_and_nothing_else_is_invented(tmp_path):
    h = Harness(tmp_path)
    slow = threading.Event()

    def generation(http):
        slow.wait(0.4)
        return cs.HttpResult(200, good_body())

    h.http.on_generation = generation
    h.config = replace(h.config, supervision_interval_s=0.05)
    report = h.run()
    index = json.loads((h.bundle_dir / "raw" / "phases.json").read_text())
    stages = [(p["stage"], p["source"]) for p in index]
    assert ("denoise", "forge_api") in stages
    assert all(
        stage not in ("encoder_load", "transformer_load", "vae_decode") for stage, _ in stages
    )
    assert report.executed


# --- T50: refusals before the claim --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "tamper_manifest",
        "tamper_payload",
        "wrong_case",
        "wrong_code",
        "risk_missing",
        "scope",
        "statement",
        "challenge",
        "expired",
        "not_yet_valid",
        "too_long",
    ],
)
def test_t50_without_exact_case_authorization_nothing_is_claimed_started_or_sent(
    tmp_path, authorization
):
    h = Harness(tmp_path, authorization=None)
    overrides = {
        "tamper_manifest": {"manifest_digest": "0" * 64},
        "tamper_payload": {"payload_digest": "1" * 64},
        "wrong_case": {"attempt_identity": "2" * 64},
        "wrong_code": {"git_sha": "c" * 40},
        "risk_missing": {"accepted_risks": []},
        "scope": {"cases": 2},
        "statement": {"statement": "yes"},
        "challenge": {"challenge": "3" * 64},
        "expired": {"expires_utc": "2026-01-01T11:30:00+00:00"},
        "not_yet_valid": {
            "authorized_utc": "2026-01-01T13:00:00+00:00",
            "expires_utc": "2026-01-01T14:00:00+00:00",
        },
        "too_long": {"expires_utc": "2026-01-03T00:00:00+00:00"},
    }
    if authorization is not None:
        h.authorization = h._authorization(**overrides[authorization])
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert not report.claimed and not report.executed
    assert h.fence.state().status == "none"  # a refusal consumes nothing
    assert "runtime.start" not in h.events.names() and not h.http.requests
    assert "confirm" not in h.events.names()
    assert report.refusals


def test_t50_a_dirty_or_unidentified_checkout_is_never_trusted(tmp_path):
    for code in (
        au.CodeRevision("dirty", "a" * 40, "b" * 64),
        au.CodeRevision("unverifiable", None, None),
    ):
        h = Harness(tmp_path / code.state, authorization="valid")
        h.collector = FakeCollector(h.clock, h.events, code=code)
        report = h.run()
        assert report.result.result_class == ev.PREFLIGHT_REFUSED
        assert any(
            r.startswith("CODE_REVISION") or r.startswith("AUTHORIZATION") for r in report.refusals
        )
        assert "runtime.start" not in h.events.names()


@pytest.mark.parametrize(
    "overrides,reason",
    [
        (
            {
                "sections": {
                    **{k: [] for k in pf.SECTION_REASON},
                    "processes": [mf.Finding("RUNTIME_CONFLICT_FOREIGN_OWNER", "refuse", "x")],
                }
            },
            "REFUSED_RUNTIME_CONFLICT",
        ),
        (
            {
                "sections": {
                    **{k: [] for k in pf.SECTION_REASON},
                    "served": [mf.Finding("ASSET_SHA256_MISMATCH", "refuse", "x")],
                }
            },
            "REFUSED_ASSET_IDENTITY",
        ),
        (
            {
                "sections": {
                    **{k: [] for k in pf.SECTION_REASON},
                    "endpoint": [mf.Finding("RUNTIME_PORT_OCCUPIED", "refuse", "x")],
                }
            },
            "REFUSED_RUNTIME_CONFLICT",
        ),
        ({"quiescent_baseline": None}, "INCONCLUSIVE"),
        ({"launch_device_id": "another-gpu"}, "REFUSED_RESOURCE_THRESHOLD"),
        ({"evidence_dir_valid": False}, "REFUSED_EVIDENCE_PATH"),
        (
            {
                "telemetry_coverage": {
                    **dict.fromkeys(pf.ESSENTIAL_TELEMETRY, "available"),
                    "gpu_temperature_c": "unavailable",
                }
            },
            "INCONCLUSIVE",
        ),
    ],
)
def test_t50_every_preflight_refusal_stops_before_the_claim(tmp_path, overrides, reason):
    h = Harness(tmp_path)
    h.collector = FakeCollector(h.clock, h.events, **overrides)
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert reason in report.refusals
    assert not report.claimed and h.fence.state().status == "none"
    assert "runtime.start" not in h.events.names() and not h.http.requests


def test_t50_unmet_thresholds_are_refused_not_relaxed(tmp_path):
    h = Harness(tmp_path)
    h.collector = FakeCollector(h.clock, h.events, headroom=36.9 * GIB)
    report = h.run()
    assert "COMMIT_HEADROOM_BELOW_THRESHOLD" in report.refusals
    assert report.result.result_class == ev.PREFLIGHT_REFUSED and not report.claimed


def test_t51_the_operator_must_type_the_exact_case_phrase(tmp_path):
    for typed in ("", "yes", "RUN-ONE-PHYSICAL-CASE", "run-one-physical-case"):
        h = Harness(tmp_path / (typed or "empty"), typed=typed)
        report = h.run()
        assert report.result.result_class == ev.PREFLIGHT_REFUSED
        assert "OPERATOR_CONFIRMATION_MISMATCH" in report.refusals
        assert not report.claimed and "runtime.start" not in h.events.names()
    phrase = au.confirmation_phrase(mf.build_manifest(), rq.build_txt2img_payload())
    assert phrase.startswith("RUN-ONE-PHYSICAL-CASE ") and len(phrase.split()) == 4


def test_t52_a_resource_drop_between_confirmation_and_start_is_caught_by_the_fresh_measurement(
    tmp_path,
):
    h = Harness(tmp_path)
    h.collector.remeasure_headroom = 30 * GIB  # fell after the first assessment
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert (
        "FINAL_REMEASURE_REFUSED" in report.refusals
        and "COMMIT_HEADROOM_BELOW_THRESHOLD" in report.refusals
    )
    assert not report.claimed and "runtime.start" not in h.events.names()


def test_t52_a_changed_gpu_or_an_unchecked_device_identity_is_refused(tmp_path):
    h = Harness(tmp_path)
    h.collector.device_after = "a-different-gpu"
    assert "DEVICE_IDENTITY_NOT_REVERIFIED" in h.run().refusals

    h2 = Harness(tmp_path / "two")
    original = h2.collector.remeasure

    def without_identity():
        fresh = original()
        fresh.observations.pop("gpu_device_id")
        return fresh

    h2.collector.remeasure = without_identity
    assert "DEVICE_IDENTITY_NOT_REVERIFIED" in h2.run().refusals


def test_t52_a_served_file_that_changes_after_the_proof_is_refused_before_the_claim(tmp_path):
    h = Harness(tmp_path)
    h.collector.served_findings = [mf.Finding("SERVED_FILE_CHANGED_AFTER_PROOF", "refuse", "vae")]
    report = h.run()
    assert not report.claimed and "SERVED_FILE_CHANGED_AFTER_PROOF" in report.refusals


# --- T53: the claim and no replay ----------------------------------------------------------------------------------------


def test_t53_a_consumed_case_is_never_run_again_by_any_coordinator(tmp_path):
    first = Harness(tmp_path)
    first.run()
    second = Harness(
        tmp_path, fence=fn.CaseFence(mf.build_manifest(), first.record_root, sync=lambda fd: None)
    )
    second.bundle_dir = tmp_path / "bundle-2"
    report = second.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert "REFUSED_PRIOR_DISPATCH" in report.refusals
    assert "runtime.start" not in second.events.names() and not second.http.requests


def test_t53_a_case_recorded_only_in_the_workspace_ledger_is_also_consumed(tmp_path):
    h = Harness(tmp_path)
    h.collector.workspace = "ambiguous"
    report = h.run()
    assert "REFUSED_PRIOR_DISPATCH" in report.refusals and not report.claimed


def test_t53_losing_the_claim_race_starts_nothing(tmp_path):
    h = Harness(tmp_path)
    other = fn.CaseFence(mf.build_manifest(), h.record_root, sync=lambda fd: None)
    original = h.collector.remeasure

    def raced():
        fresh = original()
        other.claim()  # another process wins between the final measurement and our claim
        return fresh

    h.collector.remeasure = raced
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert "CASE_ALREADY_CLAIMED" in report.refusals
    assert "runtime.start" not in h.events.names() and not h.http.requests


def test_t54_the_start_record_is_durable_before_the_process_and_a_failed_record_prevents_the_start(
    tmp_path,
):
    h = Harness(tmp_path)

    class FailingStage(fn.CaseFence):
        def record_stage(self, stage, **facts):
            if stage == "managed_start_attempted":
                raise fn.FenceRefusal(fn.STAGE_REFUSED, "disk full")
            return super().record_stage(stage, **facts)

    h.fence = FailingStage(h.manifest, h.record_root, sync=lambda fd: None)
    report = h.run()
    assert "runtime.start" not in h.events.names()
    assert report.claimed and not report.executed
    assert report.result.result_class != ev.TECHNICAL_PASS_CONSTRAINED
    assert report.exception == "FenceRefusal"
    assert make_second(h).state().status in ("open", "terminal")  # still consumed


def make_second(h):
    return fn.CaseFence(h.manifest, h.record_root, sync=lambda fd: None)


def test_t55_the_dispatch_record_is_durable_before_the_post_and_a_failed_record_prevents_it(
    tmp_path,
):
    h = Harness(tmp_path)

    class FailingDispatch(fn.CaseFence):
        def record_stage(self, stage, **facts):
            if stage == "generation_dispatched":
                raise fn.FenceRefusal(fn.STAGE_REFUSED, "ledger inaccessible")
            return super().record_stage(stage, **facts)

    h.fence = FailingDispatch(h.manifest, h.record_root, sync=lambda fd: None)
    report = h.run()
    assert not h.http.generation_posts()  # no request was ever sent
    assert not report.executed and report.claimed
    assert h.runtime.stops == 1  # torn down through the manager only


def test_t55_every_stage_record_precedes_its_action(tmp_path):
    seen = []

    class Recording(fn.CaseFence):
        def record_stage(self, stage, **facts):
            seen.append(("record", stage))
            return super().record_stage(stage, **facts)

    h = Harness(tmp_path)
    h.fence = Recording(h.manifest, h.record_root, sync=lambda fd: None)
    original_post = h.http.post_json
    original_start = h.runtime.start

    def post(path, body, *, timeout_s):
        seen.append(("action", f"post {path}"))
        return original_post(path, body, timeout_s=timeout_s)

    def start():
        seen.append(("action", "start"))
        return original_start()

    h.http.post_json = post
    h.runtime.start = start
    h.run()
    flat = [f"{kind}:{what}" for kind, what in seen]
    assert flat.index("record:managed_start_attempted") < flat.index("action:start")
    assert flat.index("record:selection_attempted") < flat.index("action:post /sdapi/v1/options")
    assert flat.index("record:generation_dispatched") < flat.index("action:post /sdapi/v1/txt2img")
    assert flat.index("record:startup_observed") < flat.index("record:selection_attempted")
    assert flat.index("record:selection_confirmed") < flat.index("record:generation_dispatched")


# --- T56: lifecycle failures ---------------------------------------------------------------------------------------------


def test_t56_a_start_failure_is_a_loader_failure_with_an_owned_stop_and_a_terminal_record(tmp_path):
    h = Harness(tmp_path, runtime=None)
    h.runtime = FakeRuntime(h.events, start_raises=RuntimeError("port bound"))
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert report.claimed and not report.executed and not h.http.requests
    assert h.runtime.stops == 1
    assert h.fence.state().status == "terminal"
    with pytest.raises(fn.FenceRefusal):
        make_second(h).claim()


def test_t56_unverified_ownership_never_proceeds_to_the_endpoint(tmp_path):
    h = Harness(tmp_path)
    h.runtime = FakeRuntime(h.events, owned=False)
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert "OWNERSHIP_NOT_VERIFIED" in report.refusals
    assert not h.http.requests  # nothing was sent to an endpoint we do not own
    assert (
        h.runtime.stops == 1
    )  # the manager stops only what it owns; the harness acts on no other pid


def test_t56_a_readiness_timeout_is_a_loader_failure_and_never_reaches_selection(tmp_path):
    h = Harness(tmp_path, http=None)
    h.use_http(FakeHttp(h.events, h.clock, never_ready=True))
    h.config = replace(h.config, ready_timeout_s=5.0)
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert "READINESS_TIMEOUT" in report.refusals
    assert not [r for r in h.http.requests if r[0] == "POST"]


def test_t56_non_default_sampling_options_stop_the_run_before_any_selection(tmp_path):
    h = Harness(tmp_path, http=None)
    h.use_http(FakeHttp(h.events, h.clock, options={"beta_dist_alpha": 0.9}))
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert "OPTION_NOT_DEFAULT" in report.refusals
    assert not [r for r in h.http.requests if r[0] == "POST"]


def test_t56_a_silently_dropped_module_is_caught_by_the_read_back_and_nothing_is_generated(
    tmp_path,
):
    h = Harness(tmp_path, http=None)
    h.use_http(FakeHttp(h.events, h.clock, drop_module=True))
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert "SELECTION_MODULES_MISMATCH" in report.refusals
    assert not h.http.generation_posts()
    assert report.stages[-1] == "terminal_evidence" and "generation_dispatched" not in report.stages


# --- T57: stop, ambiguity and shutdown -----------------------------------------------------------------------------------


def test_t57_a_halt_before_dispatch_prevents_the_request(tmp_path):
    h = Harness(tmp_path)

    def script(sampler):
        if h.events.names().count("http.post") >= 1:  # after the selection POST
            sampler.fire("REQUEST_OWNER_STOP", "VRAM_AT_OR_ABOVE_RATIO")

    h.sampler_kwargs = {"script": script}
    report = h.run()
    assert not h.http.generation_posts()
    assert report.result.result_class == ev.RESOURCE_ABORT_REQUESTED
    assert report.halt["first_trigger"] == "VRAM_AT_OR_ABOVE_RATIO"
    assert "generation_dispatched" not in report.stages
    assert h.runtime.stops == 1


def test_t57_a_halt_during_generation_requests_an_owned_stop_and_never_resends(tmp_path):
    h = Harness(tmp_path)
    release = threading.Event()

    def generation(http):
        release.wait(5)
        return cs.HttpResult(None, None, "connection reset by the stopped runtime")

    h.http.on_generation = generation
    h.config = replace(h.config, supervision_interval_s=0.05, abort_join_s=2.0)
    original_stop = h.runtime.stop

    def stop():
        release.set()  # the manager's stop ends the connection
        return original_stop()

    h.runtime.stop = stop

    def script(sampler):
        if len(h.http.generation_posts()) == 1:
            sampler.fire("REQUEST_OWNER_STOP", "GPU_TEMPERATURE_AT_OR_ABOVE_LIMIT")

    h.sampler_kwargs = {"script": script}
    report = h.run()
    assert len(h.http.generation_posts()) == 1  # exactly one, ever
    assert h.runtime.stops == 1
    assert report.halt["codes"] == ["GPU_TEMPERATURE_AT_OR_ABOVE_LIMIT"]
    assert report.result.result_class in (ev.AMBIGUOUS_DISPATCH, ev.RESOURCE_ABORT_REQUESTED)
    assert (
        report.result.result_class == ev.AMBIGUOUS_DISPATCH
        or ev.AMBIGUOUS_DISPATCH in report.result.also
    )
    assert report.halt["last_values"]


def test_t57_a_transport_failure_after_the_send_is_ambiguous_and_is_not_replayed(tmp_path):
    h = Harness(tmp_path)
    h.http.generation = cs.HttpResult(None, None, "ConnectionResetError")
    report = h.run()
    assert report.result.result_class == ev.AMBIGUOUS_DISPATCH
    assert len(h.http.generation_posts()) == 1
    assert report.stages[-1] == "terminal_evidence" and "generation_dispatched" in report.stages
    again = Harness(tmp_path, fence=make_second(h))
    again.bundle_dir = tmp_path / "again"
    assert "REFUSED_PRIOR_DISPATCH" in again.run().refusals
    assert not again.http.requests


def test_t57_an_exception_inside_the_post_is_also_ambiguous_not_retried(tmp_path):
    h = Harness(tmp_path)

    def explode(http):
        raise RuntimeError("socket closed")

    h.http.on_generation = explode
    report = h.run()
    assert report.result.result_class == ev.AMBIGUOUS_DISPATCH
    assert len(h.http.generation_posts()) == 1


def test_t58_a_shutdown_that_cannot_complete_stops_the_automation_with_operator_instructions(
    tmp_path,
):
    h = Harness(tmp_path, authority=physical())
    h.runtime = FakeRuntime(
        h.events,
        shutdown=rt.ShutdownResult(
            True, False, True, False, (4243,), "the manager-owned stop did not return"
        ),
    )
    report = h.run()
    assert not report.result.is_pass
    assert report.shutdown["outcome"] == "timed_out"
    assert report.recovery_instructions == rt.RECOVERY_INSTRUCTIONS
    assert h.runtime.stops == 1  # no second attempt and no alternative authority
    assert h.events.names().count("runtime.stop") == 1


def test_t58_survivors_after_a_stop_block_a_pass_and_are_reported(tmp_path):
    h = Harness(tmp_path, authority=physical())
    h.runtime = FakeRuntime(
        h.events, shutdown=rt.ShutdownResult(True, True, False, False, (4243,), "survivor")
    )
    report = h.run()
    assert report.result.result_class == ev.INSTRUMENTATION_GAP
    assert "shutdown_verified_clean" in report.result.reasons
    assert report.shutdown["survivors"] == [4243]


# --- T59: adjudication of results ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response,expected",
    [
        (cs.HttpResult(500, {"error": "OutOfMemoryError"}), ev.OUTPUT_VALIDATION_FAIL),
        (cs.HttpResult(200, good_body(images=[])), ev.OUTPUT_VALIDATION_FAIL),
        (cs.HttpResult(200, good_body(seed=1)), ev.OUTPUT_VALIDATION_FAIL),
        (
            cs.HttpResult(200, good_body(infotext=INFOTEXT.replace("Shift: 9.0", "Shift: 3.5"))),
            ev.OUTPUT_VALIDATION_FAIL,
        ),
        (
            cs.HttpResult(
                200,
                good_body(
                    infotext=INFOTEXT.replace("Model hash: 59610861d4", "Model hash: ffffffffff")
                ),
            ),
            ev.OUTPUT_VALIDATION_FAIL,
        ),
    ],
)
def test_t59_an_invalid_or_mismatched_response_is_an_output_failure(tmp_path, response, expected):
    h = Harness(tmp_path, authority=physical())
    h.http.generation = response
    report = h.run()
    assert report.result.result_class == expected
    assert not report.result.is_pass
    assert len(h.http.generation_posts()) == 1


def test_t59_incomplete_identity_evidence_is_not_a_pass(tmp_path):
    h = Harness(tmp_path, authority=physical())
    h.http.generation = cs.HttpResult(
        200, good_body(infotext=INFOTEXT.replace("Model hash: 59610861d4, ", ""))
    )
    report = h.run()
    assert not report.result.is_pass


def test_t60_new_fault_records_boot_changes_and_incomplete_coverage_are_never_a_clean_pass(
    tmp_path,
):
    def snapshot(**kw):
        return lambda: complete_faults(taken="2026-01-01T12:05:00+00:00", **kw)

    cases = {
        "new_records": (snapshot(ids=("100", "101", "999")), ev.SYSTEM_OR_GPU_FAULT),
        "reboot": (snapshot(boot="2026-01-01T12:01:00+00:00"), ev.SYSTEM_OR_GPU_FAULT),
        "missing_snapshot": (lambda: None, ev.INSTRUMENTATION_GAP),
    }
    for name, (after, expected) in cases.items():
        h = Harness(tmp_path / name, authority=physical(), fault_after=after)
        report = h.run()
        assert report.result.result_class == expected, name
        assert not report.result.is_pass

    partial = complete_faults(taken="2026-01-01T12:05:00+00:00")
    degraded = dict(partial.sources)
    degraded["wer_reports"] = ev.FaultSourceSnapshot("wer_reports", "inaccessible", frozenset())
    h = Harness(
        tmp_path / "partial",
        authority=physical(),
        fault_after=ev.FaultSnapshot(partial.taken_utc, BOOT, degraded),
    )
    assert h.run().result.result_class == ev.INSTRUMENTATION_GAP


def test_t60_the_settle_interval_must_elapse_before_the_after_snapshot(tmp_path):
    h = Harness(
        tmp_path, authority=physical(), config=cs.CaseConfig(settle_s=10.0, ready_timeout_s=30.0)
    )
    report = h.run()
    assert (
        report.result.result_class == ev.INSTRUMENTATION_GAP
    )  # 10 s < the required settle interval
    assert "settle_time_not_elapsed" in report.faults["gaps"]


def test_t61_telemetry_gaps_missing_fields_and_sampler_faults_are_never_a_pass(tmp_path):
    h = Harness(tmp_path, authority=physical(), sampler={"samples": 3})
    assert h.run().result.result_class == ev.INSTRUMENTATION_GAP
    h = Harness(
        tmp_path / "field",
        authority=physical(),
        sampler={"status_overrides": {"shared_vram_bytes": "missing"}},
    )
    report = h.run()
    assert report.result.result_class == ev.INSTRUMENTATION_GAP
    assert "shared_vram_bytes" in report.telemetry["missing_fields"]


def test_t61_a_cannot_verify_halt_after_dispatch_is_never_a_pass_and_names_the_trigger(tmp_path):
    h = Harness(tmp_path / "cv", authority=physical())

    def script(sampler):
        if len(h.http.generation_posts()) == 1 and sampler.halt is None:
            sampler.fire("CANNOT_VERIFY_SAFE_STATE", "TELEMETRY_STALE")

    h.sampler_kwargs = {"script": script}
    h.config = replace(h.config, supervision_interval_s=0.05)
    release = threading.Event()
    h.http.on_generation = lambda http: (release.wait(0.3), cs.HttpResult(200, good_body()))[1]
    report = h.run()
    assert not report.result.is_pass
    assert report.halt["action"] == "CANNOT_VERIFY_SAFE_STATE"


# --- T62: stage attribution ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "progress,expected",
    [
        (
            {"state": {"sampling_steps": 9, "sampling_step": 0, "job_count": 1}},
            ("denoise", "forge_api"),
        ),
        (
            {"state": {"sampling_steps": 9, "sampling_step": 7, "job_count": 1}},
            ("denoise", "forge_api"),
        ),
        (
            {"state": {"sampling_steps": 9, "sampling_step": 8, "job_count": 1}},
            ("unknown", "unknown"),
        ),  # last step / decode
        (
            {"state": {"sampling_steps": 0, "sampling_step": 0, "job_count": 1}},
            ("unknown", "unknown"),
        ),  # still loading
        (
            {"state": {"sampling_steps": 9, "sampling_step": 3, "job_count": 0}},
            ("unknown", "unknown"),
        ),
        (
            {"state": {"sampling_steps": "9", "sampling_step": 3, "job_count": 1}},
            ("unknown", "unknown"),
        ),
        (
            {"state": {"sampling_steps": True, "sampling_step": 0, "job_count": 1}},
            ("unknown", "unknown"),
        ),
        ({"state": None}, ("unknown", "unknown")),
        (None, ("unknown", "unknown")),
        ("not an object", ("unknown", "unknown")),
    ],
)
def test_t62_only_a_running_sampling_loop_is_attributed_everything_else_is_unknown(
    progress, expected
):
    info = cs.stage_from_progress(progress)
    assert (info.stage, info.source) == expected


# --- T63: evidence -------------------------------------------------------------------------------------------------------


def test_t63_the_bundle_has_raw_and_redacted_copies_hashes_and_every_required_item(tmp_path):
    h = Harness(tmp_path)
    report = h.run()
    index = json.loads((h.bundle_dir / "index.json").read_text())
    assert index["gaps"] == [] and index["complete_items"] is True
    for name in (
        "manifest",
        "effective_request",
        "preflight",
        "fault_before",
        "fault_after",
        "shutdown",
        "coverage",
    ):
        assert (h.bundle_dir / "raw" / f"{name}.json").is_file()
        assert (h.bundle_dir / "redacted" / f"{name}.json").is_file()
    assert (h.bundle_dir / "artifacts" / "output.png").is_file()
    import hashlib

    entry = index["files"]["artifacts/output.png"]
    assert (
        entry["sha256"]
        == hashlib.sha256((h.bundle_dir / "artifacts" / "output.png").read_bytes()).hexdigest()
    )
    assert report.output["sha256"] == entry["sha256"]
    raw_request = (h.bundle_dir / "raw" / "effective_request.json").read_text()
    redacted_request = (h.bundle_dir / "redacted" / "effective_request.json").read_text()
    assert "ceramic teapot" in raw_request and "ceramic teapot" not in redacted_request
    assert "distilled_cfg_scale" in raw_request


def test_t63_a_failure_to_write_evidence_is_a_downgrade_not_a_silent_pass(tmp_path):
    h = Harness(tmp_path, authority=physical())
    h.bundle_dir.mkdir(parents=True)
    (h.bundle_dir / "raw").mkdir()
    (h.bundle_dir / "raw" / "manifest.json").write_text("pre-existing evidence")
    report = h.run()
    assert not report.result.is_pass
    assert any(r.startswith("EVIDENCE_BUNDLE_FAILED") for r in report.refusals)
    assert (
        h.bundle_dir / "raw" / "manifest.json"
    ).read_text() == "pre-existing evidence"  # never overwritten


# --- T64: interrupts -----------------------------------------------------------------------------------------------------


def test_t64_an_operator_interrupt_tears_down_through_the_manager_records_and_reraises(tmp_path):
    h = Harness(tmp_path)

    def interrupt(http):
        raise KeyboardInterrupt()

    h.http.on_generation = interrupt
    h.config = replace(h.config, supervision_interval_s=0.05)
    # KeyboardInterrupt inside the worker thread is captured as an ambiguous transport failure and never re-sent
    report = h.run()
    assert report.result.result_class == ev.AMBIGUOUS_DISPATCH
    assert h.runtime.stops == 1 and len(h.http.generation_posts()) == 1


def test_t64_an_interrupt_in_the_coordinator_thread_still_stops_the_runtime_and_closes_the_ledger(
    tmp_path,
):
    h = Harness(tmp_path)
    original = h.collector.recheck_served
    calls = {"n": 0}

    def interrupt_after_selection():
        calls["n"] += 1
        if calls["n"] == 2:  # the pre-dispatch re-check
            raise KeyboardInterrupt()
        return original()

    h.collector.recheck_served = interrupt_after_selection
    with pytest.raises(KeyboardInterrupt):
        h.run()
    assert h.runtime.stops == 1
    assert not h.http.generation_posts()
    assert make_second(h).state().status in ("terminal", "open")
    with pytest.raises(fn.FenceRefusal):
        make_second(h).claim()


# --- T65: the real sampler, stepped deterministically -------------------------------------------------------------------


class SteppedSampler:
    """A real TelemetrySampler + SafetyMonitor + providers, advanced one tick per coordinator observation."""

    def __init__(self, monitor, writer, stage, endpoint, *, providers, clock):
        self.inner = sp.TelemetrySampler(
            providers,
            monitor,
            writer,
            mono=clock.mono,
            utc=lambda: UTC_NOW,
            stage=stage,
            endpoint=endpoint,
            config=sp.SamplerConfig(provider_timeout_s=1.0),
        )
        self.monitor = monitor
        self.clock = clock

    sample_count = property(lambda self: self.inner.sample_count)
    clean_streak = property(lambda self: self.inner.clean_streak)
    halt_event = property(lambda self: self.inner.halt_event)
    halt = property(lambda self: self.inner.halt)
    harness_fault = property(lambda self: self.inner.harness_fault)
    provenance = property(lambda self: self.inner.provenance)

    def write_header(self, **facts):
        self.inner.write_header(**facts)

    def start(self):
        self.monitor.begin_observation()
        self.inner.sample_once()

    def watchdog_tick(self):
        self.inner.sample_once()

    def stop(self, timeout_s=5.0):
        self.inner.stop()


def test_t65_the_real_sampler_and_monitor_end_to_end_a_vram_spike_halts_before_dispatch(tmp_path):
    h = Harness(tmp_path)
    state = {"vram": 2 * GIB}

    class Gpu:
        name = "nvml"
        fields = sp.NvmlProvider.fields

        def read(self):
            values = {
                "vram_used_bytes": state["vram"],
                "vram_total_bytes": 12 * GIB,
                "gpu_temperature_c": 45.0,
                "gpu_utilization_percent": 3.0,
                "gpu_board_power_w": 30.0,
                "gpu_device_present": True,
            }
            return sp.ProviderReading(values, dict.fromkeys(values, "ok"), "fake")

    class Mem:
        name = "windows_memory"
        fields = sp.NativeMemoryProvider.fields

        def read(self):
            values = {
                "commit_total_bytes": 10 * GIB,
                "commit_limit_bytes": 50 * GIB,
                "commit_headroom_bytes": 40 * GIB,
                "ram_available_bytes": 22 * GIB,
            }
            return sp.ProviderReading(values, dict.fromkeys(values, "ok"), "fake")

    class Pdh:
        name = "windows_pdh"
        fields = sp.PdhProvider.fields

        def read(self):
            values = {"shared_vram_bytes": int(0.3 * GIB), "hard_pages_input_per_s": 1.0}
            return sp.ProviderReading(values, dict.fromkeys(values, "ok"), "fake")

    class Tree:
        name = "owned_process_tree"
        fields = sp.ProcessTreeProvider.fields

        def read(self):
            values = {"forge_tree_working_set_bytes": GIB, "forge_tree_private_bytes": 2 * GIB}
            return sp.ProviderReading(values, dict.fromkeys(values, "ok"), "fake")

    def factory(monitor, writer, stage, endpoint):
        sampler = SteppedSampler(
            monitor, writer, stage, endpoint, providers=[Mem(), Gpu(), Pdh(), Tree()], clock=h.clock
        )
        h.samplers.append(sampler)
        return sampler

    h.make_sampler = factory
    original_post = h.http.post_json

    def post(path, body, *, timeout_s):
        if path == "/sdapi/v1/options":
            state["vram"] = int(11.9 * GIB)  # the card fills after the selection: 99% of 12 GiB
        return original_post(path, body, timeout_s=timeout_s)

    h.http.post_json = post
    h.config = replace(h.config, settle_s=0.0)
    report = h.run()
    assert not h.http.generation_posts()
    assert report.halt is not None and report.halt["action"] == "REQUEST_OWNER_STOP"
    assert report.result.result_class == ev.RESOURCE_ABORT_REQUESTED
    assert report.halt["last_values"]["vram_used_bytes"] == int(11.9 * GIB)
    records = [json.loads(line) for line in (tmp_path / "samples.jsonl").read_text().splitlines()]
    assert any(r["kind"] == "transition" and r["to"] == "REQUEST_OWNER_STOP" for r in records)
    assert any(r["kind"] == "header" for r in records)


# --- T66: authority and structure ----------------------------------------------------------------------------------------


def test_t66_a_physical_authority_cannot_be_constructed_directly():
    with pytest.raises(cs.AuthorityError):
        cs.ExecutionAuthority(adj.AUTHORITY_PHYSICAL)
    with pytest.raises(cs.AuthorityError):
        cs.ExecutionAuthority("anything-else")
    assert cs.ExecutionAuthority.synthetic().kind == adj.AUTHORITY_SYNTHETIC
    assert cs.mint_physical_authority("a" * 64).kind == adj.AUTHORITY_PHYSICAL


def test_t66_the_coordinator_performs_no_io_of_its_own_and_one_post_per_action():
    import ast

    source = Path(cs.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {
        "socket",
        "subprocess",
        "requests",
        "urllib",
        "http",
        "ctypes",
        "psutil",
        "os",
        "shutil",
    }
    posts = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "post_json"
    ]
    assert (
        len(posts) == 1
    )  # one call site: both the selection and the generation go through it, supervised
    supervised = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_supervised_request"
    ]
    assert len(supervised) == 2  # the selection request and the single generation request
    assert not [
        n for n in ast.walk(tree) if isinstance(n, ast.While) and "post_json" in ast.dump(n)
    ]


# --- T80-T86: independent-review findings --------------------------------------------------------------------------------


def test_t80_the_manager_returns_before_the_endpoint_binds_and_the_run_still_proceeds(tmp_path):
    h = Harness(
        tmp_path
    )  # two refused connections first; the listener exists only once the endpoint answers
    report = h.run()
    assert report.claimed and report.executed
    assert h.runtime.ownership_calls[0] is False  # the boot window never demanded a listener
    assert True in h.runtime.ownership_calls  # ... and one was required once the endpoint answered
    option_gets = [r for r in h.http.requests if r[0] == "GET" and r[1] == "/sdapi/v1/options"]
    assert len(option_gets) >= 4  # two refused + one answered + the read-back


def test_t80_a_listener_outside_the_owned_tree_during_boot_is_refused_before_any_request(tmp_path):
    h = Harness(tmp_path)
    h.runtime = FakeRuntime(h.events, foreign_listener=True)
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert "OWNERSHIP_NOT_VERIFIED" in report.refusals
    assert not h.http.requests  # nothing was sent while a stranger held the port
    assert h.runtime.stops == 1


def test_t81_an_endpoint_that_is_not_the_owned_tree_never_receives_the_selection(tmp_path):
    h = Harness(tmp_path)
    h.runtime.foreign_after_ready = (
        True  # another process binds the port and is the one that answers
    )
    report = h.run()
    assert report.result.result_class == ev.LOADER_FAILED
    assert "ENDPOINT_NOT_OWNED" in report.refusals
    assert not [r for r in h.http.requests if r[0] == "POST"]
    assert "startup_observed" not in report.stages


def test_t82_an_unhealthy_sampler_refuses_before_the_case_is_consumed_or_anything_starts(tmp_path):
    h = Harness(tmp_path, sampler={"unhealthy": True})
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert "SAMPLER_NOT_HEALTHY" in report.refusals
    assert not report.claimed and h.fence.state().status == "none"
    assert "runtime.start" not in h.events.names() and not h.http.requests
    assert h.samplers[0].stopped


def test_t82_a_sampler_that_cannot_be_built_refuses_without_consuming_the_case(tmp_path):
    h = Harness(tmp_path)

    def broken(monitor, writer, stage, endpoint):
        raise RuntimeError("NVML identify failed")

    h.make_sampler = broken
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert any(r.startswith("SAMPLER_UNAVAILABLE") for r in report.refusals)
    assert not report.claimed and h.fence.state().status == "none"


def test_t83_an_unreadable_fault_snapshot_and_a_failing_sampler_stop_still_end_in_a_recorded_non_pass(
    tmp_path,
):
    def denied():
        raise OSError("event log denied")

    h = Harness(tmp_path, authority=physical(), fault_after=denied)
    original_stop = FakeSampler.stop

    def failing_stop(self, timeout_s=5.0):
        original_stop(self, timeout_s)
        raise RuntimeError("thread would not join")

    FakeSampler.stop = failing_stop
    try:
        report = h.run()
    finally:
        FakeSampler.stop = original_stop
    assert not report.result.is_pass
    assert report.result.result_class == ev.INSTRUMENTATION_GAP
    assert any(r.startswith("FAULT_SNAPSHOT_FAILED") for r in report.refusals)
    assert any(r.startswith("SAMPLER_STOP_FAILED") for r in report.refusals)
    assert h.fence.state().status == "terminal"  # the evidence was not lost to the exception


def test_t83_an_unexpected_ledger_error_while_closing_the_case_is_reported_and_leaves_it_open(
    tmp_path,
):
    h = Harness(tmp_path, authority=physical())

    def broken(manifest, outcome):
        raise StopIteration

    h.fence._ledger.record_outcome = broken
    report = h.run()
    assert not report.result.is_pass
    assert any(r.startswith("TERMINAL_RECORD_FAILED") for r in report.refusals)
    assert h.fence.state().status == "open"  # ambiguous and consumed; never re-opened or repaired


def test_t84_a_halt_during_the_selection_request_stops_through_the_manager_and_sends_nothing_more(
    tmp_path,
):
    h = Harness(tmp_path)
    release = threading.Event()
    original_post = h.http.post_json

    def slow_selection(path, body, *, timeout_s):
        if path == "/sdapi/v1/options":
            h.http.requests.append(("POST", path, body))
            release.wait(5)
            return cs.HttpResult(None, None, "connection reset by the stopped runtime")
        return original_post(path, body, timeout_s=timeout_s)

    h.http.post_json = slow_selection
    original_stop = h.runtime.stop

    def stop():
        release.set()
        return original_stop()

    h.runtime.stop = stop

    def script(sampler):
        in_flight = [r for r in h.http.requests if r[0] == "POST" and r[1] == "/sdapi/v1/options"]
        if in_flight and sampler.halt is None:
            sampler.fire("REQUEST_OWNER_STOP", "SHARED_MEMORY_GROWTH")

    h.sampler_kwargs = {"script": script}
    h.config = replace(h.config, supervision_interval_s=0.05, abort_join_s=2.0)
    report = h.run()
    assert not h.http.generation_posts()
    assert h.runtime.stops == 1
    assert report.halt["codes"] == ["SHARED_MEMORY_GROWTH"]
    assert report.result.result_class == ev.RESOURCE_ABORT_REQUESTED
    assert "selection_confirmed" not in report.stages


def test_t85_the_baseline_and_fault_snapshot_are_taken_again_after_a_long_operator_wait(tmp_path):
    h = Harness(tmp_path)
    original_confirm = h.confirm

    def slow_confirm(summary):
        h.clock.now += (
            600.0  # ten minutes at the prompt: the first window (60 s limit) is long stale
        )
        return original_confirm(summary)

    h.confirm = slow_confirm
    report = h.run()
    assert report.claimed and report.executed
    assert report.preflight["decision"] == "PREPARED_FOR_OWNER_REVIEW"


def test_t85_without_a_fresh_baseline_the_stale_one_refuses_and_consumes_nothing(tmp_path):
    h = Harness(tmp_path)
    original_remeasure = h.collector.remeasure
    original_confirm = h.confirm

    def slow_confirm(summary):
        h.clock.now += 600.0
        return original_confirm(summary)

    def without_window():
        fresh = original_remeasure()
        return cs.Remeasured(fresh.observations, None, None)

    h.confirm = slow_confirm
    h.collector.remeasure = without_window
    report = h.run()
    assert not report.claimed and "FINAL_REMEASURE_REFUSED" in report.refusals
    assert "BASELINE_STALE" in report.refusals


@pytest.mark.parametrize(
    "secret", ["", "short", "wrong passphrase value", "A LONG OWNER PASSPHRASE"]
)
def test_t86_the_owner_passphrase_is_required_and_a_wrong_one_consumes_nothing(tmp_path, secret):
    h = Harness(tmp_path, secret=secret)
    report = h.run()
    assert report.result.result_class == ev.PREFLIGHT_REFUSED
    assert "OWNER_PASSPHRASE_MISMATCH" in report.refusals
    assert not report.claimed and h.fence.state().status == "none"
    assert "runtime.start" not in h.events.names() and "remeasure" not in h.events.names()


def test_t86_the_passphrase_is_asked_only_after_the_typed_phrase_and_never_written(tmp_path):
    h = Harness(tmp_path, typed="wrong phrase")
    asked = []
    original = h.coordinator

    def coordinator():
        coord = original()
        previous = coord.ports.passphrase
        coord.ports.passphrase = lambda: (asked.append(1), previous())[1]
        return coord

    h.coordinator = coordinator
    report = h.run()
    assert "OPERATOR_CONFIRMATION_MISMATCH" in report.refusals and asked == []
    h2 = Harness(tmp_path / "ok")
    h2.run()
    leaked = [
        p
        for p in (tmp_path / "ok").rglob("*")
        if p.is_file() and PASSPHRASE.encode() in p.read_bytes()
    ]
    assert leaked == []


# --- R1-R4 final safety corrections (deterministic ports; no host/runtime actions) ----------------


def assert_unconsumed(h, report):
    assert not report.claimed and not report.executed, report.as_dict()
    assert h.fence.state().status == "none"
    assert "runtime.start" not in h.events.names()
    assert h.runtime.stops == 0 and not h.http.requests
    assert all(s.stopped for s in h.samplers)


@pytest.mark.parametrize("when", ["confirmation", "passphrase", "sampler_health"])
def test_r2_expiry_during_operator_or_sampler_wait_refuses_before_claim(tmp_path, when):
    h = Harness(tmp_path)
    current = [UTC_NOW]
    h.clock.utc = lambda: current[0]

    def expire():
        current[0] = "2026-01-02T00:00:00+00:00"

    if when == "confirmation":
        original = h.confirm
        h.confirm = lambda summary: (expire(), original(summary))[1]
    elif when == "passphrase":
        original = h.coordinator

        def coordinator():
            c = original()
            c.ports.passphrase = lambda: (expire(), PASSPHRASE)[1]
            return c

        h.coordinator = coordinator
    else:
        h.sampler_kwargs = {"script": lambda sampler: expire()}
    report = h.run()
    assert_unconsumed(h, report)
    assert "AUTHORIZATION_EXPIRED" in report.refusals


@pytest.mark.parametrize(
    "code",
    [
        au.CodeRevision("clean", "c" * 40, "b" * 64),
        au.CodeRevision("clean", "a" * 40, "d" * 64),
        au.CodeRevision("dirty", "a" * 40, "b" * 64),
        au.CodeRevision("unverifiable", None, None),
    ],
)
def test_r2_code_drift_during_wait_refuses_without_consuming(tmp_path, code):
    h = Harness(tmp_path)
    original = h.confirm

    def confirm(summary):
        h.collector.code = code
        return original(summary)

    h.confirm = confirm
    report = h.run()
    assert_unconsumed(h, report)
    assert any(
        code in report.refusals
        for code in ("CODE_REVISION_UNTRUSTED", "AUTHORIZATION_CODE_MISMATCH")
    )


@pytest.mark.parametrize("mode", ["changed", "absent", "error", "unwired"])
def test_r2_record_continuity_is_required_at_claim(tmp_path, mode):
    h = Harness(tmp_path)
    c = h.coordinator()
    if mode == "unwired":
        c.ports.authorization_current = None
    elif mode == "error":

        def unavailable(approved):
            raise OSError("unreadable")

        c.ports.authorization_current = unavailable
    else:
        c.ports.authorization_current = lambda approved: False
    report = c.run(h.authority, h.authorization)
    assert_unconsumed(h, report)
    assert "AUTHORIZATION_RECORD_NOT_CURRENT" in report.refusals


def test_r2_valid_authorization_code_and_fresh_state_continue_to_claim(tmp_path):
    h = Harness(tmp_path)
    original_claim = h.fence.claim

    def claim(**kw):
        assert h.events.names()[-1] == "recheck_code"
        return original_claim(**kw)

    h.fence.claim = claim
    report = h.run()
    assert report.claimed and report.executed and not report.result.is_pass


@pytest.mark.parametrize(
    "section,code,severity",
    [
        ("processes", "RUNTIME_CONFLICT_FOREIGN_OWNER", "refuse"),
        ("endpoint", "RUNTIME_PORT_OCCUPIED", "refuse"),
        ("processes", "PROCESS_LIST_UNAVAILABLE", "inconclusive"),
        ("endpoint", "RUNTIME_PORT_UNVERIFIED", "inconclusive"),
    ],
)
def test_r3_new_runtime_or_unknown_inventory_after_confirmation_refuses(
    tmp_path, section, code, severity
):
    h = Harness(tmp_path)
    original = h.confirm

    def confirm(summary):
        h.collector.runtime_sections[section] = [Finding(code, severity, "changed during wait")]
        return original(summary)

    h.confirm = confirm
    report = h.run()
    assert_unconsumed(h, report)
    assert code in report.refusals


def test_r3_final_preflight_cannot_age_out_during_sampler_health(tmp_path):
    h = Harness(tmp_path)
    h.sampler_kwargs = {"script": lambda sampler: h.clock.sleep(31) if sampler.ticks == 3 else None}
    report = h.run()
    assert_unconsumed(h, report)
    assert "FINAL_PREFLIGHT_STALE" in report.refusals


class ScriptedPostWorker:
    """No real thread or sleeping: join advances the injected clock; the transport never completes unless scripted."""

    def __init__(self, target, clock, *, complete_after=None, **kw):
        self.target, self.clock = target, clock
        self.complete_after = complete_after
        self.name = kw.get("name")
        self.joins = 0
        self.alive_checks = 0
        self.alive = True

    def start(self):
        if self.name == "img154b-progress-observation":
            self.target()
            self.alive = False

    def is_alive(self):
        self.alive_checks += 1
        if self.alive_checks > 40:
            raise RuntimeError("UNBOUNDED_SUPERVISION_SPIN")
        return self.alive

    def join(self, seconds):
        self.joins += 1
        if self.joins > 12:
            raise RuntimeError("UNBOUNDED_SUPERVISION")
        self.clock.sleep(seconds)
        if self.complete_after is not None and self.joins >= self.complete_after:
            self.target()
            self.alive = False


@pytest.mark.parametrize("path", [rq.OPTIONS_ENDPOINT, rq.TXT2IMG_ENDPOINT])
@pytest.mark.parametrize("stop_mode", ["clean", "timed_out", "unverified", "raises"])
def test_r4_overall_deadline_bounds_live_worker_and_records_uncertainty(
    tmp_path, monkeypatch, path, stop_mode
):
    h = Harness(tmp_path)
    h.config = replace(h.config, supervision_interval_s=1, abort_join_s=2)
    c = h.coordinator()
    workers = []

    def thread(target, **kw):
        worker = ScriptedPostWorker(target, h.clock, **kw)
        workers.append(worker)
        return worker

    monkeypatch.setattr(cs.threading, "Thread", thread)
    if stop_mode == "raises":
        h.runtime.stop = lambda: (_ for _ in ()).throw(OSError("stop unavailable"))
    elif stop_mode != "clean":
        h.runtime.shutdown = rt.ShutdownResult(
            True, False, stop_mode == "timed_out", False, (), stop_mode
        )
    writer = ev.DurableJsonlWriter(tmp_path / "requests.jsonl", redact=False)
    c._request_writer = writer
    sampler = h.make_sampler(None, writer, lambda: c._run.stage, lambda: "fake")
    response, aborted = c._supervised_request(sampler, path, b"{}", timeout_s=3, progress=True)
    assert aborted and response.status is None
    assert h.clock.now <= 5005
    assert sampler.ticks >= 3
    assert c._run.shutdown is not None
    assert c._run.shutdown.verified == (stop_mode == "clean")
    assert workers[0].is_alive()
    records = ev.read_jsonl(writer.path)[0]
    assert any(r.get("reason") == "overall_deadline" for r in records)
    assert any(r.get("worker_outstanding") is True for r in records)
    assert "POST_OVERALL_TIMEOUT" in c._run.refusals


def test_r4_completion_within_deadline_is_accepted(tmp_path, monkeypatch):
    h = Harness(tmp_path)
    c = h.coordinator()
    monkeypatch.setattr(
        cs.threading,
        "Thread",
        lambda target, **kw: ScriptedPostWorker(target, h.clock, complete_after=1, **kw),
    )
    writer = ev.DurableJsonlWriter(tmp_path / "requests.jsonl", redact=False)
    c._request_writer = writer
    sampler = h.make_sampler(None, writer, lambda: c._run.stage, lambda: "fake")
    response, aborted = c._supervised_request(
        sampler,
        rq.OPTIONS_ENDPOINT,
        cs._json_bytes(rq.selection_payload(SERVED)),
        timeout_s=3,
        progress=False,
    )
    assert response.status == 200 and not aborted
    assert h.runtime.stops == 0


def test_r4_late_worker_completion_never_turns_aborted_generation_into_pass(tmp_path, monkeypatch):
    h = Harness(tmp_path, authority=physical())
    h.config = replace(
        h.config,
        generation_timeout_s=3,
        options_timeout_s=7,
        supervision_interval_s=1,
        abort_join_s=2,
    )
    workers = []

    def thread(target, **kw):
        worker = ScriptedPostWorker(target, h.clock, complete_after=1 if not workers else 4, **kw)
        workers.append(worker)
        return worker

    monkeypatch.setattr(cs.threading, "Thread", thread)
    report = h.run()
    assert report.claimed and report.executed
    assert report.result.result_class == ev.AMBIGUOUS_DISPATCH
    assert not report.result.is_pass and report.output is None
    assert len(h.http.generation_posts()) == 1
    assert h.runtime.stops == 1 and h.fence.state().status == "terminal"
    again = Harness(tmp_path, fence=make_second(h))
    again.bundle_dir = tmp_path / "again"
    assert "REFUSED_PRIOR_DISPATCH" in again.run().refusals and not again.http.requests


@pytest.mark.parametrize("change", ["delete", "replace", "mutate", "invalid"])
def test_r2_real_record_continuity_gate_refuses_before_claim(tmp_path, change):
    from dataclasses import asdict

    h = Harness(tmp_path)
    path = tmp_path / "synthetic-authorization.json"
    data = {"schema": au.AUTHORIZATION_SCHEMA, **asdict(h.authorization)}
    path.write_text(json.dumps(data), encoding="utf-8")
    original_record = au.read_authorization_record(path)
    c = h.coordinator()
    c.ports.authorization_current = original_record.is_current
    original = c.ports.confirm

    def confirm(summary):
        if change == "delete":
            path.unlink()
        elif change == "replace":
            other = tmp_path / "replacement.json"
            other.write_bytes(path.read_bytes())
            other.replace(path)
        elif change == "invalid":
            path.write_text("invalid", encoding="utf-8")
        else:
            data["accepted_risks"] = []
            path.write_text(json.dumps(data), encoding="utf-8")
        return original(summary)

    c.ports.confirm = confirm
    report = c.run(h.authority, h.authorization)
    assert_unconsumed(h, report)
    assert "AUTHORIZATION_RECORD_NOT_CURRENT" in report.refusals


@pytest.mark.parametrize("age", [None, float("nan"), float("inf"), -31, 31])
def test_r3_runtime_observation_timestamp_must_be_valid_and_current(tmp_path, age):
    h = Harness(tmp_path)
    original = h.collector.remeasure

    def remeasure():
        fresh = original()
        fresh.runtime_observed_mono_s = None if age is None else h.clock.mono() - age
        return fresh

    h.collector.remeasure = remeasure
    report = h.run()
    assert_unconsumed(h, report)
    assert "FINAL_PREFLIGHT_STALE" in report.refusals


@pytest.mark.parametrize(
    "reader", ["remeasure", "recheck_served", "recheck_code", "recheck_runtime"]
)
def test_r2_r3_final_reader_exception_is_an_unconsumed_refusal(tmp_path, reader):
    h = Harness(tmp_path)

    def inaccessible():
        raise TimeoutError("inventory timed out")

    setattr(h.collector, reader, inaccessible)
    assert_unconsumed(h, h.run())


def test_r4_monitor_halt_precedes_deadline_and_discards_late_success(tmp_path, monkeypatch):
    h = Harness(tmp_path)
    c = h.coordinator()
    c._request_writer = ev.DurableJsonlWriter(tmp_path / "requests.jsonl", redact=False)
    workers = []

    def thread(target, **kw):
        worker = ScriptedPostWorker(target, h.clock, complete_after=2, **kw)
        workers.append(worker)
        return worker

    monkeypatch.setattr(cs.threading, "Thread", thread)
    sampler = h.make_sampler(None, c._request_writer, lambda: c._run.stage, lambda: "fake")
    sampler.script = lambda s: s.fire("REQUEST_OWNER_STOP", "RAM_LOW") if s.ticks == 2 else None
    response, aborted = c._supervised_request(
        sampler,
        rq.OPTIONS_ENDPOINT,
        cs._json_bytes(rq.selection_payload(SERVED)),
        timeout_s=600,
        progress=False,
    )
    assert aborted and response.status is None
    assert "POST_MONITOR_ABORT" in c._run.refusals and "POST_OVERALL_TIMEOUT" not in c._run.refusals
    assert h.runtime.stops == 1 and not workers[0].is_alive()


def test_r4_intermittent_progress_cannot_extend_post_budget(tmp_path, monkeypatch):
    h = Harness(tmp_path)
    c = h.coordinator()
    c._request_writer = ev.DurableJsonlWriter(tmp_path / "requests.jsonl", redact=False)
    monkeypatch.setattr(
        cs.threading, "Thread", lambda target, **kw: ScriptedPostWorker(target, h.clock, **kw)
    )
    sampler = h.make_sampler(None, c._request_writer, lambda: c._run.stage, lambda: "fake")
    response, aborted = c._supervised_request(
        sampler, rq.TXT2IMG_ENDPOINT, b"{}", timeout_s=3, progress=True
    )
    progress = [r for r in h.http.requests if r[1].startswith(rq.PROGRESS_ENDPOINT)]
    assert len(progress) >= 2 and aborted and response.status is None
    assert h.clock.mono() <= 5033 and h.runtime.stops == 1


def test_r4_selection_timeout_stops_progression_before_generation(tmp_path, monkeypatch):
    h = Harness(tmp_path)
    h.config = replace(h.config, options_timeout_s=3, generation_timeout_s=7, abort_join_s=2)
    starts = []

    def thread(target, **kw):
        starts.append(h.clock.mono())
        return ScriptedPostWorker(target, h.clock, **kw)

    monkeypatch.setattr(cs.threading, "Thread", thread)
    report = h.run()
    assert report.requests[0]["mono_s"] - starts[0] == h.config.options_timeout_s
    assert report.claimed and not report.executed and not report.result.is_pass
    assert "POST_OVERALL_TIMEOUT" in report.refusals
    assert "selection_attempted" in report.stages and "generation_dispatched" not in report.stages
    assert not h.http.generation_posts() and h.runtime.stops == 1


def test_r4_timeout_record_is_durable_before_owned_stop(tmp_path, monkeypatch):
    h = Harness(tmp_path)
    c = h.coordinator()
    c._request_writer = ev.DurableJsonlWriter(tmp_path / "requests.jsonl", redact=False)
    monkeypatch.setattr(
        cs.threading, "Thread", lambda target, **kw: ScriptedPostWorker(target, h.clock, **kw)
    )
    original = h.runtime.stop

    def stop():
        records, torn, corrupt = ev.read_jsonl(c._request_writer.path)
        assert not torn and not corrupt
        assert records[-1]["reason"] == "overall_deadline" and records[-1]["ambiguous"]
        return original()

    h.runtime.stop = stop
    sampler = h.make_sampler(None, c._request_writer, lambda: c._run.stage, lambda: "fake")
    _, aborted = c._supervised_request(
        sampler, rq.OPTIONS_ENDPOINT, b"{}", timeout_s=3, progress=False
    )
    assert aborted and h.runtime.stops == 1


@pytest.mark.parametrize(
    "section,code",
    [("processes", "RUNTIME_CONFLICT_FOREIGN_OWNER"), ("endpoint", "RUNTIME_PORT_OCCUPIED")],
)
def test_r3_conflict_during_sampler_health_is_freshly_refused_before_claim(tmp_path, section, code):
    h = Harness(tmp_path)
    h.sampler_kwargs = {
        "script": lambda sampler: h.collector.runtime_sections.__setitem__(
            section, [Finding(code, "refuse", "appeared during sampler health")]
        )
    }
    report = h.run()
    assert_unconsumed(h, report)
    assert code in report.refusals


@pytest.mark.parametrize("halt", [False, True])
def test_r4_stalled_progress_observation_cannot_blind_supervisor(tmp_path, monkeypatch, halt):
    h = Harness(tmp_path)
    h.config = replace(h.config, supervision_interval_s=1, abort_join_s=2)
    c = h.coordinator()
    c._request_writer = ev.DurableJsonlWriter(tmp_path / "requests.jsonl", redact=False)
    workers = []

    def thread(target, **kw):
        worker = ScriptedPostWorker(target, h.clock, **kw)
        if kw["name"] == "img154b-progress-observation":
            worker.start = (
                lambda: None
            )  # pending/stalled GET worker; never completes or frees its slot
        workers.append((kw["name"], worker))
        return worker

    monkeypatch.setattr(cs.threading, "Thread", thread)

    def progress(path, *, timeout_s):
        # Represents a trickling/stalled GET: socket timeout is no overall bound.
        # A synchronous call makes the injected clock jump beyond the POST budget.
        h.clock.sleep(20)
        return cs.HttpResult(200, h.http.progress)

    h.http.get_json = progress
    sampler = h.make_sampler(None, c._request_writer, lambda: c._run.stage, lambda: "fake")
    if halt:
        sampler.script = lambda s: s.fire("REQUEST_OWNER_STOP", "RAM_LOW") if s.ticks == 2 else None
    response, aborted = c._supervised_request(
        sampler, rq.TXT2IMG_ENDPOINT, b"{}", timeout_s=3, progress=True
    )
    assert aborted and response.status is None
    assert c._run.requests[0]["mono_s"] - 5000 == (1 if halt else 3)
    assert h.runtime.stops == 1
    assert [name for name, _ in workers] == [
        "img154b-supervised-post",
        "img154b-progress-observation",
    ]
    assert c._run.requests[-1]["progress_worker_outstanding"] is True
    assert "PROGRESS_OBSERVER_MAY_BE_OUTSTANDING" in c._run.refusals


def test_r3_evidence_records_the_actual_claim_boundary_assessment(tmp_path):
    from datetime import datetime, timedelta

    h = Harness(tmp_path)
    h.clock.utc = lambda: (
        datetime.fromisoformat(UTC_NOW) + timedelta(seconds=h.clock.mono() - 5000)
    ).isoformat()
    claimed_utc = []
    original = h.fence.claim

    def claim(**kw):
        claimed_utc.append(h.clock.utc())
        return original(**kw)

    h.fence.claim = claim
    report = h.run()
    assert report.claimed
    assert report.preflight["assessed_utc"] == claimed_utc[0]
    persisted = json.loads((h.bundle_dir / "raw" / "preflight.json").read_text())
    assert persisted["assessed_utc"] == claimed_utc[0]
