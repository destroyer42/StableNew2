# Future Learning Roadmap (2025-11-26_1115)


# Future Learning Roadmap (PR-3S → PR-3W)

This document defines the post–PR‑3R extended roadmap for the Learning subsystem.  
These items are **not** scheduled for immediate implementation and are provided as forward-looking design anchors.

---

## PR‑3S — Statistical Regression & Trend Modeling

Introduce statistical regression over Learning records:
- Linear and polynomial regression
- Rolling-window weighted averages
- Confidence intervals
- Trend slope reporting

Purpose: give users predictive insights into how parameters behave across ranges.

---

## PR‑3T — Bayesian Optimization Mode

Add a probabilistic optimizer that:
- Suggests next test values (exploration/exploitation)
- Works with discrete + numeric parameters
- Integrates with adaptive loop (PR‑3L)

Purpose: accelerate convergence on optimal settings.

---

## PR‑3U — Multi‑Experiment Merge & Meta‑Analysis

Combine results across multiple experiments:
- Per‑prompt patterns
- Cross‑prompt generalizations
- Consistency scoring

Purpose: evolve StableNew into a knowledge-accumulating system.

---

## PR‑3V — GPU‑Accelerated Analytics Backend

Use GPU acceleration (CuPy/CUDA) to:
- Evaluate large X/Y grids faster
- Generate heatmaps quickly
- Support scaling to 1000+ variant analysis

Purpose: support high-throughput learning workloads.

---

## PR‑3W — Auto‑Scheduler & Per‑Prompt Optimization Profiles

Learn optimal sampler/scheduler/CFG/steps per prompt type:
- Saved as reusable JSON style profiles
- Auto-applied when prompts match known patterns
- Exportable/importable presets

Purpose: enable fully automated, real-world optimization flows.

---

## Summary Table

| PR | Feature Area | Goal |
|----|--------------|------|
| 3S | Regression modeling | Establish statistical trend basis |
| 3T | Bayesian optimization | Intelligent suggestion of next candidates |
| 3U | Meta-analysis | Cross-experiment insights |
| 3V | GPU analytics | Scale and speed |
| 3W | Auto-scheduler profiles | Real-world automation |

These items remain in the **Future Work** queue until PR‑3A → PR‑3R are stabilized. 
