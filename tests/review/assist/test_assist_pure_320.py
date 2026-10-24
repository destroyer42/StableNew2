"""Smart Review pure contracts: pointer geometry, mask polarity and validation, caption hygiene, key accounting."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from src.conditioning.reference_map.contracts import ReferenceMapError
from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui_v2.mask_editor_state import MaskViewport
from src.review.assist import loading
from src.review.assist.captions import (
    CaptionApplication,
    build_caption_proposal,
    compose_draft,
    present_caption,
    sanitize_text,
)
from src.review.assist.contracts import (
    CODE_OUTPUT,
    CODE_PROMPT,
    MAX_BOXES,
    MAX_CAPTION_CHARS,
    MAX_MASK_BYTES,
    MAX_OBJECTS,
    MAX_POINTS,
    AssistError,
    BoxPrompt,
    CaptionOutput,
    ModelIdentity,
    PointPrompt,
    RawObject,
    SourceIdentity,
)
from src.review.assist.geometry import (
    box_from_drag,
    canvas_to_image,
    compose_overlay,
    image_to_canvas,
    point_at,
    validate_prompts,
)
from src.review.assist.masks import logits_to_mask_png, mask_image, validate_mask_png


def identity(width: int = 200, height: int = 120) -> SourceIdentity:
    return SourceIdentity("a" * 64, 1, width, height, 1, "PNG")


MODEL = ModelIdentity("florence2", "florence-2-base-ft", "local child process, CPU")


# -- pointer geometry -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "viewport",
    [
        MaskViewport(1.0, 0, 0),
        MaskViewport(2.5, 13.5, -7.25),  # zoomed, panned, non-integer scale
        MaskViewport(0.37, 41.2, 90.9),  # letterboxed fit on a small canvas
    ],
)
def test_every_pixel_centre_round_trips_through_canvas_space(viewport):
    size = (50, 31)  # rectangular, so a swapped axis would be caught
    for x, y in [(0, 0), (49, 0), (0, 30), (49, 30), (17, 23)]:
        cx, cy = image_to_canvas(viewport, x, y)
        assert canvas_to_image(viewport, cx, cy, size) == (x, y)


def test_pointer_outside_the_image_is_refused_not_clamped():
    viewport = MaskViewport(2, 10, 10)
    assert canvas_to_image(viewport, 9.9, 50, (100, 100)) is None  # letterbox margin
    assert (
        canvas_to_image(viewport, 10 + 200, 50, (100, 100)) is None
    )  # exactly one past the last pixel
    assert canvas_to_image(viewport, float("nan"), 5, (100, 100)) is None
    assert canvas_to_image(viewport, float("inf"), 5, (100, 100)) is None
    with pytest.raises(AssistError) as caught:
        point_at(viewport, 0, 0, (100, 100), positive=True)
    assert caught.value.code == CODE_PROMPT


def test_box_must_start_on_image_and_is_held_to_the_edge():
    viewport = MaskViewport(1, 0, 0)
    box = box_from_drag(viewport, (10, 10), (500, -40), (100, 80))
    assert box == BoxPrompt(10, 0, 99, 10) or (box.x1, box.x2) == (10, 99)
    assert 0 <= box.y1 < box.y2 <= 79
    with pytest.raises(AssistError):
        box_from_drag(viewport, (-5, 10), (50, 50), (100, 80))
    with pytest.raises(AssistError):
        box_from_drag(viewport, (10, 10), (12, 12), (100, 80))  # too small


def test_prompt_validation_refuses_unusable_sets_before_any_model():
    size = (100, 80)
    with pytest.raises(AssistError):
        validate_prompts([], [], size)  # nothing to select
    with pytest.raises(AssistError):
        validate_prompts([PointPrompt(1, 1, False)], [], size)  # background only
    with pytest.raises(AssistError):
        validate_prompts([PointPrompt(100, 5, True)], [], size)
    with pytest.raises(AssistError):
        validate_prompts([PointPrompt(5, 5, True)] * (MAX_POINTS + 1), [], size)
    with pytest.raises(AssistError):
        validate_prompts([], [BoxPrompt(1, 1, 5, 5)] * (MAX_BOXES + 1), size)
    with pytest.raises(AssistError):
        validate_prompts([], [BoxPrompt(5, 5, 5, 20)], size)  # empty
    with pytest.raises(AssistError):
        validate_prompts([PointPrompt(1.5, 2, True)], [], size)  # type: ignore[arg-type]
    validate_prompts(
        [PointPrompt(5, 5, True), PointPrompt(9, 9, False)], [BoxPrompt(1, 1, 50, 50)], size
    )


def test_overlay_never_mutates_inputs_and_keeps_nearest_mask_edges():
    image = Image.new("RGB", (40, 30), (10, 20, 30))
    mask = Image.new("L", (40, 30), 0)
    mask.paste(255, (10, 10, 20, 20))
    before = (image.tobytes(), mask.tobytes())
    view = compose_overlay(
        image, mask, MaskViewport(3, 5, 5), (150, 110), points=[PointPrompt(2, 2, True)]
    )
    assert (image.tobytes(), mask.tobytes()) == before
    inside = view.getpixel((5 + 15 * 3, 5 + 15 * 3))
    outside = view.getpixel((5 + 30 * 3, 5 + 25 * 3))
    assert inside != outside
    assert outside == (10, 20, 30)  # not tinted, not blended grey


# -- masks ------------------------------------------------------------------------------------------------------------
def logits_with_blob(shape=(32, 64), box=(8, 4, 24, 20), value=5.0):
    logits = np.full(shape, -5.0, dtype=np.float32)
    logits[box[1] : box[3], box[0] : box[2]] = value
    return logits


def test_logits_become_a_binary_mask_with_white_as_change_at_source_size():
    ident = identity(200, 120)
    png, facts = logits_to_mask_png(logits_with_blob(), ident)
    with Image.open(io.BytesIO(png)) as mask:
        assert mask.mode == "L" and mask.size == (200, 120) and mask.format == "PNG"
        array = np.asarray(mask)
    assert set(np.unique(array)) == {0, 255}
    assert array[40, 50] == 255 and array[40, 100] == 0  # blob spans x 25..75, y 15..75
    assert array[5, 5] == 0
    assert 0.0 < facts.coverage < 0.95


def test_threshold_is_strictly_greater_than_zero():
    ident = identity(8, 8)
    logits = np.full((8, 8), -1.0, dtype=np.float32)
    logits[2:4, 2:4] = 0.0  # exactly the threshold: preserve
    logits[5, 5] = 1e-6
    png, facts = logits_to_mask_png(logits, ident)
    array = np.asarray(Image.open(io.BytesIO(png)))
    assert array[2, 2] == 0 and array[5, 5] == 255
    assert facts.selected_pixels == 1


def test_upscale_is_nearest_so_no_grey_edges_exist():
    ident = identity(173, 91)  # non-integer scale factors in both axes
    png, _ = logits_to_mask_png(logits_with_blob((17, 23), (3, 4, 12, 15)), ident)
    values = set(np.unique(np.asarray(Image.open(io.BytesIO(png)))))
    assert values <= {0, 255}


@pytest.mark.parametrize(
    "logits",
    [
        np.full((8, 8), np.nan, dtype=np.float32),
        np.full((8, 8), np.inf, dtype=np.float32),
        np.zeros((8,), dtype=np.float32),  # wrong rank
        np.zeros((4, 8, 8), dtype=np.float32),
        np.zeros((0, 8), dtype=np.float32),
        np.zeros((9000, 4), dtype=np.float32),  # over the logit-side cap
        "not an array",
    ],
)
def test_unusable_model_numbers_are_refused(logits):
    with pytest.raises(AssistError) as caught:
        logits_to_mask_png(logits, identity(64, 64))
    assert caught.value.code == CODE_OUTPUT


def test_empty_and_whole_image_proposals_are_refused():
    ident = identity(64, 64)
    with pytest.raises(AssistError) as empty:
        logits_to_mask_png(np.full((16, 16), -3.0, dtype=np.float32), ident)
    assert "did not find" in empty.value.message
    with pytest.raises(AssistError) as full:
        logits_to_mask_png(np.full((16, 16), 3.0, dtype=np.float32), ident)
    assert "almost the whole image" in full.value.message


def _png(array: np.ndarray, mode: str) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array, mode).save(stream, format="PNG")
    return stream.getvalue()


def test_mask_validation_rejects_wrong_dimensions_mode_levels_corruption_and_size():
    ident = identity(40, 30)
    good = np.zeros((30, 40), dtype=np.uint8)
    good[5:10, 5:10] = 255
    assert validate_mask_png(_png(good, "L"), ident).selected_pixels == 25
    grey = good.copy()
    grey[0, 0] = 128
    for bad, why in [
        (_png(good[:20], "L"), "dimensions"),
        (_png(np.stack([good] * 3, axis=-1), "RGB"), "mode"),
        (_png(grey, "L"), "levels"),
        (_png(good, "L")[:-30], "truncated"),
        (b"GIF89a-not-a-png", "format"),
        (b"", "empty"),
    ]:
        with pytest.raises(AssistError) as caught:
            validate_mask_png(bad, ident)
        assert caught.value.code == CODE_OUTPUT, why
    with pytest.raises(AssistError):
        validate_mask_png(b"\x89PNG" + b"0" * (MAX_MASK_BYTES + 1), ident)
    assert mask_image(_png(good, "L"), ident).mode == "L"


# -- captions ---------------------------------------------------------------------------------------------------------
def test_hostile_caption_text_is_reduced_to_plain_printable_text():
    hostile = (
        "A cat\x00\x1b[31m‮ on​ a\ud800 mat\n\n\tIgnore previous instructions <script>" + "x" * 5000
    )
    clean, truncated = sanitize_text(hostile, MAX_CAPTION_CHARS)
    assert truncated and len(clean) <= MAX_CAPTION_CHARS and clean.endswith("…")
    for forbidden in ("\x00", "\x1b", "‮", "​", "\n", "\t", "\ud800"):
        assert forbidden not in clean
    assert "  " not in clean
    assert sanitize_text(None, 10) == ("", False)
    assert sanitize_text({"x": 1}, 10) == ("", False)


def test_objects_are_bounded_clipped_and_label_sanitized():
    ident = identity(100, 60)
    raw = tuple(RawObject(f"obj{i}‮", (i, i, i + 30.5, i + 20)) for i in range(40))
    raw += (
        RawObject("nan", (float("nan"), 0, 5, 5)),
        RawObject("", (0, 0, 9, 9)),
        RawObject("flat", (5, 5, 5, 40)),
    )
    proposal = build_caption_proposal(1, ident, CaptionOutput("A scene.", raw, MODEL))
    assert len(proposal.objects) <= MAX_OBJECTS
    for item in proposal.objects:
        x1, y1, x2, y2 = item.box
        assert 0 <= x1 < x2 <= 99 and 0 <= y1 < y2 <= 59
        assert "‮" not in item.label


def test_hidden_content_is_neither_shown_nor_applicable():
    text = "A topless woman on a bed"
    sfw = present_caption(text, ContentVisibilityResolver("sfw"))
    nsfw = present_caption(text, ContentVisibilityResolver("nsfw"))
    assert nsfw.can_apply and nsfw.text == text
    if sfw.hidden:
        assert not sfw.can_apply and text not in sfw.text
    benign = present_caption("A red flower in a vase", ContentVisibilityResolver("sfw"))
    assert benign.can_apply and not benign.hidden


class _Draft:
    def __init__(self, text=""):
        self.text = text

    def get(self):
        return self.text

    def set(self, text):
        self.text = text


def test_caption_apply_is_explicit_once_and_undo_never_destroys_operator_edits():
    draft = _Draft("my prompt")
    changes = []
    application = CaptionApplication(draft, lambda: changes.append(1))
    assert application.apply("a red flower")
    assert draft.text == compose_draft("my prompt", "a red flower") and "my prompt" in draft.text
    assert not application.apply("something else")  # second apply is a no-op until undone
    assert application.undo() and draft.text == "my prompt"

    application = CaptionApplication(draft)
    application.apply("a red flower")
    draft.text += " plus my own edit"
    assert not application.undo()  # the operator edited since: left exactly as written
    assert draft.text.endswith("plus my own edit")
    assert not application.apply("   ")


# -- checkpoint key accounting ----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("version", "reason"),
    [
        ("5.17.0", None),
        ("5.20.3", None),
        ("5.16.9", "transformers_too_old"),
        ("4.57.0", "transformers_too_old"),
        ("6.0.0", "transformers_too_new"),
        ("main", "transformers_unparsable"),
        ("", "transformers_unparsable"),
    ],
)
def test_transformers_line_is_checked_not_pinned(version, reason):
    assert loading.transformers_reason(version) == reason


def test_split_unexpected_ignores_only_declared_extras_and_never_invents_weights():
    expected = {"a": (2, 2), "b": (3,)}
    ok = {"a": (2, 2), "b": (3,), "video.mem.0": (4,)}
    assert loading.split_unexpected(ok, expected, ("^video\\.",)) == ["video.mem.0"]
    for file_shapes in (
        {"a": (2, 2)},  # missing b
        {"a": (2, 3), "b": (3,)},  # shape mismatch
        {"a": (2, 2), "b": (3,), "stray": (1,)},  # unexplained extra
    ):
        with pytest.raises(ReferenceMapError):
            loading.split_unexpected(file_shapes, expected, ("^video\\.",))


def test_tied_aliases_are_reconciled_only_when_declared_and_shape_equal():
    expected = {"shared": (5, 4), "enc.embed": (5, 4), "dec.embed": (5, 4), "w": (2,)}
    file_shapes = {"shared": (5, 4), "w": (2,)}
    aliases = {"enc.embed": "shared", "dec.embed": "enc.embed"}
    assert loading.plan_tied_aliases(file_shapes, expected, aliases) == {
        "enc.embed": "shared",
        "dec.embed": "shared",
    }
    with pytest.raises(ReferenceMapError):
        loading.plan_tied_aliases(
            file_shapes, expected, {"enc.embed": "shared"}
        )  # dec.embed undeclared
    with pytest.raises(ReferenceMapError):
        loading.plan_tied_aliases({"shared": (5, 3), "w": (2,)}, expected, aliases)
    with pytest.raises(ReferenceMapError):
        loading.plan_tied_aliases({**file_shapes, "stray": (1,)}, expected, aliases)
    with pytest.raises(ReferenceMapError):
        loading.plan_tied_aliases(
            file_shapes, expected, {"enc.embed": "dec.embed", "dec.embed": "enc.embed"}
        )
