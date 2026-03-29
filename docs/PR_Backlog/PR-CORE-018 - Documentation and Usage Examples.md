PR-CORE-018 – Documentation and Usage Examples

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Post‑Unification Core Refinement
Date: 2026‑03‑29

Context & Motivation

StableNew has grown into a sophisticated system with multiple pipelines (image‑to‑video, story planning, prompt packs) and numerous configuration options. However, documentation lags behind; new users struggle to understand how to set up characters, create PromptPacks, or run end‑to‑end workflows. The architecture documents stress the importance of clear examples and tutorials, yet many new features (e.g. multi‑character support, style LoRAs) are not covered in the current guides. PR‑CORE‑018 addresses this by producing comprehensive, up‑to‑date documentation and curated examples.

Goals & Non‑Goals
Goal: Create a user‑friendly, version‑controlled documentation portal (e.g. using MkDocs or Sphinx) that covers all core concepts, including installing dependencies, running basic pipelines, training character embeddings, and combining multiple characters.
Goal: Develop sample projects that demonstrate realistic use cases, such as generating a short clip from a fantasy novel chapter or stitching multiple scenes into a mini‑movie. Provide step‑by‑step instructions and example configs.
Goal: Add inline code comments and docstrings where they are missing in critical modules (e.g. prompt_pack.py, story_plan_store.py) to support developer comprehension.
Goal: Update the README.md file to reflect the current feature set and provide quick start instructions.
Non‑Goal: Writing academic papers or marketing materials. This PR focuses on practical guides and developer‑oriented documentation.
Guardrails
Keep documentation in sync with the code. Use CI checks to warn when doc pages are outdated or missing references to newly merged PRs.
Avoid duplicating information across multiple files; use cross‑referencing to maintain a single source of truth. For example, link to the image metadata contract rather than restating it.
Provide clear attributions for any borrowed images or text excerpts from books used in examples.
Allowed Files
Files to Create
docs/index.md – main landing page for StableNew documentation; introduce high‑level concepts.
docs/getting_started.md – step‑by‑step installation and first‑run guide.
docs/tutorials/ – directory of example workflows, such as “Generate a Video from a Novel Scene” or “Train a Character Embedding”. Each tutorial will include markdown instructions and sample configuration files.
docs/api/ – auto‑generated API reference pages for Python modules (via Sphinx autodoc). Ensure code has proper docstrings.
docs/examples/ – include finished outputs (e.g. images, videos) and sample config files to accompany the tutorials.
tests/docs/test_tutorials.py – test script that ensures all tutorials run without errors (using minimal stub data and mocking heavy dependencies).
Files to Modify
README.md – update with a new summary of StableNew’s capabilities, installation instructions, and links to detailed docs.
Various source files – add or improve docstrings and inline comments for key classes and functions. Focus on modules used by external developers (e.g. prompt_pack, job_builder_v2).
Forbidden Files
Do not embed large assets (e.g. videos) directly into the repository. Host them externally or compress them if needed.
Implementation Plan
Documentation Framework: Choose a documentation engine (e.g. MkDocs or Sphinx) and set up its configuration in docs/. Create a table of contents covering core topics: architecture overview, installation, basic usage, advanced features, and API reference. Add a Makefile or GitHub action to build the docs on CI.
Content Creation: Write the main pages (index.md, getting_started.md) with clear language and diagrams showing how data flows through StableNew. Use diagrams from existing architecture docs as guidance.
Tutorials: Develop at least three tutorial guides:
Tutorial 1: Generate a single video clip from a story description. Step through writing a prompt, selecting a model, and running SVD. Include references to the depth‑map support (PR‑CORE‑017).
Tutorial 2: Train a character embedding using the Character Embedding pipeline (PR‑CORE‑002) and apply it to generate consistent images and video.
Tutorial 3: Combine multiple scenes into a stitched video using the story planner and video stitcher (PR‑CORE‑003 and PR‑CORE‑007). Provide scripts and config files.
API Reference: Use Sphinx autodoc to generate documentation for modules such as prompt_pack.py, story_plan_store.py, svd_service.py, and others. Write docstrings for these modules where missing.
Readme Refresh: Re‑write the README.md to summarise capabilities, list installation requirements, and link to the new documentation. Emphasise that the docs live under docs/ and can be built locally.
Tests: Implement test_tutorials.py that attempts to run the code snippets in each tutorial (using minimal example data) to ensure instructions are correct. Use mocking to avoid heavy computation.
CI Integration: Add a CI job that builds the documentation on each commit and fails if there are broken links or missing pages.
Testing Plan
Doc Build Test: Configure CI to build the docs using the chosen framework. Fail if any pages do not build or contain broken references.
Tutorial Execution Test: In test_tutorials.py, run the tutorial scripts in a headless environment with stub data. Assert that they complete without raising exceptions. Skip heavy parts (e.g. diffusers pipeline) by mocking.
Spell & Lint Checks: Use a linter (e.g. markdownlint) and a spell checker to ensure quality and consistency across docs.
Verification Criteria
New documentation pages exist in docs/, covering installation, usage guides, tutorials, and API reference.
The README.md contains an updated summary and links to docs. All instructions are accurate and reproducible.
Tutorials produce the expected outputs (within mocked environments). Tests verifying the tutorials pass in CI.
Docstrings and inline comments are present in major modules and are reflected in the generated API reference.
CI build includes a job that builds the docs and fails on broken links.
Risk & Mitigation
Risk: Documentation may become outdated as new features are added. Mitigate by integrating doc updates into the definition of done for future PRs and by adding CI checks for missing docs.
Risk: Tutorials might rely on large models, making them slow to run. Mitigate by using smaller models or stub data and by clearly marking optional steps.
Dependencies
Dependent on core features (PR‑CORE‑001 through PR‑CORE‑017) being stable; the docs will describe these features. No functional code dependencies.
Approval & Execution
Approvers: Documentation lead, maintainers.
Execution: Create a documentation branch (feature/docs) and commit the new files. Ensure the CI build passes. After review and final edits, merge into the main branch.
