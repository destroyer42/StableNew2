"""MEC-903: confirmed Civitai batch lookups by verified SHA-256, stored per checkpoint as unreviewed facts."""

from urllib.error import HTTPError

import pytest

from src.generation_profiles.civitai_lookups import (
    LookupStore,
    base_model_hint,
    batch_lookup,
    describe_result,
    disclosure,
)
from src.generation_profiles.evidence_refresh import EvidenceRefresh, Lookup, civitai_identification

A, B, C = "a" * 64, "b" * 64, "c" * 64


def version(sha, base="SD 1.5", **extra):
    return {
        "id": 7,
        "name": "v2 pruned",
        "baseModel": base,
        "baseModelType": "Standard",
        "model": {
            "name": "Dream Mix",
            "type": "Checkpoint",
            "description": "<p>prompt: secret</p>",
        },
        "trainedWords": ["secret"],
        "files": [{"hashes": {"SHA256": sha.upper()}}],
        **extra,
    }


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_identification_keeps_short_labels_and_drops_text_urls_and_settings():
    facts = civitai_identification(
        version(
            A,
            base="Pony",
            name="v1 https://evil.example",
            model={"name": "A\nB\x00C", "type": "Checkpoint"},
        )
    )
    assert facts == {
        "base_model": "Pony",
        "base_model_type": "Standard",
        "model_name": "A BC",
        "model_type": "Checkpoint",
    }


def test_refresh_reports_identification_only_for_a_matching_hash():
    matched = EvidenceRefresh(lambda _u: version(A), clock=lambda: 0).refresh(
        Lookup("civitai", A), confirmed=True
    )
    assert matched["identification"]["base_model"] == "SD 1.5"
    assert "secret" not in str(matched)
    other = EvidenceRefresh(lambda _u: version(B), clock=lambda: 0).refresh(
        Lookup("civitai", A), confirmed=True
    )
    assert not other["hash_matched"] and "identification" not in other


def test_batch_waits_for_the_rate_limit_and_stores_definite_answers(tmp_path):
    clock, requests = Clock(), []

    def get(url):
        requests.append(url)
        if B in url:
            raise HTTPError(url, 404, "not found", {}, None)
        if C in url:
            raise OSError("offline")
        return version(A)

    store = LookupStore(tmp_path)
    messages = []
    summary = batch_lookup(
        [A, B, C],
        store=store,
        refresh=EvidenceRefresh(get, clock=clock),
        confirmed=True,
        progress=messages.append,
        sleep=clock.sleep,
    )
    assert (summary.identified, summary.not_found, summary.unavailable) == (1, 1, 1)
    assert len(requests) == 3 and clock.now >= 4  # one request every 2 seconds
    assert any("rate limit" in message for message in messages)
    assert base_model_hint(store.load(A)) == "SD 1.5"
    assert "Not found on Civitai" in describe_result(store.load(B))
    assert store.load(C) is None  # offline is retried later, not remembered
    assert set(store.load_all()) == {A, B}
    assert "Dream Mix / v2 pruned" in describe_result(store.load(A))


def test_batch_requires_confirmation_and_stops_on_cancel(tmp_path):
    requests = []
    refresh = EvidenceRefresh(lambda url: requests.append(url) or version(A), clock=lambda: 0)
    with pytest.raises(ValueError, match="Confirm"):
        batch_lookup([A], store=LookupStore(tmp_path), refresh=refresh, confirmed=False)
    summary = batch_lookup(
        [A, B], store=LookupStore(tmp_path), refresh=refresh, confirmed=True, cancelled=lambda: True
    )
    assert summary.cancelled and requests == []


def test_disclosure_lists_hashes_but_no_paths():
    text = disclosure([A, B], {A: "Not Working/x.safetensors"})
    assert "Send 2 SHA-256 hashes" in text and A[:16] in text
    assert "file names are not sent" in text
