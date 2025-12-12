# Codex Run Sheet — PR-GUI-V2-LEARNING-RUNNER-STUB-001

Paste the following into Codex chat to implement this PR. Do not exceed the described scope.

---

Implement PR-GUI-V2-LEARNING-RUNNER-STUB-001 as specified in the accompanying PR document.

Key points:

1) Add learning models under src/learning/:
   - learning_plan.py
   - learning_runner.py
   - learning_feedback.py
   - learning_adapter.py

2) Keep these modules completely free of GUI, Tk, pipeline runner, or network dependencies.

3) Provide a controller hook in src/controller/pipeline_controller.py that can lazily construct and return a LearningRunner instance for tests:
   - Do not invoke this from existing pipeline methods yet.
   - Expose a small helper for tests (e.g., get_learning_runner_for_tests).

4) Add GUI stub methods in src/gui/main_window.py:
   - _start_learning_run_stub(self)
   - _collect_learning_feedback_stub(self)
   These must not be wired to buttons or menus yet and must not alter existing behavior.

5) Add tests under tests/learning/:
   - test_learning_plan_factory.py
   - test_learning_runner_stubs.py
   - test_learning_feedback_packaging.py
   - test_learning_adapter_stub.py

6) Required test commands:
   - pytest tests/learning -v
   - pytest -v

7) Constraints:
   - No GUI visual changes.
   - No pipeline behavior changes.
   - No LLM or external calls.
   - No randomizer modifications.
   - Only touch the allowed files listed in the PR document.

Report back with:
   - A summary of changes (files touched, key classes/functions).
   - Full pytest output for the commands above.
