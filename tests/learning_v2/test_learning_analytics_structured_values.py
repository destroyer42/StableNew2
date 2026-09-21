"""LearningAnalytics must summarize structured (composite) controlled variant values."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from src.learning.learning_analytics import LearningAnalytics
from src.learning.learning_record import LearningRecordWriter
from src.learning.value_identity import readable_value

LORA = "add-detail-xl"
EXP = "lora-exp"


def _lora(weight: float, name: str = LORA) -> dict[str, Any]:
    return {"name": name, "weight": weight}


def _rec(value: Any, rating: int, *, variable: str = "LoRA Strength", exp: str = EXP) -> dict:
    return {
        "metadata": {
            "experiment_name": exp,
            "variable_under_test": variable,
            "variant_value": value,
            "user_rating": rating,
        }
    }


def _analytics(tmp_path: Path, records: list[dict]) -> LearningAnalytics:
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return LearningAnalytics(LearningRecordWriter(str(path)))


def test_structured_lora_experiment_summarizes_with_semantic_values(tmp_path: Path) -> None:
    summary = _analytics(
        tmp_path, [_rec(_lora(0.0), 3), _rec(_lora(1.0), 4), _rec(_lora(2.0), 5)]
    ).get_experiment_summary(EXP)
    assert summary is not None
    assert (summary.total_variants, summary.total_ratings) == (3, 3)
    assert summary.parameter_name == "LoRA Strength"
    assert summary.best_value == _lora(2.0) and type(summary.best_value) is dict
    assert summary.worst_value == _lora(0.0)
    assert (summary.best_rating, summary.worst_rating) == (5.0, 3.0)


def test_mapping_insertion_order_is_one_variant(tmp_path: Path) -> None:
    reordered = {"weight": 1.0, "name": LORA}
    summary = _analytics(
        tmp_path, [_rec(_lora(1.0), 4), _rec(reordered, 2)]
    ).get_experiment_summary(EXP)
    assert summary.total_variants == 1 and summary.total_ratings == 2
    assert summary.best_rating == 3.0


def test_same_weight_under_different_loras_stays_separate(tmp_path: Path) -> None:
    summary = _analytics(
        tmp_path, [_rec(_lora(1.0, "lora-a"), 5), _rec(_lora(1.0, "lora-b"), 1)]
    ).get_experiment_summary(EXP)
    assert summary.total_variants == 2
    assert summary.best_value == _lora(1.0, "lora-a") and summary.worst_value == _lora(
        1.0, "lora-b"
    )


def test_scalar_values_behave_as_before(tmp_path: Path) -> None:
    summary = _analytics(
        tmp_path,
        [
            _rec(5.0, 2, variable="CFG Scale"),
            _rec(7.0, 5, variable="CFG Scale"),
            _rec(7.0, 4, variable="CFG Scale"),
        ],
    ).get_experiment_summary(EXP)
    assert (summary.total_variants, summary.total_ratings) == (2, 3)
    assert (summary.best_value, summary.best_rating) == (7.0, 4.5)
    assert (summary.worst_value, summary.worst_rating) == (5.0, 2.0)
    text = _analytics(
        tmp_path, [_rec("Euler a", 3, variable="Sampler"), _rec("DDIM", 5, variable="Sampler")]
    )
    assert text.get_experiment_summary(EXP).best_value == "DDIM"


def test_unsupported_historical_value_is_skipped_not_fatal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    analytics = _analytics(tmp_path, [_rec(_lora(1.0), 4), _rec(_lora(2.0), 5)])
    original = analytics._read_all_records
    poisoned = original() + [_rec({"weight": {1, 2}}, 1)]  # not JSON-like
    analytics._read_all_records = lambda: poisoned  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        summary = analytics.get_experiment_summary(EXP)
    assert (summary.total_variants, summary.total_ratings) == (2, 2)
    assert "unsupported variant value" in caplog.text


def test_overall_summary_and_exports_handle_structured_values(tmp_path: Path) -> None:
    analytics = _analytics(
        tmp_path, [_rec(_lora(0.0), 3), _rec(_lora(1.0), 4), _rec(_lora(2.0), 5)]
    )
    overall = analytics.get_overall_summary()
    assert overall.total_experiments == 1 and overall.total_ratings == 3
    assert overall.experiments[0].best_value == _lora(2.0)

    json_path, csv_path = tmp_path / "out.json", tmp_path / "out.csv"
    analytics.export_to_json(json_path)
    analytics.export_to_csv(csv_path)
    exported = json.loads(json_path.read_text(encoding="utf-8"))["experiments"][0]
    assert exported["best_value"] == _lora(2.0) and exported["worst_value"] == _lora(0.0)
    rows = list(csv.reader(csv_path.open(encoding="utf-8", newline="")))
    assert rows[1][4] == f"{LORA} @ 2.0" and rows[1][6] == f"{LORA} @ 0.0"


def test_readable_value_is_presentation_only() -> None:
    assert readable_value(7.5) == 7.5 and readable_value("Euler a") == "Euler a"
    assert readable_value(_lora(2.0)) == "add-detail-xl @ 2.0"
    assert readable_value({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'
