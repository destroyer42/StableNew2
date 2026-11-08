# Publication validation and evidence boundary

Publication packages the existing assessment at source SHA `3399f8032182b65bd904f8f27818d927909cd6a3`; no application source, tests, dependencies, runtime configuration or operator data are part of the PR.

- 73 unique confirmed decision rows; UX-DEC-005A and 007A included, UX-DEC-072 excluded.
- 39 source references checked for target existence, valid lines and unchanged assessment-source hashes.
- Portable Markdown links use repository-relative paths and GitHub line fragments.
- Aggregate scoped diff reviewed; `git diff --check` checked before commit.
- Existing settings bytes/diff retained; no user settings or baseline diff included.
- Prior 141 + 7 non-GUI test evidence is reused at the unchanged application-source SHA. No application tests or GUI tests were rerun for publication.
- CI was not requested or awaited for this docs-only publication, per owner instruction. Repository-triggered checks may run automatically; no required check or branch rule was disabled or bypassed.
- Independent review, current Windows usability/DPI and physical model qualification remain unverified. The retained Tk incident is a redacted excerpt, not a passing result.

Research usage is retained in USAGE.md. Publication continues the same package/session; any final publication usage is recorded separately in the PR body so the historical research measurement is not silently rewritten.
