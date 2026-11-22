"""Names and first-use contents of the Evaluation Plans workspace."""

from pathlib import Path

EVAL_PLANS_FOLDER = "eval_plans"
EVAL_PLAN_KINDS = ("video", "image", "qualification", "templates", "_imported")
EVAL_PLANS_README = """# Evaluation Plans

- `video/`: video suites, named `YYYYmmdd_slug.suite.json`. The JSON schema is
  `stablenew.video-eval-suite.v1`. Image paths are relative to the suite or absolute.
- `image/`: image comparison plans, named `YYYYmmdd_slug.plan.json`.
  Use the schema declared by the tool that reads the plan.
- `qualification/<tool>/`: frozen plans using each tool's existing schema and authorization rules.
- `templates/`: starting points from the StableNew runbook examples. Copy a
  template to the appropriate plan folder before editing it.
- `_imported/imports.jsonl`: provenance for imported suites.

Video runs and reports are in `<Output>/video_eval/<run_id>/`. Learning experiment sessions
are not eval plans. They remain in the Learning Library and `data/learning/experiments/`.

See `docs/runbooks/eval_plans.md` in the StableNew checkout.
"""


def initialize_eval_plans(root: Path) -> None:
    for kind in EVAL_PLAN_KINDS:
        (root / kind).mkdir(parents=True, exist_ok=True)
    try:
        with (root / "README.md").open("x", encoding="utf-8") as stream:
            stream.write(EVAL_PLANS_README)
    except FileExistsError:
        pass
