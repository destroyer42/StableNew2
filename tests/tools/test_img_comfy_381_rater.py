"""IMG-COMFY-381: the blind A/B rating page written from a harness review directory (no browser, no GPU)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from tools.acceptance import img_comfy_381_rater as rater

COLUMNS = (
    "pair_id", "workload", "prompt_id", "seed", "image_a", "image_b",
    "fidelity_a", "fidelity_b", "detail_a", "detail_b", "artifacts_a", "artifacts_b", "preference_a_b_tie", "notes",
)  # fmt: skip


def _review(tmp_path: Path, pairs: int = 2, prompt: str = "a red </script> cat & <!-- dog") -> Path:
    run = tmp_path / "run"
    review = run / "review"
    (review / "images").mkdir(parents=True)
    rows, plan_pairs = [], []
    for n in range(pairs):
        pair_id = f"S1-p{n}-s42"
        for label, shade in (("A", 10 + n), ("B", 200 - n)):
            Image.new("RGB", (8, 8), (shade, shade, shade)).save(
                review / "images" / f"{pair_id}_{label}.png"
            )
        rows.append(
            {
                "pair_id": pair_id, "workload": "S1", "prompt_id": str(n), "seed": "42",
                "image_a": f"images\\{pair_id}_A.png", "image_b": f"images\\{pair_id}_B.png",
            }
        )  # fmt: skip
        plan_pairs.append({"pair_id": pair_id, "prompt": prompt})
    with (review / "review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (run / "plan.json").write_text(json.dumps({"pairs": plan_pairs}), encoding="utf-8")
    (run / "review_key.json").write_text(
        json.dumps({"pairs": {"S1-p0-s42": {"A": "forge_webui", "B": "comfyui"}}}), encoding="utf-8"
    )
    return review


def _data(page: str) -> dict:
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S)
    assert match
    return json.loads(match.group(1))


def test_the_page_carries_every_pair_the_columns_and_the_shared_prompt(tmp_path: Path) -> None:
    review = _review(tmp_path)

    target = rater.write_rater(review)
    data = _data(target.read_text(encoding="utf-8"))

    assert target == review / "rater.html"
    assert data["header"] == list(COLUMNS)
    assert [row["pair_id"] for row in data["rows"]] == ["S1-p0-s42", "S1-p1-s42"]
    assert data["prompts"]["S1-p0-s42"].startswith(
        "a red </script> cat"
    )  # survives the JSON round trip intact
    assert data["preferences"] == ["A", "B", "tie"]


def test_hostile_text_cannot_close_the_script_block_or_open_a_comment(tmp_path: Path) -> None:
    page = rater.write_rater(_review(tmp_path)).read_text(encoding="utf-8")
    block = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S)

    assert block is not None
    assert "<" not in block.group(1)
    assert page.count("</script>") == 2  # the data block and the page script, nothing smuggled in


def test_the_page_never_names_a_backend_or_reads_the_key(tmp_path: Path) -> None:
    page = rater.write_rater(_review(tmp_path)).read_text(encoding="utf-8").lower()

    for word in ("forge", "comfy", "review_key", "backend"):
        assert word not in page.replace("img-comfy-381-rater", "")


def test_the_page_loads_nothing_from_elsewhere(tmp_path: Path) -> None:
    page = rater.write_rater(_review(tmp_path)).read_text(encoding="utf-8")

    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", page)
    assert "fetch(" not in page and "XMLHttpRequest" not in page


def test_it_refuses_to_replace_a_page_unless_told_to(tmp_path: Path) -> None:
    review = _review(tmp_path)
    rater.write_rater(review)

    with pytest.raises(rater.RaterError, match="already exists"):
        rater.write_rater(review)
    assert rater.write_rater(review, overwrite=True).is_file()


def test_a_missing_image_or_csv_is_refused(tmp_path: Path) -> None:
    review = _review(tmp_path)
    (review / "images" / "S1-p1-s42_B.png").unlink()
    with pytest.raises(rater.RaterError, match="missing"):
        rater.write_rater(review)
    with pytest.raises(rater.RaterError, match="review.csv"):
        rater.write_rater(tmp_path / "nowhere")


def test_the_storage_key_follows_the_images_not_just_the_pair_ids(tmp_path: Path) -> None:
    first = _data(rater.write_rater(_review(tmp_path / "one")).read_text(encoding="utf-8"))
    review_two = _review(tmp_path / "two")
    Image.new("RGB", (8, 8), (77, 1, 1)).save(review_two / "images" / "S1-p0-s42_A.png")
    second = _data(rater.write_rater(review_two).read_text(encoding="utf-8"))

    assert first["storage_key"] != second["storage_key"]


def test_the_cli_writes_the_page_and_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    review = _review(tmp_path)

    assert rater.main([str(review)]) == 0
    assert str(review / "rater.html") in capsys.readouterr().out
    assert rater.main([str(review)]) == 2
    assert "already exists" in capsys.readouterr().err
