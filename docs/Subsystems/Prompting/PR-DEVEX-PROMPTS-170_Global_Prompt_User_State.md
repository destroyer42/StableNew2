# Global Prompt user state

Saved Global Positive and Global Negative prompt **text** is per-user StableNew
state. It is not repository content and not product configuration.

## Storage

| Item | Owner |
|---|---|
| Prompt text | `<GlobalPrompts>/global_positive.txt`, `<GlobalPrompts>/global_negative.txt` |
| Enabled flags (`global_positive_enabled`, `global_negative_enabled`) | the existing settings authority (`presets/settings.json` via `ConfigManager`) |
| Code-defined defaults | `DEFAULT_GLOBAL_POSITIVE_PROMPT`, `DEFAULT_GLOBAL_NEGATIVE_PROMPT` in `src/utils/config.py` |

`<GlobalPrompts>` is resolved by `resolve_global_prompt_dir`
(`src/prompting/global_prompt_paths.py`), a pure function with no filesystem
side effects. Precedence:

1. an explicit path (`ConfigManager(..., global_prompt_dir=...)`);
2. the `STABLENEW_GLOBAL_PROMPT_DIR` environment variable;
3. the platform user-data directory:
   - Windows: `%LOCALAPPDATA%\StableNew\GlobalPrompts`, or
     `~\AppData\Local\StableNew\GlobalPrompts` when `LOCALAPPDATA` is unset;
   - elsewhere: `$XDG_DATA_HOME/StableNew/GlobalPrompts`, or
     `~/.local/share/StableNew/GlobalPrompts`.

`ConfigManager` remains the only persistence API
(`get_/save_global_positive_prompt`, `get_/save_global_negative_prompt`,
`save_global_positive_state`, `save_global_negative_state`). The directory is
created lazily on the first write; constructing a `ConfigManager` creates
nothing.

## Semantics (unchanged)

- Text is UTF-8; saves strip surrounding whitespace.
- A blank Negative is a valid explicitly saved value. A blank Positive reads as
  the code-defined default (empty).
- With no stored file, a read returns the code-defined default and persists it.
- Preview/compilation freezes the effective policy into the immutable NJR; the
  executor consumes the frozen policy and does not read the stored files for
  modern NJRs. Replay and the explicit legacy fallback are unchanged.

## Retired repository files

`presets/global_positive.txt` and `presets/global_negative.txt` are no longer
tracked and are ignored by exact `.gitignore` rules. They are **not** a seed,
fallback or migration source: any local copy is never read. Historical
qualification documents that mention them describe evidence of their time.

## Test and journey isolation

- Tests that save prompt text inject `global_prompt_dir` explicitly, the same
  way PromptPack tests inject `packs_dir`.
- `tests/conftest.py::_isolate_global_prompt_user_state` is the single test-safety authority: it sets
  `STABLENEW_GLOBAL_PROMPT_DIR` to a per-test temporary directory for every pytest test, so default-constructed
  `ConfigManager()` call sites (`SidebarPanelV2.__init__`, the executor's legacy-fallback `Pipeline.__init__`)
  can never reach the per-user store. A test that sets the variable itself, or injects `global_prompt_dir`, wins.
  `tests/utils/test_config_manager_global_prompts.py` proves both directions: the redirection holds, and without
  it a default manager resolves toward the user-data location.
- `OperatorWorkspace.activate()` sets `STABLENEW_GLOBAL_PROMPT_DIR` to the workspace-owned `global-prompts`
  directory, creates it, and restores the prior environment exactly on exit, so no journey reads or writes the
  operator's real store.

## Acceptance

Deterministic proof lives in `tests/utils/test_global_prompt_paths.py`,
`tests/utils/test_config_manager_global_prompts.py`,
`tests/pipeline/test_global_prompt_policy.py` and
`tests/tools/test_operator_journey_harness.py`. Real-filesystem acceptance on
Windows used a temporary directory through `STABLENEW_GLOBAL_PROMPT_DIR`; no
backend, GPU or generation is involved.

## Known follow-up

`SidebarPanelV2` and the executor `Pipeline` construct `ConfigManager()` directly (the latter only for the
historical unfrozen-policy fallback). Injecting a manager into them would be a legitimate testability change but
is not needed for safety, which the root test fixture provides.
