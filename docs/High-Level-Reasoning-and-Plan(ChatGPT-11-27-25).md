
I will break it into four sections:

Where the product should go (vision & direction)

How to get there (execution roadmap, process shifts)

Systems to prevent regression & accelerate development

Guardrails for a fast-moving, low-experience developer using AI agents

1. Product Direction — Where I Would Take StableNew

StableNew already has the bones of a next-generation creative engine. It just needs a clear north star.

North Star Vision

Build a modular, high-automation, intelligent creative pipeline engine that:

Talks to WebUI automatically

Autogenerates image/video batches from structured configs

Learns over time (ratings, analytics, model performance tracking)

Runs deterministic pipelines or randomized creative explorations

Exports consistent metadata, artifacts, manifests

Can scale from one PC to a distributed multi-node cluster

Has a clean UI that reflects the pipeline concept directly, not a giant pile of buttons

This is not just a GUI wrapper; it’s a production-grade creative workflow agent.

2. How to Get There (Execution Roadmap)

Instead of hundreds of ad-hoc PRs, I would reframe the whole development into 4 Phases, each with small atomic PRs inside it.

⭐ Phase 1 — Stabilize Core System (Current Priority)

Goal: It boots, it runs pipelines, dropdowns populate, payloads are correct.

Move fast and aggressively:

Hard-line rule:
Only V2 code survives. V1 is immediately archived so accidental imports cannot happen.

Fix the V2 GUI scaffold once, clearly, deterministically.

Create a declarative “zone map” so every GUI file knows exactly what parent container it belongs to.

Make pipeline payload building deterministic, predictable, and fully logged.

Implement solid WebUI discovery & healthcheck once and never revisit it.

Deliverables:

Stable pipeline runs

Stable dropdown population

Stable main window wiring

Stable last-run config restore

Zero legacy leaks

Zero Tkinter config errors

⭐ Phase 2 — Feature Hardening & Cross-Layer Unification

Goal: Every pipeline stage talks to the same controller/state layer in a standard way.

Lock down the contract for:

Stage config structure

Controller update methods

Pipeline execution events

Introduce an internal Event Bus (lightweight pub/sub) so:

Pipeline → GUI updates

GUI → controller updates

Errors → centralized logging

Make learning hooks part of the pipeline event system, not bolted-on.

Deliverables:

Unified AppController

Unified StageCard contract

EventBus (10–20 lines)

Logging standardization

Strong unit tests for resource discovery, config roundtrip, and payload building

⭐ Phase 3 — Intelligence Layer (Learning System)

Goal: The system gets smarter after each run.

Introduce a structured JSONL learning record format (already almost done)

Add ratings UI + rating storage

Auto-suggest:

Preferred models

Best samplers

Prompts often rated high

Add lightweight analytics (weekly, “what worked best?”)

This becomes the foundation for genuine ML-driven future features.

⭐ Phase 4 — Creative Expansion

Goal: Unlock advanced creative workflows.

Bring back Randomization Engine V2

Bring back Advanced Prompt Editor V2

Add node graph or modular editor (optional, but high value)

Add video generation stage (frames → ffmpeg)

⭐ Phase 5 — Distributed Cluster Controller

Goal: Local orchestrator sending jobs across multiple machines.

Introduce Job abstraction

Local Queue + Worker model

Optional remote worker mode (Proxmox nodes, Windows PCs, etc.)

Feeds natural extension:

nightly batch generation

long-run experiments

high-resolution video pipelines

3. Systems to Prevent Regression & Accelerate Development

This is where most of your pain comes from. You need infrastructure for fast iteration.

I’d put in these systems IMMEDIATELY:

System A — Snapshot-Based Development

You already do this manually — formalize it.

Every time you begin a PR:
Create a snapshot zip with timestamp.

Every time you finish a PR:
Store a snapshot.

ChatGPT + Codex always diff against the last snapshot.

Never trust Codex to navigate the repo unsupervised.

This is the single greatest guardrail for AI-assisted development.

System B — PR Templates That Prevent Scope Creep

PRs must be:

SMALL

Atomic

File-scoped

Deterministic

PR template should include:

Required files to modify (explicit paths)

Forbidden files (list them)

Existing tests that must not break

One-sentence definition of “done”

You already use something like this; it just needs tightening.

System C — File Locking System

Codex often drifts; the cure is:

You mark a list of core, untouchable files (e.g., executor, main_window_v2, theme_v2).

Codex cannot modify them unless you explicitly unlock.

This is PROFOUNDLY important.

System D — Contract Tests

We add a tiny but powerful set of unit tests:

StageCard contract

Controller contract

Resource discovery contract

Last-run config contract

Payload building contract

These act as permanent anchors so AI agents cannot break core behaviors.

System E — Surgical PR Prompting

Instead of letting Codex wander:

You feed Codex:

EXACT files

EXACT diff goals

EXACT forbidden files

EXACT post-change test goals

One or two example code blocks

This prevents runaway diff corruption.

System F — “Controller First” Architecture

Every UI action routes through the controller.
This stops the “GUI spaghetti” problem that Tkinter projects fall into.

The rule is:

GUI never touches the pipeline directly:
GUI → controller → pipeline → executor → WebUI

This is how you prevent fragmentation.

4. Guardrails for a Developer With Limited Coding Background

If someone is vibe-coding with AI agents, they need rigid scaffolding but flexible execution.

Here are the guardrails:

Guardrail 1 — Codex Only Works File-by-File

Never ask an LLM to modify multiple files unless you want chaos.

Instead:

Single PR = single file or cluster of tightly-related files.
(Controller + one GUI card is okay. Controller + 12 GUI cards is not.)

This prevents runaway restructuring, indentation breakage, and “phantom” imports.

Guardrail 2 — You MUST Give Codex Examples

Codex behaves 5× better when you give it:

an exact code block (correct)

an incorrect block to replace

or a template to follow

You’ve already seen this:

When you gave it “drop-in patch” style instructions, it stayed surgical.

This is the golden rule of AI-assisted coding:

Codex imitates your clarity. Give it clean, explicit examples and it will produce clean, explicit code.

Guardrail 3 — Codex Never Creates Classes or Large Systems Alone

AI agents cannot safely create entire controllers, GUI classes, or pipeline engines from scratch.

So the rule is:

Codex can extend a class. Codex cannot invent one.

E.g., good:

“Add this method to AppController following this example”

“Fill in this TODO inside this exact function”

Bad:

“Rewrite the controller”

“Make a new GUI system”

“Refactor the pipeline”

Keep Codex on rails.

Guardrail 4 — All New Code Goes Behind a Contract

Before adding a feature, define:

exact method signatures

exact event flow

exact data structures

exact GUI callback contract

exact pipeline behavior

This gives AI a target.

A contract transforms vague work into deterministic work.

Guardrail 5 — Never Let Codex Modify a File Twice in a Row Without Human Diff Review

This is critical.

Pattern:

You give Codex patch

Codex applies patch

You check the diff

Only if diff is perfect, you allow the next patch

Otherwise it will snowball into a disaster.

Codex is powerful but not consistent across runs — enforcing human diff checkpoints removes drift.

Guardrail 6 — Use “Forbidden Files Lists” Aggressively

These files must be treated like holy relics:

executor.py

healthcheck.py

webui_process_manager.py

main_window_v2.py

theme_v2.py

pipeline_runner_v2.py

resource_service & last run store

Any pipeline dataclasses

Your PR template should contain:

❌ Forbidden files (do not touch them)
✔️ Allowed files
✔️ Allowed tests
✔️ Explicit filenames Codex may modify

This instantly stops Codex from wandering into V1 code or rewriting core logic.

Guardrail 7 — Every PR Ends With Test Execution & Manual Flow Validation

Especially when vibe-coding with AI:

Run the GUI

Run a txt2img pipeline

Validate:

dropdowns populate

payload matches GUI selection

image is generated

learning hook writes JSONL

last-run config saves

This prevents regressions before they happen.

Guardrail 8 — Goal Size = Tiny

StableNew is extremely modular.

Use that to your advantage:

If something takes more than 20–30 minutes, break the PR into:

PR-A: controller wiring
PR-B: GUI card wiring
PR-C: payload contract update
PR-D: test updates

Small PRs = predictable AI behavior.

Guardrail 9 — Use Snapshots and Repo Inventory Every 12–24 Hours

You are already doing this.
But I would institutionalize it:

snapshot zip (timestamped)

generate repo_inventory.json

diff between snapshot and current before every PR

This gives you:

forensic visibility

recovery ability

regression detection

architectural clarity

Snapshotted repos are the magic cheat code for safe AI-driven development.

Guardrail 10 — You Decide When to Move Forward

Codex is a co-pilot, not a co-founder.

YOU:

Define contracts

Approve diffs

Approve architecture

Decide PR boundaries

Approve when V1 code is decommissioned

Codex:

Fills in code

Writes patches

Runs tests

Fixes errors

Implements wiring

This division of responsibility keeps things fast AND correct.

Pulling It All Together — If I Were Leading This Project
My plan would be:
Step 1 — Remove All V1 Files Immediately (archive/)

No split-brain system.

Step 2 — Harden the V2 GUI Scaffold

Targeted PR to make the skeleton bulletproof.

Step 3 — Make Resource Discovery + Last-Run Config Iron-Clad

Dropdown correctness = zero pipeline errors.

Step 4 — Pipeline Payload Contracts

Strict, typed, validated.

Step 5 — Controller Unification + Event Bus

To prevent spaghetti callbacks.

Step 6 — Tests for Every Contract

Controller tests
GUI wiring tests
Payload-building tests
Healthcheck tests

Step 7 — Bring in Learning System

Clean, straightforward, JSONL writer + rating UI.

Step 8 — Bring in Randomization V2

Now that pipeline is stable.

Step 9 — Prompt Editor V2

Use same controller/event bus system.

Step 10 — Video & Multi-Node Compute

Once core is stable and extensible.

Final Note — You’re Building a Legit Platform

StableNew has:

a pipeline engine

a GUI

an orchestrator

a learning system

randomization

cluster plans

video plans

This is no longer a hobby project.

It’s evolving into a real creative production system.

With these guardrails, you’ll move fast, safe, and confidently, without Codex blowing up the repo again.

If you want, I can now:

✅ Rewrite the PR template to enforce all these guardrails
✅ Build an “AI Safety Layer” doc for Codex
✅ Generate a development process map (ASWF-style)
✅ Turn your Roadmap into a FigJam diagram
🟦 Or start the next PR

### Related references

For deep dives into sequencing invariants, refer to [Stage_Sequencing_V2_5_V2-P1.md](Stage_Sequencing_V2_5_V2-P1.md).
