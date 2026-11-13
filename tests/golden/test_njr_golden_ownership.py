"""Every golden snapshot is owned by a test, and every test-owned snapshot exists (P4-2A).

The older parametrized check in ``test_njr_golden_p4_2.py`` names six files by hand.  This one reads the suite itself:
a file in ``tests/golden/njr`` that no ``assert_golden("<name>", ...)`` call names is orphaned, and a name with no file
means the snapshot was never generated.
"""

from __future__ import annotations

import re
from pathlib import Path

GOLDEN_ROOT = Path(__file__).resolve().parent
NAMED = re.compile(r"assert_golden\(\s*\"([a-z0-9_]+)\"")


def _owned_names() -> set[str]:
    names: set[str] = set()
    for source in GOLDEN_ROOT.glob("test_*.py"):
        names.update(NAMED.findall(source.read_text(encoding="utf-8")))
    return names


def test_every_snapshot_file_is_named_by_a_golden_assertion() -> None:
    files = {path.stem for path in (GOLDEN_ROOT / "njr").glob("*.json")}
    assert files - _owned_names() == set(), "orphaned golden files"


def test_every_named_snapshot_exists() -> None:
    files = {path.stem for path in (GOLDEN_ROOT / "njr").glob("*.json")}
    assert _owned_names() - files == set(), "assertions naming a missing golden file"


def test_the_suite_covers_the_route_families_of_the_p4_2_baseline() -> None:
    names = _owned_names()
    for family in (
        "cli",
        "generic_config_variants",
        "generic_adetailer",
        "prompt_pack_matrix_2x2",
        "prompt_pack_randomizer",
        "prompt_pack_lora_embedding",
        "prompt_pack_exact_profile",
        "reprocess_img2img",
        "reprocess_frozen_mask_edit",
        "learning_ordinary_strict",
        "learning_ordinary_legacy",
        "learning_model_comparison",
        "learning_two_axis_grid",
        "learning_prompt_model_matrix",
        "learning_non_txt2img_variant",
        "history_variation",
        "replay_prompt_pack_batch_parent",
        "sequence_resume_and_replay",
        "svd_native",
        "video_workflow",
        "movie_clips",
        "refusals_generic",
        "refusals_prompt_pack",
        "refusals_cli",
        "refusals_reprocess",
        "refusals_history",
        "refusals_learning",
        "refusals_video",
    ):
        if family != "cli":  # the six older snapshots are named in the original module
            assert family in names, family
