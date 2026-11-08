# StableNew UX-850-R1 research handoff

**Recommendation:** end the broad Learning questionnaire and select a bounded foundation tranche. Build around existing generation profiles, PromptPacks, editing, Storyboards, History and Learning evidence services. The first candidate is **GUI-FOUNDATION-851**, gated by a current reproduction and a valid no-code exit.

**Baseline:** local `main` at `3399f8032182b65bd904f8f27818d927909cd6a3`; existing settings change preserved. Runtime and application source are unchanged. This documentation package is published on `codex/ux-850-r1-integrated-assessment` under the owner’s subsequent authorization; merge and implementation remain unauthorized.

| Read | Purpose |
|---|---|
| [Assessment](ASSESSMENT.md) | Findings, feasibility, state ownership, risks, challenge and evidence limits |
| [Integrated experience](EXPERIENCE_DESIGN.md) | Current/proposed screen maps, five complete journeys, paper layouts and Windows acceptance |
| [Delivery plan](DELIVERY_PLAN.md) | First candidate contract, dependencies, subsequent bounded packages and owner decisions |
| [73-decision matrix](DECISION_TRACEABILITY.md) | One row for every confirmed decision, with current-source references |
| [CSV matrix](DECISION_TRACEABILITY.csv) | Reusable traceability data |
| [Owner register (wording preserved)](OWNER_DECISIONS.md) | Supplied product-intent source, including pending UX-DEC-072 |
| [Source index](SOURCE_INDEX.md) | Exact path/line anchors; JSON companion contains file hashes |
| [Usage](USAGE.md) | Measured session/time-window telemetry and calibration limits |

**Demonstrated:** 148 selected non-GUI tests passed (141 + 7). Logs: [core contracts](pure-tests.txt), [Library projection](library-tests.txt). No qualification verdict granted. A separately selected Tk layout test hit a Windows exception; a [redacted incident excerpt](focused-tests.txt) is retained and no desktop-pass claim is made.

**Limits:** partial Comprehensive assessment; live usability/DPI, operator timing, independent second reviewer and complete control/CI audit remain unverified. The report is sufficient to choose a bounded next package, not to claim full redesign or implementation readiness. It authorizes no production code, inference, physical run, publication or merge.
