# PR-CLEANUP-LEARN-038: Tech Debt Removal and Contract Cleanup

**Status**: 🟡 Specification
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The Learning subsystem currently contains obsolete helpers, controller overload, placeholder execution paths, and duplicated assumptions left over from earlier partial implementations.

## Goals
1. Remove superseded Learning helpers and placeholder paths.
2. Tighten module boundaries after the prior PRs land.
3. Leave the Learning subsystem cleaner and smaller.

## Allowed Files
- learning subsystem files touched by PR-031 through PR-037
- learning docs/tests only

## Implementation Plan
1. Remove dead compatibility helpers once replacement paths are green.
2. Consolidate naming and contracts.
3. Update docs to reflect final subsystem shape.

## Testing Plan
- targeted regression suite
- Golden Path regression check

## Next Steps
Execute after PR-037.
