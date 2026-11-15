# StableNew — Version-Controlled Project Instructions

## Purpose

This directory preserves the intended project instructions for the user's external Codex and Claude Code project configurations.

The files are reviewable, version-controlled mirrors. They do not replace or override the repository's operating contract.

## Authority

`AGENTS.md` is the repository operating-rule authority.

`docs/AI_MODEL_SELECTION.md` controls model/effort recommendations.

`docs/AGENT_OPERATING_MODEL.md` controls execution procedure.

`CODEX_PROJECT.md` and `CLAUDE_CODE_PROJECT.md` are non-authoritative external project-instruction mirrors.

A difference between a mirror and an external project configuration is configuration drift, not authority to disregard `AGENTS.md`.

## Files

- [Codex project instructions](CODEX_PROJECT.md)
- [Claude Code project instructions](CLAUDE_CODE_PROJECT.md)

## Synchronization

External project instructions may be stored outside Git. Editing these Markdown files does not update those configurations automatically.

When either file changes:

1. Review and merge the repository PR containing the proposed instruction change.
2. Open the corresponding external project configuration.
3. Copy the complete approved instruction body into that configuration, preserving headings and formatting.
4. Read the applied configuration back where the provider allows it.
5. Compare the applied instruction text with the repository file.
6. Record which repository SHA was applied and whether the effective instructions were verified.
7. Test a fresh project session with a benign authority-resolution question when possible.

Do not automate a project-settings change or access credentials without separate authorization.

## Sync state

Until an external setting has been verified, its sync state is **UNVERIFIED**.

A committed mirror is not evidence that the external configuration was updated.

The project owner may record the applied repository SHA and confirmation date in the relevant external project configuration or an appropriate non-authoritative project record.

Do not edit `STATUS.md` merely to record a routine external configuration sync.

## Future changes

Propose revisions through a normal repository PR.

Keep the always-loaded instruction mirrors small. Do not copy architecture catalogs, current holds, active roadmap details or model matrices into them.

Preserve provider-specific differences only when they serve actual supported host behavior.

If the two mirrors conflict with canonical authority, correct the mirror rather than creating another operating rule.

Prompt templates and on-demand workflows are maintained separately under `docs/ai/`.

## Verification limitation

The repository cannot prove that an external provider has loaded the intended instructions unless a supported provider-side inspection or behavioral verification is available.

Reports must distinguish:

- Repository file committed.
- External configuration applied.
- Effective provider instructions verified.

Do not treat those three states as interchangeable.
