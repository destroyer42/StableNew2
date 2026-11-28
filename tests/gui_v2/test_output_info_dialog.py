"""NAME-INFO: the desktop "More info" window shows one column per image, read off the Tk thread."""

from __future__ import annotations

import tkinter as tk

import pytest
from PIL import Image

from src.gui import output_info_dialog
from src.review.output_info import info_rows
from src.utils.image_metadata import build_contract_kv, write_image_metadata

CHECKPOINT = "photoMomentumSDXLNSFW_v20"


class Now:
    """The background runner, run at once."""

    def submit(self, _key, work, *, on_result, on_error, **_names):
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - the dialog's own error path
            on_error(error)
            return
        on_result(result)

    def close(self):
        pass


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    window.withdraw()
    yield window
    window.destroy()


def image(path, stage="txt2img"):
    Image.new("RGB", (16, 16)).save(path)
    payload = {"stage": stage, "generation": {"model": CHECKPOINT}, "seeds": {"final_seed": 7}}
    assert write_image_metadata(
        path, build_contract_kv(payload, job_id="j", run_id="r", stage=stage)
    )
    return path


def test_rows_are_labelled_and_leave_out_what_is_unknown():
    rows = dict(
        info_rows(
            {
                "stage_path": "clip (A14B) from photoMomentum",
                "model": "A14B",
                "model_name": "wan22_i2v_a14b_4step_v1 1.0.0",
                "prompt_number": 3,
                "variant": 2,
            }
        )
    )
    assert rows == {
        "Path": "clip (A14B) from photoMomentum",
        "Model": "A14B (wan22_i2v_a14b_4step_v1 1.0.0)",
        "Prompt": "prompt 3, variant 2",
    }


def test_both_sides_are_shown_in_their_own_column(root, tmp_path, monkeypatch):
    monkeypatch.setattr(output_info_dialog, "build_edit_work_runner", lambda _widget: Now())
    original = image(tmp_path / "before.png")
    fixed = image(tmp_path / "after.png", stage="adetailer")

    dialog = output_info_dialog.OutputInfoDialog(root, (("Source", original), ("Returned", fixed)))

    shown = {
        values[0]: values[1:]
        for values in (dialog.tree.item(row, "values") for row in dialog.tree.get_children())
    }
    assert [str(dialog.tree.heading(column, "text")) for column in ("side0", "side1")] == [
        "Source",
        "Returned",
    ]
    assert tuple(shown["Path"]) == ("txt2img", "ADetailer")
    assert tuple(shown["Model"])[0] == f"photoMomentum ({CHECKPOINT})"
    assert tuple(shown["File"]) == ("before.png", "after.png")
    assert str(tmp_path) not in str(shown)
    dialog.destroy()
