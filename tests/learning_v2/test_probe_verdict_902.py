"""MEC-902: advisory probe verdicts and the explicit, never-overwriting classification sidecar."""

import json

import pytest

from src.assets.compatibility import ModelFamily, _normalize_token
from src.learning.probe_verdict import (
    LINEAGES,
    RUNS_ARTIFACTS,
    RUNS_NO,
    RUNS_YES,
    ProbeVerdict,
    VerdictStore,
    classification_sidecar,
    write_classification,
)

SHA = "c" * 64


def verdict(**kw):
    return ProbeVerdict(**{"sha256": SHA, "model": "m.safetensors", "runs": RUNS_YES, **kw})


def test_store_round_trips_and_latest_replaces(tmp_path):
    store = VerdictStore(tmp_path / "verdicts")
    assert store.load(SHA) is None and store.load_all() == {}
    saved = store.save(verdict(lineage="sd15", best_recipe="SD 1.5", notes="clean faces"))
    assert saved.recorded_at and store.load(SHA) == saved
    store.save(verdict(runs=RUNS_ARTIFACTS, lineage="pony"))
    assert store.load(SHA).lineage == "pony" and list(store.load_all()) == [SHA]
    (tmp_path / "verdicts" / f"{'d' * 64}.json").write_text("{broken", encoding="utf-8")
    assert list(store.load_all()) == [SHA]  # an unreadable verdict is ignored, not fatal


def test_invalid_verdicts_are_refused(tmp_path):
    store = VerdictStore(tmp_path)
    for bad in (verdict(sha256="x"), verdict(runs="maybe"), verdict(lineage="sd99")):
        with pytest.raises(ValueError):
            store.save(bad)


@pytest.mark.parametrize(
    ("lineage", "family"),
    [
        ("sd15", ModelFamily.SD1),
        ("sd2", ModelFamily.SD2),
        ("sdxl", ModelFamily.SDXL),
        ("pony", ModelFamily.SDXL),
        ("illustrious", ModelFamily.SDXL),
        ("sdxl_turbo", ModelFamily.SDXL),
        ("sdxl_lightning", ModelFamily.SDXL),
        ("flux", ModelFamily.FLUX),
    ],
)
def test_each_base_model_label_maps_to_its_family_through_existing_evidence(lineage, family):
    assert _normalize_token(LINEAGES[lineage][1]) == family


def test_classification_sidecar_is_created_only_when_absent(tmp_path):
    model = tmp_path / "m.safetensors"
    model.write_bytes(b"x")
    path, document = classification_sidecar(model, verdict(lineage="sd15", probe_ids=("probe-1",)))
    assert path == tmp_path / "m.civitai.info"
    assert document["baseModel"] == "SD 1.5"
    provenance = document["stablenew_operator_classification"]
    assert provenance["sha256"] == SHA and provenance["probe_ids"] == ["probe-1"]
    assert "operator's explicit request" in provenance["note"]
    write_classification(path, document)
    assert json.loads(path.read_text(encoding="utf-8"))["baseModel"] == "SD 1.5"
    with pytest.raises(ValueError, match="never overwrites"):
        classification_sidecar(model, verdict(lineage="sdxl"))
    with pytest.raises(FileExistsError):
        write_classification(path, {"baseModel": "SDXL 1.0"})
    assert json.loads(path.read_text(encoding="utf-8"))["baseModel"] == "SD 1.5"


def test_an_existing_civitai_sidecar_under_either_name_blocks_classification(tmp_path):
    model = tmp_path / "m.safetensors"
    model.write_bytes(b"x")
    (tmp_path / "m.safetensors.civitai.info").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        classification_sidecar(model, verdict(lineage="sdxl"))


def test_unknown_lineage_or_not_working_is_never_classified(tmp_path):
    model = tmp_path / "m.safetensors"
    with pytest.raises(ValueError, match="lineage"):
        classification_sidecar(model, verdict())
    with pytest.raises(ValueError, match="does not work"):
        classification_sidecar(model, verdict(runs=RUNS_NO, lineage="sdxl"))
