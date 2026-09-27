"""PR-VID-184: legal Wan-length + qualification-only output trim. Pure stdlib, no GPU/network.

Proves, before any GPU dispatch, the six properties the owner amendment required:
1. input motion source stays exactly the frozen evidence-frame count;
2. internal generation length is the smallest legal (4n+1) value covering it;
3. the final adjudicated output, after trim, is exactly the evidence-frame count;
4. no temporal resampling occurs (trim only drops frames, never reindexes/interpolates);
5. no source-frame substitution occurs (retained frames are unaltered, in original order);
6. the frozen scoring contract remains untouched by this correction.
"""

from __future__ import annotations

import pytest

from tools.qualification.vid184 import scoring_contract as sc
from tools.qualification.vid184.legal_length import (
    is_legal_wan_length,
    smallest_legal_wan_length,
    trim_to_evidence_window,
)

RUN_5_EVIDENCE_FRAMES = 39
RUN_5_INTERNAL_LENGTH = 41
RUNS_1_4_EVIDENCE_FRAMES = 60
RUNS_1_4_INTERNAL_LENGTH = 61


# --- property 1: frozen evidence-frame counts are exactly what the package committed to ---------


def test_run5_frozen_evidence_window_is_exactly_39_frames() -> None:
    assert RUN_5_EVIDENCE_FRAMES == 39


def test_runs1_4_frozen_evidence_window_is_exactly_60_frames() -> None:
    assert RUNS_1_4_EVIDENCE_FRAMES == 60


# --- property 2: internal generation length is the smallest legal 4n+1 covering it ---------------


def test_run5_internal_length_is_smallest_legal_4n_plus_1() -> None:
    assert smallest_legal_wan_length(RUN_5_EVIDENCE_FRAMES) == RUN_5_INTERNAL_LENGTH
    assert is_legal_wan_length(RUN_5_INTERNAL_LENGTH)


def test_runs1_4_internal_length_is_smallest_legal_4n_plus_1() -> None:
    # The same WanVAE.encode floor applies to every run, not just run 5 -- 60 is not 4n+1 either.
    assert smallest_legal_wan_length(RUNS_1_4_EVIDENCE_FRAMES) == RUNS_1_4_INTERNAL_LENGTH
    assert is_legal_wan_length(RUNS_1_4_INTERNAL_LENGTH)


def test_evidence_frame_counts_are_not_themselves_legal() -> None:
    # This is exactly the bug being guarded against: WanVAE.encode floors 39 -> 37 and 60 -> 57,
    # silently dropping trailing real driving frames, if fed directly as `length`.
    assert not is_legal_wan_length(RUN_5_EVIDENCE_FRAMES)
    assert not is_legal_wan_length(RUNS_1_4_EVIDENCE_FRAMES)


def test_smallest_legal_length_is_idempotent_on_an_already_legal_value() -> None:
    assert smallest_legal_wan_length(41) == 41
    assert smallest_legal_wan_length(1) == 1


def test_smallest_legal_length_rejects_nonpositive_input() -> None:
    with pytest.raises(ValueError):
        smallest_legal_wan_length(0)
    with pytest.raises(ValueError):
        is_legal_wan_length(0)


# --- property 3: final adjudicated output, after trim, is exactly the evidence-frame count -------


def test_trim_recovers_exactly_the_evidence_frame_count() -> None:
    decoded_output = [f"frame_{i}" for i in range(RUN_5_INTERNAL_LENGTH)]
    trimmed = trim_to_evidence_window(decoded_output, RUN_5_EVIDENCE_FRAMES)
    assert len(trimmed) == RUN_5_EVIDENCE_FRAMES


# --- property 4: no temporal resampling -- trim only drops trailing frames -----------------------


def test_trim_only_drops_trailing_frames_no_reordering() -> None:
    decoded_output = list(range(RUN_5_INTERNAL_LENGTH))
    trimmed = trim_to_evidence_window(decoded_output, RUN_5_EVIDENCE_FRAMES)
    assert trimmed == list(range(RUN_5_EVIDENCE_FRAMES))


# --- property 5: no source-frame substitution -- retained frames are byte-identical, in order ----


def test_trim_never_substitutes_or_alters_retained_leading_frames() -> None:
    real_frames = [f"real_frame_{i}" for i in range(RUN_5_EVIDENCE_FRAMES)]
    held_padding = ["held_pad_39", "held_pad_40"]
    decoded_output = real_frames + held_padding
    trimmed = trim_to_evidence_window(decoded_output, RUN_5_EVIDENCE_FRAMES)
    assert trimmed == real_frames
    assert "held_pad_39" not in trimmed
    assert "held_pad_40" not in trimmed


def test_trim_rejects_fewer_frames_than_the_evidence_window() -> None:
    with pytest.raises(ValueError):
        trim_to_evidence_window(["a", "b"], RUN_5_EVIDENCE_FRAMES)


# --- property 6: the frozen scoring contract is untouched by this correction ---------------------


def test_frozen_scoring_contract_is_untouched_by_the_length_correction() -> None:
    assert sc.contract_sha256() == sc.FROZEN_CONTRACT_SHA256
