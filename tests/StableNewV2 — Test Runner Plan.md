StableNewV2 — Test Runner Plan
Version: 2025-11-26_1147
1. Purpose

Defines how Journey Tests (JT-01 through JT-13) are executed across:

DEV (local developer machines)

CI (automated continuous integration jobs)

Pre-release regression runs

Ensures the entire pipeline—from Prompt authoring to Learning experiments—has predictable, repeatable validation.

2. Environments
DEV

Full GUI

Developers run manual & automated subsets

Used during PR implementation and bug fixing

CI

Headless mode (Xvfb / virtual display)

Runs smoke tests, logic tests, and learning-specific nightly tests

PRE-RELEASE

Full manual + automated JT suite

Mandatory for release signoff

3. Journey Test Categories
Category	Tests
Core Authoring & Pipeline	JT-01 → JT-05
Infrastructure	JT-07, JT-13
Learning System	JT-08 → JT-10
Experience / Workflow	JT-11 → JT-12
Future Features	JT-06, JT-09, JT-11 (until implemented)
4. Execution Matrix
JT	Name	DEV	CI	Pre-Release
01	Prompt Pack Authoring	Weekly	Mocked	Always
02	LoRA / Embedding Integration	Weekly	Mocked	Always
03	txt2img Pipeline Run	Per change	Smoke	Always
04	img2img / ADetailer Run	Per change	Optional	Always
05	Upscale Stage Run	Per change	Optional	Always
06	Video Pipeline (Future)	n/a	n/a	n/a
07	Startup + Async WebUI Bootstrap	Infra change	Smoke	Always
08	Single-Variable Learning	Learning change	Nightly	Always
09	X/Y Learning (Future)	Future	Future	Future
10	Ratings / Review	Learning change	Nightly	Always
11	Presets / Styles (Future)	Future	Future	Future
12	Run / Stop / Run Lifecycle	Controller change	Smoke	Always
13	Logging & Error Surfacing	Infra change	Partial	Always
5. Automation Plan
Directory Structure
tests/
  journey/
    test_jt01_prompt_pack.py
    test_jt02_lora_embedding.py
    test_jt03_txt2img.py
    ...
    test_jt13_logging.py

Pytest Markers

@pytest.mark.journey

@pytest.mark.smoke

@pytest.mark.learning

@pytest.mark.jt01 … @pytest.mark.jt13

Marker Usage

Core Journey: pytest -m "journey and core"

Smoke tests: pytest -m "journey and smoke"

Learning: pytest -m "journey and learning"

Full suite: pytest -m journey

6. CI Integration
Recommended Jobs
1. Smoke on Merge Requests
pytest -m "journey and smoke"

2. Nightly Learning Tests
pytest -m "journey and learning"

3. Full Pre-Release Validation
pytest -m journey

Headless GUI Strategy

Use Xvfb for Tkinter GUI tests

Or split headless logic tests vs manual GUI exercises

7. Manual Test Requirements

Certain JTs require human UX validation:

JT-01 – Prompt authoring fidelity

JT-02 – Visual LoRA slider binding

JT-04 – img2img / ADetailer quality

JT-10 – Ratings & navigation UX

Manual pass checklist should be stored under:

docs/testing/runs/


Each run includes:

Date

Tester initials

PASS / FAIL / N/A

Optional notes

8. Ownership
Responsibility	Owner
Journey Test Suite Maintenance	Test Architect / PM
Automation & CI	DevOps / Automation Engineer
Release Signoff	Release Manager
9. Versioning & Change Management

When features change:

Update the relevant JT-XX spec file.

Update the Test Runner Plan if mappings or cadence change.

Ensure pytest markers and filenames remain synchronized.

Minor version increment recommended for clustered changes.

10. Next Steps

Create test skeletons under tests/journey/

Implement smoke test CI jobs

Implement nightly learning job

Add pre-release “all JTs” test plan to release checklist