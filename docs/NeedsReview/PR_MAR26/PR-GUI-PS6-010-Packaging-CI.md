# PR-GUI-PS6-010: Packaging + CI Hardening for PySide6

**Status**: ?? Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Finalize dependency pinning, CI, smoke tests, and release docs for Qt runtime.

## Allowed Files
- requirements*.txt / pyproject.toml
- .github/workflows/**
- tests/smoke/**
- docs/PR_MAR26/PR-GUI-PS6-010-Packaging-CI.md
- docs/StableNew_Coding_and_Testing_v2.6.md

## Forbidden Files
- src/pipeline/**
- src/queue/**

## Plan
1. Pin PySide6-related dependencies.
2. Add CI gui test strategy and smoke workflow.
3. Add release checklist updates.

## Tests
- CI smoke + GP suite

## Criteria
Fresh environment install/start/test passes deterministically.
