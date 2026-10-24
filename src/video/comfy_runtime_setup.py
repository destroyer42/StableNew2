"""Toolkit-neutral facts about how ComfyUI is configured, what this process is running, and what that means (PR-VID-UX-340).

Four kinds of evidence are kept apart, because "Ready / Not ready" hides which one a statement rests on:

- **saved**: the ``comfy_command`` in Engine Settings (``presets/settings.json``);
- **environment**: ``STABLENEW_COMFY_COMMAND`` (a whitespace-split override that wins at startup, as documented);
- **active**: the command of the launcher ``ComfyProcessManager`` registered in *this* process, or ``None`` when no launcher
  exists (unknown, never "the same as saved");
- **observed**: whether the endpoint is serving and whether StableNew's own manager launched what is serving.

Nothing here reads a file, the environment or a process: ``ComfyProcessManager`` supplies the facts
(``read_comfy_launch_facts``) and this module only combines them. It adds no configuration authority and no lifecycle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

SOURCE_SETTINGS = "settings"
SOURCE_ENVIRONMENT = "environment"
SOURCE_NONE = "none"

ENV_COMMAND_VARIABLE = "STABLENEW_COMFY_COMMAND"

#: A ``PreflightGate.action`` value: the operator can repair this gate in Engine Settings > Video runtime (ComfyUI).
ACTION_FIX_COMFY_SETUP = "fix_comfy_setup"


@dataclass(frozen=True)
class ResolvedLaunchCommand:
    command: tuple[str, ...]
    source: str


def resolve_launch_command(
    saved: Sequence[str], environment: Sequence[str]
) -> ResolvedLaunchCommand:
    """The command startup uses: the environment override when it is set, otherwise the saved setting."""

    env = tuple(str(part) for part in environment if str(part))
    if env:
        return ResolvedLaunchCommand(env, SOURCE_ENVIRONMENT)
    stored = tuple(str(part) for part in saved if str(part))
    if stored:
        return ResolvedLaunchCommand(stored, SOURCE_SETTINGS)
    return ResolvedLaunchCommand((), SOURCE_NONE)


@dataclass(frozen=True)
class ComfyLaunchFacts:
    """Saved, environment and active launch evidence (see the module docstring)."""

    saved_command: tuple[str, ...] = ()
    environment_command: tuple[str, ...] = ()
    #: The registered launcher's command; ``None`` means this process has no launcher (unknown).
    active_command: tuple[str, ...] | None = None
    #: True only while a process ``ComfyProcessManager`` launched is running.
    owns_runtime: bool = False

    @property
    def resolved(self) -> ResolvedLaunchCommand:
        return resolve_launch_command(self.saved_command, self.environment_command)

    @property
    def effective_command(self) -> tuple[str, ...]:
        """What a startup of StableNew would launch (saved settings with the environment override applied)."""

        return self.resolved.command

    @property
    def effective_source(self) -> str:
        return self.resolved.source

    @property
    def environment_overrides_saved(self) -> bool:
        return bool(self.environment_command) and self.environment_command != self.saved_command

    @property
    def restart_pending(self) -> bool:
        """The launcher this process runs from differs from what a restart would use.

        Without a registered launcher there is nothing to compare, so nothing is claimed (never ``True`` by guess).
        """

        return self.active_command is not None and self.active_command != self.effective_command

    @property
    def command_in_force(self) -> tuple[str, ...]:
        """The command a launch from this process would actually run: the registered launcher's, else the effective one."""

        return self.active_command if self.active_command is not None else self.effective_command


def command_missing_flags(command: Sequence[str], required: Sequence[str]) -> tuple[str, ...]:
    present = set(command)
    return tuple(flag for flag in required if flag not in present)


def environment_override_notice(facts: ComfyLaunchFacts) -> str:
    """Why the Engine Settings command is not the one in force, or an empty string."""

    if not facts.environment_overrides_saved:
        return ""
    saved = (
        "Engine Settings holds a different launch command"
        if facts.saved_command
        else "Engine Settings holds no launch command"
    )
    return (
        f"The ComfyUI launch command comes from the {ENV_COMMAND_VARIABLE} environment variable, "
        f"which overrides Engine Settings ({saved.lower()}). To use the Engine Settings command, remove or "
        f"change that variable outside StableNew and restart StableNew; StableNew does not edit it."
    )


def restart_pending_notice(facts: ComfyLaunchFacts) -> str:
    """The saved/environment launch command is not what this session's launcher runs; empty when they agree."""

    if not facts.restart_pending:
        return ""
    return (
        "A ComfyUI launch change is saved but not applied: StableNew must restart to apply it. Until then this "
        "session's launcher still uses the earlier command, and a ComfyUI that is already running is not "
        "stopped or changed."
    )


def setup_notices(facts: ComfyLaunchFacts | None) -> tuple[str, ...]:
    if facts is None:
        return ()
    return tuple(
        text for text in (environment_override_notice(facts), restart_pending_notice(facts)) if text
    )


__all__ = [
    "ACTION_FIX_COMFY_SETUP",
    "ENV_COMMAND_VARIABLE",
    "SOURCE_ENVIRONMENT",
    "SOURCE_NONE",
    "SOURCE_SETTINGS",
    "ComfyLaunchFacts",
    "ResolvedLaunchCommand",
    "command_missing_flags",
    "environment_override_notice",
    "resolve_launch_command",
    "restart_pending_notice",
    "setup_notices",
]
