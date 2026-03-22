# UX Help and In-Product Guidance Executable Sequence v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: tabs, stage cards, settings, tooltips, help surfaces, operator guidance, inspectability

## 1. Purpose

StableNew has accumulated a large number of tabs, stage cards, settings, and
workflow pathways, but the product currently expects too much repo knowledge from
operators.

This sequence adds an in-product guidance layer so users can understand:

- what each tab and feature does
- how features interact with each other
- what the best use case is for each surface
- what configs/settings are currently active
- what a button actually does before clicking it
- how to safely modify settings and when not to

This is intended to produce a much more self-explaining, operator-friendly UX,
closer to the usefulness of the existing ADetailer hover-help pattern, but expanded
across the product in a structured way.

## 2. Product Goal

Target UX behavior:

- every major tab has a built-in explainer
- every major workflow surface has concise “what this is for” guidance
- important settings have hover help, not just labels
- high-risk buttons explain whether they queue, edit, mutate, or merely inspect
- users can see effective settings/configs, not just raw inputs
- the product becomes much more learnable without requiring external docs

## 3. Guiding Principles

- explain the workflow at the point of use
- default to short, practical guidance first; allow expansion for detail
- distinguish safe/inspect-only actions from queue/execute actions
- prefer plain-English operator explanations over internal jargon
- show effective config summaries where hidden defaults matter
- help text should reflect actual repo behavior, not aspirational behavior

## 4. Recommended PR Sequence

### PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers

Purpose:

- give each major tab a built-in overview explaining what it is for, when to use
  it, and how it differs from adjacent tabs

Primary outcomes:

- add overview/help panels for major tabs such as:
  - Pipeline
  - Review
  - Learning
  - Staged Curation
  - Video-related surfaces
- each panel explains:
  - purpose
  - primary use cases
  - what inputs it expects
  - what actions it can trigger
  - how it connects to other tabs

Recommended UX pattern:

- collapsible `About This Tab` panel at the top or side of each major surface
- compact default state with expandable detail

Primary file targets:

- `src/gui/views/*`
- tab frame modules across Review / Learning / Pipeline / Video surfaces
- shared help-panel widgets if created

Execution gate:

- a new user can open a major tab and immediately understand what it does and
  when they should use it

### PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained

Purpose:

- make buttons and actions much more understandable before the user clicks them

Primary outcomes:

- add hover help / inline descriptions for action buttons such as:
  - queue
  - generate
  - reprocess
  - edit in review
  - import to learning
  - save feedback
- explicitly explain whether a button:
  - opens an edit surface
  - immediately queues work
  - writes metadata
  - only inspects/compares
- add consistent wording for high-risk or irreversible-feeling actions

Primary file targets:

- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- pipeline/video tab files
- shared tooltip helpers

Execution gate:

- button semantics are no longer ambiguous to the operator

### PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions

Purpose:

- expand the useful hover-help model seen in the ADetailer settings card across
  the broader settings/card system

Primary outcomes:

- add tooltip/help coverage for important settings in stage cards:
  - txt2img
  - img2img
  - adetailer
  - upscale
  - video-related settings
- each major field explains:
  - what it controls
  - when to raise/lower/change it
  - common tradeoffs
  - whether it mainly affects quality, speed, fidelity, or risk
- identify “normal/default-safe” ranges where appropriate

Primary file targets:

- stage card GUI modules
- tooltip/help mapping helpers
- settings-card rendering helpers

Execution gate:

- users can hover key settings and understand what they do without leaving the app

### PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used

Purpose:

- surface the effective config that the product is actually using, especially
  where settings are inherited, defaulted, merged, or stage-specific

Primary outcomes:

- add read-only `Effective Settings` summaries on important surfaces
- explain where values came from:
  - source artifact metadata
  - current stage card baseline
  - built-in defaults
  - target-stage presets
- make it visible when values are inherited vs explicitly changed

Primary file targets:

- Review tab
- Learning / Staged Curation
- video settings/results surfaces
- config/metadata adapter helpers

Execution gate:

- the operator can tell not just what value is active, but why that value is active

### PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations

Purpose:

- explain when to use each workflow pathway so users stop guessing which tab or
  tool is appropriate

Primary outcomes:

- add built-in guidance such as:
  - when to use Review vs Learning
  - when to use Staged Curation vs direct Review
  - when to use `Queue Now` vs `Edit in Review`
  - when to use discovered/imported review flows
  - when secondary motion is appropriate in video workflows
- add simple decision-support copy in the UI

Recommended UX pattern:

- `When should I use this?` expandable guidance blocks
- inline recommendations near ambiguous multi-path features

Primary file targets:

- Review / Learning / Staged Curation / Video surfaces
- shared workflow-guidance helpers

Execution gate:

- the product helps the user choose the right pathway instead of forcing them to
  infer architecture from labels

### PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish

Purpose:

- tie the above work together into a coherent, polished guidance layer

Primary outcomes:

- add a lightweight `Help Mode` or contextual help toggle if needed
- standardize terminology across tabs, buttons, and help text
- reduce inconsistent wording like generate/queue/run/reprocess where semantics differ
- improve clarity, density, and readability of help text/tooltips
- align with metadata inspection and effective-config surfaces

Primary file targets:

- shared GUI/help widgets
- multiple tab/view modules
- terminology/constants helpers if introduced

Execution gate:

- guidance feels cohesive across the product rather than added piecemeal

## 5. Recommended Order

1. `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`
2. `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
3. `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`
4. `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`
5. `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`
6. `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`

## 6. Validation Expectations

At completion, validate these operator questions can be answered in-product:

- What does this tab do?
- When should I use this instead of a different tab?
- What exactly happens if I click this button?
- What settings are currently being used?
- Where did those settings come from?
- How do I change them safely?
- What is the normal use case for this feature?

## 7. Recommendation

Treat this UX/help sequence as a first-class usability tranche, not cosmetic polish.

The product now has enough workflow complexity that explanation, inspectability,
and embedded guidance are part of core functionality, not optional niceties.
