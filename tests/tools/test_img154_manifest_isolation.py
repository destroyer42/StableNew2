"""PR-IMG-MODELS-154A T01-T06: frozen manifest, served-file proof, isolation, port/ownership and pin/intent blocks.

Synthetic data and fakes only: no model is read, hashed, linked, copied or loaded and no process is touched.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from tools.qualification.img153 import feasibility as img153
from tools.qualification.img154 import isolation as iso
from tools.qualification.img154 import manifest as mf

ROOT = "C:/qual/zimage"
RESERVED = {
    "repository": "C:/Users/someone/projects/StableNew",
    "managed_forge_install": "C:/Users/someone/AppData/Local/StableNew/Forge/neo-d70373eb",
    "model_library": "C:/Users/someone/stable-diffusion-webui",
}


class FakeFs:
    """A dict-backed ``FsFacts``: ``entries`` maps a path to ``(kind, size)``; ``links`` maps a path to a resolved target."""

    def __init__(self, entries=None, links=None, volumes=None, absolute=True):
        self.entries = {k.replace("\\", "/").lower(): v for k, v in (entries or {}).items()}
        self.links = {k.replace("\\", "/").lower(): v for k, v in (links or {}).items()}
        self.volumes = volumes or {}
        self.absolute = absolute

    @staticmethod
    def _k(path):
        return str(path).replace("\\", "/").lower()

    def resolve(self, path):
        key = self._k(path)
        for link, target in self.links.items():
            if key == link or key.startswith(link + "/"):
                return target + key[len(link) :]
        return str(path)

    def is_absolute(self, path):
        return self.absolute

    def is_reparse_point(self, path):
        return self._k(path) in self.links

    def exists(self, path):
        key = self._k(path)
        return key in self.entries or key in self.links

    def is_file(self, path):
        return self.entries.get(self._k(path), ("none", 0))[0] == "file"

    def size(self, path):
        entry = self.entries.get(self._k(path))
        return entry[1] if entry else None

    def volume(self, path):
        key = self._k(path)
        for prefix, volume in self.volumes.items():
            if key.startswith(prefix.lower()):
                return volume
        return "c:"


def codes(findings):
    return {item.code for item in findings}


def exact(
    role: str, *, name=None, size=None, sha=None, path=None, hashed=True
) -> mf.FileMeasurement:
    spec = mf.FROZEN_ASSETS[role]
    return mf.FileMeasurement(
        name or spec.filename,
        spec.size_bytes if size is None else size,
        (spec.sha256 if sha is None else sha) if hashed else None,
        path,
    )


def all_exact(**overrides):
    measured = {role: exact(role) for role in mf.FROZEN_ASSETS}
    measured.update(overrides)
    return measured


# --- T01 ---------------------------------------------------------------------------------------------------------------


def test_t01_manifest_facts_are_exact_and_independent_of_the_git_commit():
    plan = mf.build_manifest()
    assert plan.forge_pin == "d70373ebcf1a96d210b78cd6f77196459e783e2a"
    assert plan.assets["transformer"].size_bytes == 6_158_115_074
    assert plan.assets["transformer"].sha256 == (
        "59610861d46ae8d5d1d371ab7b2532ce64c0835052b395551a8550fa0e3eb3cf"
    )
    assert plan.assets["text_encoder"].sha256 == (
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a"
    )
    assert plan.assets["vae"].sha256 == (
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"
    )
    # identical digests on repeated builds: nothing reads the repository, the host or the clock
    assert mf.build_manifest().digest() == plan.digest()
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(ast.parse(Path(mf.__file__).read_text(encoding="utf-8")))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    # no process, filesystem, clock or environment access can influence the facts
    assert imported <= {
        "__future__",
        "posixpath",
        "collections.abc",
        "dataclasses",
        "typing",
        "core",
    }


def test_t01_manifest_filenames_and_pin_match_the_accepted_pr153_evidence():
    plan = mf.build_manifest()
    assert plan.assets["transformer"].filename == img153.TRANSFORMER_NAME
    assert plan.assets["text_encoder"].filename == img153.ENCODER_NAME
    assert plan.assets["vae"].filename == img153.VAE_NAME
    assert plan.forge_pin == img153.PINNED_REVISION
    assert plan.assets["text_encoder"].sha256 == img153.IMG115_ENCODER_SHA256


def test_t01_manifest_is_a_proposal_and_marks_unreconciled_intent_fields():
    data = mf.build_manifest().as_dict()
    assert data["status"] == "PROPOSED_NOT_APPLIED"
    assert set(data["unreconciled_intent_fields"]) == {"cfg_scale", "shift", "scheduler"}
    assert data["intent"]["width"] == data["intent"]["height"] == 1024
    assert data["intent"]["batch_size"] == data["intent"]["n_iter"] == 1
    assert all(
        asset["provenance"] == "unverified_third_party_candidate"
        for asset in data["assets"].values()
    )
    assert data["served_relative_paths"]["vae"] == "forge-data/models/VAE/flux1AE_v10.safetensors"


# --- T02 ---------------------------------------------------------------------------------------------------------------


def test_t02_exact_assets_pass():
    assert mf.verify_assets(all_exact()) == []


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"transformer": exact("transformer", size=1)}, "ASSET_SIZE_MISMATCH"),
        ({"transformer": exact("transformer", sha="0" * 64)}, "ASSET_SHA256_MISMATCH"),
        ({"vae": exact("vae", name="flux2-vae.safetensors")}, "ASSET_NAME_MISMATCH"),
        ({"text_encoder": None}, "ASSET_MISSING"),
        ({"vae": exact("vae", sha="XYZ")}, "ASSET_DIGEST_MALFORMED"),
        ({"vae": exact("vae", hashed=False)}, "ASSET_NOT_HASHED"),
    ],
)
def test_t02_size_sha_name_and_missing_fail_closed(override, code):
    assert code in codes(mf.verify_assets(all_exact(**override)))


def test_t02_wrong_role_and_collision_fail_closed():
    swapped = all_exact(
        transformer=exact("text_encoder", name=mf.FROZEN_ASSETS["transformer"].filename)
    )
    assert codes(mf.verify_assets(swapped)) & {"ASSET_SIZE_MISMATCH", "ASSET_SHA256_MISMATCH"}
    # one set of bytes standing in for two roles
    spec = mf.FROZEN_ASSETS["vae"]
    twin = mf.AssetSpec(
        "text_encoder", "qwen3_4b_2964436.safetensors", spec.size_bytes, spec.sha256, "text_encoder"
    )
    plan = dataclasses.replace(
        mf.build_manifest(), assets={**mf.FROZEN_ASSETS, "text_encoder": twin}
    )
    measured = {
        "transformer": exact("transformer"),
        "text_encoder": mf.FileMeasurement(twin.filename, twin.size_bytes, twin.sha256),
        "vae": exact("vae"),
    }
    assert "ASSET_ROLE_COLLISION" in codes(mf.verify_assets(measured, plan))
    assert "ASSET_ROLE_UNEXPECTED" in codes(mf.verify_assets({**all_exact(), "lora": exact("vae")}))


# --- T03 ---------------------------------------------------------------------------------------------------------------


def served(models_root="C:/qual/zimage/forge-data/models", **overrides):
    items = {}
    for role, spec in mf.FROZEN_ASSETS.items():
        items[role] = exact(role, path=f"{models_root}/{spec.models_subdir}/{spec.filename}")
    items.update(overrides)
    return items


def test_t03_served_files_pass_only_with_their_own_measurement_at_the_expected_path():
    root = "C:/qual/zimage/forge-data/models"
    assert mf.verify_served_files(served(), models_root=root) == []


def test_t03_a_matching_source_never_stands_in_for_the_served_file():
    root = "C:/qual/zimage/forge-data/models"
    # the SOURCE measures exactly...
    assert mf.verify_assets(all_exact()) == []
    # ...but the served file was never hashed, has other bytes, or is a same-name file somewhere else
    unhashed = served(vae=exact("vae", hashed=False, path=f"{root}/VAE/flux1AE_v10.safetensors"))
    assert "ASSET_NOT_HASHED" in codes(mf.verify_served_files(unhashed, models_root=root))
    other_bytes = served(vae=exact("vae", sha="1" * 64, path=f"{root}/VAE/flux1AE_v10.safetensors"))
    assert "ASSET_SHA256_MISMATCH" in codes(mf.verify_served_files(other_bytes, models_root=root))
    elsewhere = served(vae=exact("vae", path="C:/other/place/flux1AE_v10.safetensors"))
    assert "SERVED_PATH_MISMATCH" in codes(mf.verify_served_files(elsewhere, models_root=root))
    absent = {role: item for role, item in served().items() if role != "vae"}
    assert "ASSET_MISSING" in codes(mf.verify_served_files(absent, models_root=root))


# --- T04 ---------------------------------------------------------------------------------------------------------------


def test_t04_a_clean_isolated_root_is_accepted():
    assert iso.validate_isolation(ROOT, RESERVED, FakeFs()) == []


def test_t04_overlap_is_refused_in_both_directions():
    inside = iso.validate_isolation("C:/Users/someone/projects/StableNew/qual", RESERVED, FakeFs())
    assert "ISOLATION_INSIDE_RESERVED" in codes(inside)
    equal = iso.validate_isolation(RESERVED["model_library"], RESERVED, FakeFs())
    assert "ISOLATION_INSIDE_RESERVED" in codes(equal)
    contains = iso.validate_isolation("C:/Users/someone", RESERVED, FakeFs())
    assert "ISOLATION_CONTAINS_RESERVED" in codes(contains)
    # case differences cannot hide an overlap
    shouty = iso.validate_isolation("c:/USERS/SOMEONE/PROJECTS/stablenew/x", RESERVED, FakeFs())
    assert "ISOLATION_INSIDE_RESERVED" in codes(shouty)


def test_t04_an_incomplete_reserved_set_cannot_certify_isolation():
    only_repo = {"repository": RESERVED["repository"]}
    found = iso.validate_isolation(ROOT, only_repo, FakeFs())
    assert [(f.code, f.severity) for f in found] == [
        ("ISOLATION_RESERVED_SET_INCOMPLETE", "inconclusive")
    ]
    assert "managed_forge_install" in found[0].detail
    assert set(iso.REQUIRED_RESERVED_LABELS) == {
        "repository",
        "managed_forge_install",
        "model_library",
    }


def test_t04_drive_root_relative_and_marker_roots_are_refused():
    assert "ISOLATION_ROOT_COLLISION" in codes(iso.validate_isolation("C:/", RESERVED, FakeFs()))
    assert "ISOLATION_ROOT_NOT_ABSOLUTE" in codes(
        iso.validate_isolation("zimage", RESERVED, FakeFs(absolute=False))
    )
    marker = iso.validate_isolation("C:/data/.venv/zimage", RESERVED, FakeFs())
    assert "ISOLATION_RESERVED_MARKER" in codes(marker)


def test_t04_junction_symlink_escape_into_a_reserved_tree_is_refused():
    fs = FakeFs(
        entries={"C:/qual": ("dir", 0)},
        links={"C:/qual/zimage": "c:/users/someone/stable-diffusion-webui/models"},
    )
    found = codes(iso.validate_isolation(ROOT, RESERVED, fs))
    assert "ISOLATION_REPARSE_ESCAPE" in found
    assert "ISOLATION_INSIDE_RESERVED" in found  # the resolved target is inside the A1111 tree


def test_t04_linked_layout_directory_is_refused():
    models = "C:/qual/zimage/forge-data/models"
    fs = FakeFs(entries={models: ("dir", 0)}, links={models: "D:/elsewhere"})
    assert "ISOLATION_LAYOUT_REPARSE" in codes(iso.validate_isolation(ROOT, RESERVED, fs))


def test_t04_cross_volume_sources_cannot_assume_a_hardlink():
    fs = FakeFs(volumes={"d:/downloads": "d:", "c:/qual": "c:"})
    sources = {"vae": "D:/downloads/flux1AE_v10.safetensors"}
    assert "ISOLATION_CROSS_VOLUME_HARDLINK" in codes(
        iso.validate_isolation(ROOT, RESERVED, fs, source_paths=sources)
    )
    same = {"vae": "C:/qual/zimage/assets/flux1AE_v10.safetensors"}
    assert iso.validate_isolation(ROOT, RESERVED, fs, source_paths=same) == []


def test_t04_preexisting_targets_must_be_plain_files_of_the_frozen_size():
    spec = mf.FROZEN_ASSETS["vae"]
    target = f"C:/qual/zimage/forge-data/models/VAE/{spec.filename}"
    bad_size = FakeFs(entries={target: ("file", spec.size_bytes + 1)})
    assert "ISOLATION_TARGET_SIZE_MISMATCH" in codes(
        iso.validate_isolation(ROOT, RESERVED, bad_size)
    )
    folder = FakeFs(entries={target: ("dir", 0)})
    assert "ISOLATION_TARGET_NOT_PLAIN_FILE" in codes(
        iso.validate_isolation(ROOT, RESERVED, folder)
    )
    right = FakeFs(entries={target: ("file", spec.size_bytes)})
    found = iso.validate_isolation(ROOT, RESERVED, right)
    assert [item.code for item in found] == ["ISOLATION_TARGET_EXISTS_UNVERIFIED"]
    assert found[0].severity == "inconclusive"  # a size match is never identity


def test_t04_real_filesystem_ancestry_and_creates_nothing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    reserved = {"repository": str(repo)}
    inside = iso.validate_isolation(
        str(repo / "qual"), reserved, iso.RealFs(), required_reserved=()
    )
    assert "ISOLATION_INSIDE_RESERVED" in codes(inside)
    contains = iso.validate_isolation(str(tmp_path), reserved, iso.RealFs(), required_reserved=())
    assert "ISOLATION_CONTAINS_RESERVED" in codes(contains)
    outside = tmp_path.parent / "img154-qual-root-not-created"
    assert iso.validate_isolation(str(outside), reserved, iso.RealFs(), required_reserved=()) == []
    assert not outside.exists()  # validation never creates the root


def test_t04_real_symlink_escape_is_refused(tmp_path):
    target = tmp_path / "library"
    target.mkdir()
    link = tmp_path / "qualroot"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this host")
    found = iso.validate_isolation(
        str(link), {"library": str(target)}, iso.RealFs(), required_reserved=()
    )
    assert "ISOLATION_REPARSE_ESCAPE" in codes(found)
    assert "ISOLATION_INSIDE_RESERVED" in codes(found)


# --- T05 ---------------------------------------------------------------------------------------------------------------


def test_t05_free_loopback_port_passes_and_everything_else_does_not():
    ok = iso.PortObservation("127.0.0.1", iso.QUALIFICATION_PORT, "free")
    assert iso.validate_endpoint(ok) == []
    assert "RUNTIME_PORT_OCCUPIED" in codes(
        iso.validate_endpoint(iso.PortObservation("127.0.0.1", iso.QUALIFICATION_PORT, "occupied"))
    )
    unverifiable = iso.validate_endpoint(
        iso.PortObservation("127.0.0.1", iso.QUALIFICATION_PORT, "unverifiable")
    )
    assert [(f.code, f.severity) for f in unverifiable] == [
        ("RUNTIME_PORT_UNVERIFIED", "inconclusive")
    ]
    assert "PORT_NOT_LOOPBACK" in codes(
        iso.validate_endpoint(iso.PortObservation("0.0.0.0", iso.QUALIFICATION_PORT, "free"))
    )
    assert "PORT_RESERVED" in codes(
        iso.validate_endpoint(iso.PortObservation("127.0.0.1", 7871, "free"), expected_port=7871)
    )
    assert "PORT_NOT_FROZEN" in codes(
        iso.validate_endpoint(iso.PortObservation("127.0.0.1", 9000, "free"))
    )
    assert "PORT_NOT_OBSERVED" in codes(iso.validate_endpoint(None))


def test_t05_foreign_or_unowned_runtimes_refuse_and_nothing_is_acted_on():
    forge = iso.ProcessObservation(
        4242, "python.exe", ("python", "launch.py", "--api", "--port", "7871"), (7871,), "external"
    )
    owned_looking = iso.ProcessObservation(
        4243, "python.exe", ("forge-launcher",), (), "stablenew_manager"
    )
    benign = iso.ProcessObservation(7, "python.exe", ("python", "-m", "pytest"), (), "unknown")
    found = iso.validate_process_conflicts([forge, owned_looking, benign])
    assert "RUNTIME_CONFLICT_FOREIGN_OWNER" in codes(found)
    assert "RUNTIME_CONFLICT_PRESENT" in codes(found)
    assert all(
        "7" != item.detail.split()[1] for item in found
    )  # the benign process is not reported
    listener = iso.ProcessObservation(
        9, "node.exe", ("node",), (iso.QUALIFICATION_PORT,), "unknown"
    )
    assert "RUNTIME_PORT_LISTENER" in codes(iso.validate_process_conflicts([listener]))
    assert iso.validate_process_conflicts([benign]) == []
    unavailable = iso.validate_process_conflicts(None)
    assert [(f.code, f.severity) for f in unavailable] == [
        ("PROCESS_LIST_UNAVAILABLE", "inconclusive")
    ]


def test_t05_ownership_plan_grants_no_control_to_this_package():
    plan = iso.OwnershipPlan()
    assert plan.observer_may_control_process is False
    assert plan.external_runtime_adoption is False
    assert plan.termination_performed_by_this_package is False
    assert plan.sole_owner_required is True


# --- T06 ---------------------------------------------------------------------------------------------------------------


def test_t06_pin_and_marker_mismatch_block():
    pin = mf.FORGE_PIN
    assert mf.verify_runtime_pin(pin, "verified", pin) == []
    assert "PIN_CONFIG_MISMATCH" in codes(mf.verify_runtime_pin(pin, "verified", "f" * 40))
    assert "PIN_MARKER_MISMATCH" in codes(mf.verify_runtime_pin("f" * 40, "verified", pin))
    assert "PIN_MARKER_MISMATCH" in codes(mf.verify_runtime_pin(pin, "drifted", pin))
    unknown = mf.verify_runtime_pin(None, None, pin)
    assert [(f.code, f.severity) for f in unknown] == [("PIN_MARKER_UNKNOWN", "inconclusive")]


def test_t06_altered_added_or_forbidden_intent_blocks():
    plan = mf.build_manifest()
    fields = plan.intent.request_fields()
    assert mf.verify_intent(fields) == []
    assert "INTENT_DRIFT" in codes(mf.verify_intent({**fields, "steps": 20}))
    assert "INTENT_DRIFT" in codes(mf.verify_intent({**fields, "seed": fields["seed"] + 1}))
    forbidden = mf.verify_intent({**fields, "enable_hr": True})
    assert {"INTENT_FORBIDDEN_FIELD", "INTENT_DRIFT"} <= codes(forbidden)
    assert "INTENT_NOT_PRESENTED" in codes(mf.verify_intent(None))
    assert "INTENT_NOT_CANONICAL" in codes(mf.verify_intent({**fields, "cfg_scale": float("nan")}))
