PR-CORE1-D11.md

Title: Delete PipelineConfigAssembler Path and Re-Anchor Controllers to NJR Builder Pipeline

Status: Ready for Execution
Risk Tier: Tier 2 (Core Controller Logic)
Architecture Version: v2.6
Related Debt IDs: D-11 (Architectural Drift), CORE1-D
Depends On: Existing JobBuilderV2 / NJR pipeline

1. Intent

Eliminate the legacy PipelineConfigAssembler execution path and its associated tests, which are now blocking pytest collection and violating the v2.6 architecture.
This PR enforces a single canonical job construction path:

PromptPack → Builder Pipeline → NormalizedJobRecord → Queue → Runner

No compatibility shims or partial migrations are permitted.

2. Problem Statement

The repository currently fails pytest collection due to references to a deleted module:

src.controller.pipeline_config_assembler


This reflects unresolved architectural drift where:

Legacy config-assembly logic is still assumed by tests

Controllers implicitly support multiple execution paths

NJR-only invariants are violated by test expectations

This PR removes the dead path entirely and re-anchors the controller contract to the v2.6 Builder Pipeline.

3. Canonical Architecture Alignment

This PR explicitly enforces:

PromptPack-only prompt sourcing

Builder-only job construction

NJR-only execution

No legacy pipeline_config objects

No controller-side config assembly

This matches:

ARCHITECTURE_v2.6.md

Builder Pipeline Deep Dive v2.6

ARCHITECTURAL_DEBT_ANALYSIS.md

4. Scope of Change
In Scope

Controller imports and execution routing

Controller-level tests

Removal of legacy assembler tests

Out of Scope (Explicitly Protected)

Advanced Prompt Panel

Learning Module

Randomizer internals

Video / clustering pipelines

5. File-by-File Change Plan
5.1 src/controller/pipeline_controller.py

Modify

Remove all imports and references to:

PipelineConfigAssembler

GuiOverrides

Ensure all preview / enqueue / run paths invoke the Builder Pipeline → NJR

Ensure no code path constructs or accepts pipeline_config dicts

Delete

Any helper methods that exist only to support assembler-based execution

5.2 tests/controller/test_pipeline_controller_config_path.py

Rewrite

Remove imports of pipeline_config_assembler

Replace assertions with:

Controller builds NJR(s) via JobBuilderV2

No legacy config objects are produced

PromptPack provenance exists on NJR

5.3 Legacy Assembler Tests (Delete)

Remove entire files:

tests/controller/test_pipeline_config_assembler.py

tests/controller/test_pipeline_config_assembler_core_fields.py

tests/controller/test_pipeline_config_assembler_model_fields.py

tests/controller/test_pipeline_config_assembler_negative_prompt.py

tests/controller/test_pipeline_config_assembler_output_settings.py

tests/controller/test_pipeline_config_assembler_resolution.py

These tests validate a deleted subsystem and must not be preserved or shimmed.

5.4 New Test: tests/controller/test_builder_pipeline_contract_v2_6.py

Add

Tests must assert:

Controller → Builder → NJR contract

PromptPack metadata survives into NJR

Multiple prompt packs result in multiple NJRs

No alternate job construction path exists

6. Tests & Validation
Required Test Runs
python -m pytest -q -m "not slow and not gui and not integration and not journey"

Pass Criteria

Pytest collection completes

No ModuleNotFoundError

Controller tests assert NJR-only behavior

7. Tech Debt Impact
Debt Removed

Legacy assembler path

Dual controller execution semantics

Broken test contracts

Debt Introduced

None

8. Documentation Updates Required

Update ARCHITECTURE_v2.6.md
→ Remove any mention of PipelineConfigAssembler

Update Builder Pipeline Deep Dive v2.6
→ Explicitly note assembler removal

9. Rollback Plan

Revert PR commit

Restore previous controller/test state (not recommended except for emergency)

10. Definition of Done

One controller execution path

NJR-only job flow

Tests collect and execute

No assembler references anywhere in repo