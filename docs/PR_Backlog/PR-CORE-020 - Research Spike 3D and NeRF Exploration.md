PR-CORE-020 – Research Spike: 3D and NeRF Exploration

Status: Specification
Priority: LOW
Effort: MEDIUM
Phase: Exploratory
Date: 2026‑03‑29

Context & Motivation

StableNew’s current focus is on 2D image and video generation using diffusion models. However, the industry is rapidly moving toward 3D content generation, including NeRF (Neural Radiance Fields), 3D Gaussian Splatting, and volumetric video techniques. These approaches can produce camera‑free movement and true parallax, which align with the long‑term goal of building visually rich movies from books. To remain competitive and plan future work, we propose a research spike to evaluate the feasibility of integrating 3D generation techniques into StableNew.

Goals & Non‑Goals
Goal: Survey current 3D generative models (NeRF, 3D diffusion, Gaussian Splatting) and assess their open‑source implementations, focusing on ease of integration with our pipeline.
Goal: Build a prototype that takes a single scene description (text or image) and produces a simple 3D representation (e.g. a NeRF or mesh) that can be rendered into short camera fly‑throughs.
Goal: Document findings, including performance metrics, quality assessments, and integration challenges. Provide recommendations on whether to pursue 3D as a core future feature.
Non‑Goal: Shipping a production‑ready 3D generation feature in this PR. This is purely an exploratory research spike.
Guardrails
Focus on open‑source or permissively licensed models. Do not integrate any proprietary code into the repository during this spike.
Keep the prototype separate from the main codebase. Place experimental scripts under a research/ directory and mark them clearly as experimental.
Avoid making promises about timelines or deliverables beyond this spike; the goal is to inform future decisions, not commit to immediate implementation.
Allowed Files
Files to Create
research/nerf/README.md – outline the scope of the research, summarise selected papers, and list candidate libraries (e.g. Instant‑NGP, DreamGaussian, 3D Gaussian Splatting). Include notes on licensing and technical requirements.
research/nerf/spike_report.md – after experiments, document methodology, results (quality vs. compute cost), and recommendations.
research/nerf/prototype.py – a simple script that, given a prompt or image, generates a 3D representation using a chosen open‑source library (e.g. renders a NeRF from a multi‑view sample dataset). Provide instructions for running it. Note: do not include large datasets; require the user to download them separately.
tests/research/test_nerf_prototype.py – unit test or smoke test to ensure the prototype script runs and produces an output file (e.g. a small GLB or MP4). Use a tiny synthetic dataset to minimise runtime.
Files to Modify
None in the core pipeline. This spike is separate from the main code.
Implementation Plan
Literature Survey: Compile a list of recent 3D generation papers and tools. Focus on NeRF variants (Instant‑NGP, DreamFusion, etc.) and 3D Gaussian Splatting. Identify which are open source and can run on commodity GPUs.
Library Selection: Choose one or two libraries that best fit our experimental needs (e.g. Instant‑NGP for NeRF and a Gaussian Splatting library). Assess ease of installation and documentation.
Prototype Development: Create prototype.py that loads a pre‑trained model or trains on a small dataset (e.g. synthetic shapes). For instance, use Instant‑NGP to train a NeRF on a few images and render a short camera path. Alternatively, load a pre‑trained 3D Gaussians model and render a camera fly‑through. The script should save the output as a video or GLB file.
Run Experiments: On a local machine or cloud instance, run the prototype on simple scenes. Measure training/inference time, GPU memory usage, and output quality. Capture sample outputs.
Write Report: Summarise the experiments in spike_report.md. Discuss the challenges, such as dataset preparation, hardware requirements, and integration points with StableNew (e.g. how a NeRF representation could be imported into our pipeline). Provide a recommendation: pursue 3D integration now, later, or not at all.
Testing: Implement test_nerf_prototype.py as a smoke test that runs the prototype on a minimal dataset and verifies that an output file is created. Skip test if required libraries are not installed (mark as optional).
Testing Plan
Smoke Test: Run prototype.py with a dummy dataset to ensure it completes without error and produces a file of the expected type.
Environment Check: Verify that installation instructions in README.md are correct by setting up a new environment and running the prototype.
Verification Criteria
A well‑structured research/nerf/README.md summarises the literature and libraries considered.
prototype.py runs and produces a simple 3D output file on a small dataset.
spike_report.md documents the methodology, results, and recommendations in a way that informs future decision‑making.
The prototype code remains isolated under research/ and does not affect production code.
The smoke test passes in an environment with dependencies installed.
Risk & Mitigation
Risk: 3D generation libraries may have large dependencies and long training times. Mitigate by using small synthetic datasets and by selecting lightweight implementations.
Risk: The research could distract from critical core features. To mitigate, limit the spike to a fixed timeframe and avoid feature creep.
Risk: Results might be inconclusive. Accept that the spike’s value is in informing strategy, even if no immediate integration is recommended.
Dependencies
None. This spike is exploratory and does not depend on other PRs. However, the team should coordinate with the core maintainers to allocate time and resources.
Approval & Execution
Approvers: Research lead, technical architect.
Execution: Create a research/nerf directory and commit the survey, prototype, and report. After the research concludes, present findings to stakeholders to decide whether to pursue 3D integration in future roadmaps.
