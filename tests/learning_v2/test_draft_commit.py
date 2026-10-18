"""Committing rated drafts: only unrated images, nothing lost, other experiments untouched."""

from __future__ import annotations

from src.learning.draft_commit import DraftCommitSummary, commit_drafts, parse_draft

EXP = "exp-1"


def _draft(rating: int = 4, **extra: object) -> dict[str, object]:
    return {
        "overall_rating": rating,
        "notes": "n",
        "context_flags": {"people": True},
        "subscores": {"anatomy": 5, "bad": 0},
        **extra,
    }


def _run(drafts, *, rated=(), known=("a.png", "b.png", "c.png"), fail=()):
    committed: list[tuple[str, int, str]] = []

    def commit(ref, variant, rating):
        if ref in fail:
            raise OSError("disk full")
        committed.append((ref, rating.rating, variant))

    remaining, summary = commit_drafts(
        drafts,
        experiment_id=EXP,
        find_variant=lambda ref: "variant-1" if ref in known else None,
        is_rated=lambda ref: ref in rated,
        commit=commit,
    )
    return remaining, summary, committed


def test_a_rated_draft_parses_into_record_rating_arguments() -> None:
    parsed = parse_draft(_draft(4))

    assert parsed is not None
    assert (parsed.rating, parsed.notes) == (4, "n")
    assert parsed.details["subscores"] == {"anatomy": 5}
    assert parsed.details["context_flags"] == {"people": True}
    assert isinstance(parsed.details["blended_rating"], int)


def test_a_draft_without_a_rating_cannot_be_committed() -> None:
    assert parse_draft({"overall_rating": 0, "notes": "x"}) is None
    assert parse_draft({"overall_rating": "junk"}) is None
    assert parse_draft({}) is None


def test_rated_drafts_for_unrated_images_are_committed_and_removed() -> None:
    drafts = {f"{EXP}:a.png": _draft(4), f"{EXP}:b.png": _draft(2)}

    remaining, summary, committed = _run(drafts)

    assert remaining == {}
    assert summary.committed == 2
    assert sorted((ref, rating) for ref, rating, _ in committed) == [("a.png", 4), ("b.png", 2)]


def test_an_image_that_is_already_rated_keeps_its_draft_and_its_saved_rating() -> None:
    drafts = {f"{EXP}:a.png": _draft(1)}

    remaining, summary, committed = _run(drafts, rated={"a.png"})

    assert committed == []
    assert remaining == drafts
    assert summary == DraftCommitSummary(already_rated=1)


def test_unrated_orphaned_and_failed_drafts_are_kept() -> None:
    drafts = {
        f"{EXP}:a.png": {"overall_rating": 0, "notes": "just a note"},
        f"{EXP}:gone.png": _draft(3),
        f"{EXP}:b.png": _draft(5),
    }

    remaining, summary, committed = _run(drafts, fail={"b.png"})

    assert committed == []
    assert set(remaining) == set(drafts)
    assert (summary.unrated, summary.orphaned, summary.failed, summary.committed) == (1, 1, 1, 0)
    assert "disk full" in summary.errors[0]


def test_other_experiments_drafts_pass_through_untouched() -> None:
    drafts = {f"{EXP}:a.png": _draft(4), "exp-2:a.png": _draft(5)}

    remaining, summary, committed = _run(drafts)

    assert remaining == {"exp-2:a.png": _draft(5)}
    assert summary.committed == 1
    assert [ref for ref, *_ in committed] == ["a.png"]


def test_image_refs_with_colons_survive_the_key_split() -> None:
    ref = "C:\\out\\a.png"

    remaining, summary, committed = _run({f"{EXP}:{ref}": _draft(4)}, known=(ref,))

    assert summary.committed == 1
    assert committed[0][0] == ref
    assert remaining == {}


def test_summary_describes_what_was_kept() -> None:
    summary = DraftCommitSummary(committed=3, already_rated=1, failed=2)

    assert (
        summary.describe()
        == "3 saved; 1 already rated (kept as drafts); 2 failed (kept as drafts)."
    )
    assert summary.kept == 3
