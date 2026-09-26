---
name: technology-research
description: Research a current image/video/AI/runtime technology for StableNew and produce a bounded evidence-based qualification recommendation without integrating it.
---
Follow `AGENTS.md`.

Use primary/upstream documentation, repositories, release notes, model cards,
licenses, and reproducible target-hardware evidence where possible.

Evaluate only dimensions relevant to the decision, typically:
- capability/quality for the requested use case;
- Windows/local execution viability;
- RTX 4070 Ti 12 GB VRAM / 32 GB RAM target fit when applicable;
- dependency/runtime footprint;
- Comfy/native/Diffusers integration fit;
- backend neutrality and StableNew contract fit;
- license/distribution restrictions;
- maintenance/community/upstream status;
- qualification cost and reversible next experiment.

Separate:
- established facts;
- community evidence;
- inference;
- unknowns requiring a bounded experiment.

Do not install models, mutate the environment, or add a production backend as
part of research unless separately authorized.

End with the smallest next qualification step that could change the decision.
