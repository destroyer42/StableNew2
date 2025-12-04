PR-112 – Prompt Pack + RunConfig Coupling & History.md

Risk Tier: Medium (Tier 2 – models + history)
Baseline: After PR-103 & PR-109 (RunConfig bridge + JobHistory V2)

1. Intent

Make sure every run is tagged with its prompt origin:

PACK – from a specific prompt pack + key(s),

MANUAL – user-typed ad-hoc prompt,

and that this information is:

Captured in RunConfig,

Propagated into JobRecord,

Visible in job history / panel,

so the future learning tab can correlate “what was asked” vs “how it was configured.”

2. Scope

Files

src/utils/prompt_packs.py

src/pipeline/run_config.py (or equivalent)

src/pipeline/job_history.py

tests/utils/test_prompt_packs.py (extend)

Possibly: tests/pipeline/test_run_config_prompt_source.py (new)

Out-of-Scope

Learning algorithms, recommendation engine.

GUI learning tab / rating UI.

Changes to how prompts are rendered or edited in the GUI.

3. Design
3.1 PromptSource enum

File: src/pipeline/run_config.py

Define an explicit enum (or at least string constants):

from enum import Enum


class PromptSource(str, Enum):
    MANUAL = "manual"
    PACK = "pack"

3.2 Extend RunConfig

If you already have a RunConfig model, extend it; otherwise, define one that fits your job pipeline. Add:

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass
class RunConfig:
    ...
    prompt_source: PromptSource = PromptSource.MANUAL
    prompt_pack_id: str | None = None
    prompt_keys: Sequence[str] = field(default_factory=list)   # which prompts in the pack
    prompt_payload: Mapping[str, Any] = field(default_factory=dict)  # minimal prompt info


prompt_payload can store a minimal summary (e.g., selected prompts + any overrides) to avoid having to re-open the pack just to display basic info.

3.3 prompt_packs utilities: origin metadata

File: src/utils/prompt_packs.py

Ensure the helpers that:

Load prompt packs.

Select a specific pack and key.

Build a job draft or RunConfig.

…populate fields correctly:

Add or extend a helper like:

def build_run_config_from_prompt_pack(
    pack_id: str,
    pack_data: Mapping[str, Any],
    selected_keys: list[str],
    *,
    base_config: RunConfig | None = None,
) -> RunConfig:
    cfg = base_config or RunConfig()
    cfg.prompt_source = PromptSource.PACK
    cfg.prompt_pack_id = pack_id
    cfg.prompt_keys = list(selected_keys)

    # Minimal prompt payload for history/learning
    prompts = {k: pack_data["prompts"][k] for k in selected_keys}
    cfg.prompt_payload = {"pack_id": pack_id, "prompts": prompts}

    return cfg


Similarly, when building a RunConfig for manual prompts:

def build_run_config_for_manual_prompt(
    prompt: str,
    negative_prompt: str = "",
    *,
    base_config: RunConfig | None = None,
) -> RunConfig:
    cfg = base_config or RunConfig()
    cfg.prompt_source = PromptSource.MANUAL
    cfg.prompt_pack_id = None
    cfg.prompt_keys = []
    cfg.prompt_payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
    }
    return cfg


Your controller/app_state can call these utilities instead of hand-rolling.

3.4 JobHistory integration

File: src/pipeline/job_history.py

Extend JobRecord (from PR-109) to include the new prompt-origin fields if they’re not already present:

@dataclass
class JobRecord:
    ...
    prompt_source: str  # "manual" | "pack"
    prompt_pack_id: str | None = None
    prompt_keys: list[str] = field(default_factory=list)


When creating a JobRecord from a RunConfig:

def job_record_from_run_config(job_id: str, run_config: RunConfig, **extra) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        run_mode=run_config.run_mode,   # from earlier PRs
        source=run_config.source,
        prompt_source=run_config.prompt_source.value,
        prompt_pack_id=run_config.prompt_pack_id,
        prompt_keys=list(run_config.prompt_keys),
        # plus stage_count, config_hash, timestamps, etc.
        **extra,
    )


Ensure that history-based consumers (Job History Panel, future learning) always rely on these fields instead of re-deriving them from job metadata.

4. Tests
4.1 Prompt pack utilities

File: tests/utils/test_prompt_packs.py

Add/extend tests to cover:

RunConfig built from prompt pack

Create a fake pack with id pack-123 and two prompts.

Call build_run_config_from_prompt_pack(pack_id, pack_data, ["p1", "p2"]).

Assert:

assert cfg.prompt_source == PromptSource.PACK
assert cfg.prompt_pack_id == "pack-123"
assert cfg.prompt_keys == ["p1", "p2"]
assert cfg.prompt_payload["pack_id"] == "pack-123"
assert set(cfg.prompt_payload["prompts"].keys()) == {"p1", "p2"}


RunConfig built for manual prompt

Call build_run_config_for_manual_prompt("A dragon", "no gore").

Assert:

assert cfg.prompt_source == PromptSource.MANUAL
assert cfg.prompt_pack_id is None
assert cfg.prompt_keys == []
assert cfg.prompt_payload["prompt"] == "A dragon"
assert cfg.prompt_payload["negative_prompt"] == "no gore"

4.2 JobHistory + RunConfig

Add a small test module (or extend existing):

File: tests/pipeline/test_run_config_prompt_source.py (suggested)

JobRecord from manual RunConfig

Build RunConfig via build_run_config_for_manual_prompt.

Call job_record_from_run_config("job-1", run_config, extra_fields...).

Assert:

assert record.prompt_source == "manual"
assert record.prompt_pack_id is None
assert record.prompt_keys == []


JobRecord from pack-based RunConfig

Build RunConfig via build_run_config_from_prompt_pack.

Same pattern; assert prompt_source == "pack" and prompt_pack_id and prompt_keys correct.

5. Validation & Acceptance

Commands:

pytest tests/utils/test_prompt_packs.py
pytest tests/pipeline/test_run_config_prompt_source.py
pytest tests/pipeline


Acceptance:

 RunConfig always carries prompt_source, prompt_pack_id, and prompt_keys.

 Utilities in prompt_packs.py build RunConfig objects with correct prompt-origin fields.

 JobRecord preserves prompt-origin data and Job History Panel can display it.

 Tests confirm that manual vs pack-based runs produce distinct, correctly populated RunConfig and JobRecord values.