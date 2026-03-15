Canonical_Document_Ownership_v2.6.md
Ownership Map, Precedence Table, and Contradiction Rules for StableNew v2.6

Status: Authoritative
Updated: 2026-03-12

---

## 1. Purpose

This document defines which agent or role owns each canonical document, what the
precedence is when documents appear to conflict, and how to handle contradictions
before they become tech debt.

---

## 2. Document Ownership Table

| Document | Tier | Owner | Update Trigger |
|---|---|---|---|
| `docs/ARCHITECTURE_v2.6.md` | 1 | ChatGPT (Planner) | Structural change approved by Human |
| `docs/GOVERNANCE_v2.6.md` | 1 | ChatGPT (Planner) | Process or rule change |
| `docs/StableNew Roadmap v2.6.md` | 1 | ChatGPT (Planner) | Phase transition or milestone |
| `docs/PROMPT_PACK_LIFECYCLE_v2.6.md` | 2 | ChatGPT (Planner) | PromptPack field or flow change |
| `docs/Builder Pipeline Deep-Dive (v2.6).md` | 2 | ChatGPT (Planner) | Builder stage change |
| `docs/DEBUG HUB v2.6.md` | 2 | ChatGPT (Planner) | Diagnostic pattern change |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | 2 | ChatGPT (Planner) | Coding standard or test policy change |
| `docs/PR_TEMPLATE_v2.6.md` | 2 | ChatGPT (Planner) | PR workflow change |
| `AGENTS.md` | 2 | ChatGPT (Planner) | Agent role or boundary change |
| `.github/copilot-instructions.md` | 2 | ChatGPT (Planner) | Executor brief update |
| `docs/StableNew_v2.6_Canonical_Execution_Contract.md` | 2 | ChatGPT (Planner) | NJR or queue contract change |
| `docs/DOCS_INDEX_v2.6.md` | Meta | ChatGPT (Planner) | Any doc addition, removal, or rename |
| `docs/Canonical_Document_Ownership_v2.6.md` | Meta | ChatGPT (Planner) | Ownership or precedence change |
| `docs/Learning_System_Spec_v2.6.md` | 3 | ChatGPT (Planner) | Learning subsystem change |
| `docs/Randomizer_Spec_v2.5.md` | 3 (retained) | ChatGPT (Planner) | Upgrade to v2.6 when randomizer is revised |
| `docs/Cluster_Compute_Spec_v2.5.md` | 3 (retained) | ChatGPT (Planner) | Upgrade to v2.6 when cluster is revised |
| `docs/Image_Metadata_Contract_v2.6.md` | 3 | ChatGPT (Planner) | Metadata field change |

---

## 3. Precedence Rules When Documents Appear To Conflict

When two documents give conflicting guidance, apply this order:

1. Tier 1 wins over Tier 2.
2. Tier 2 wins over Tier 3.
3. More-specific document wins over more-general when within the same tier.
4. Newer revision wins over older revision when document names and content
   otherwise match.
5. If conflict cannot be resolved by rules 1–4, escalate to ChatGPT (Planner)
   and Human before implementation continues.

In all cases, if a document is found contradicting a higher-tier document,
the lower-tier document must be updated in the same PR that introduced the
conflict. No PR may leave known contradictions unresolved.

---

## 4. Archive Rules

A document must be archived (moved to `docs/archive/`) rather than deleted when:

- It is superseded by a v2.6 equivalent but still contains historical spec detail.
- It covers a subsystem not yet migrated to v2.6.
- It is referenced by an active PR series as a baseline.

A document may be deleted only when:

- Its content is fully absorbed into a live document.
- No active PR spec or implementation depends on it.
- Human provides explicit approval.

---

## 5. Contradiction Checklist

Before submitting any PR that touches a doc file, verify:

- [ ] Does the edited doc reference any file that no longer exists? (fix the reference)
- [ ] Does the edited doc mandate a technology or pattern not used anywhere in the
      codebase, without a migration plan? (remove or qualify the mandate)
- [ ] Does the edited doc's tier-1 or tier-2 content contradict another tier-1
      or tier-2 document? (resolve before merging)
- [ ] Does the edited doc list a v2.5 spec where a v2.6 replacement now exists?
      (update the reference)
- [ ] Does the edited doc list a v2.6 document that does not yet exist?
      (either create it or mark the reference explicitly as "planned")

---

## 6. Retained v2.5 Documents

The following v2.5 documents are intentionally retained because no v2.6
replacement has been written yet. They remain active but must obey Tier 1–2
constraints:

| Document | Retained Until |
|---|---|
| `docs/Randomizer_Spec_v2.5.md` | A `Randomizer_Spec_v2.6.md` is produced |
| `docs/Cluster_Compute_Spec_v2.5.md` | A `Cluster_Compute_Spec_v2.6.md` is produced |

When refactoring these subsystems, the first deliverable must be the v2.6 spec
document before implementation begins.

---

**Document Status**: ✅ CANONICAL
**Last Updated**: 2026-03-12
