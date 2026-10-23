"""Offline AI Assist (PR-AI-110): typed, validated, advisory suggestions from a locally stored model.

The package is an authoring aid that sits *before* Intent. It produces suggestions the operator may accept into an editing
buffer; it never produces an executable job and imports nothing from the queue, repository, job service, runner, NJR core
or any GUI module (enforced by the ``ai_assist_forbidden_imports`` architecture ratchet). Inference runs only as a
short-lived, contained, CPU-only child of a pinned, hash-verified runtime; nothing here downloads, installs or runs a model
on import.
"""
