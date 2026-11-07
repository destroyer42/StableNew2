"""The journey-control exception contract shared by the drivers and the journey runners.

A journey stops for exactly three reasons that are decisions, not symptoms: its own assertion failed (``JourneyAbort``), a
prerequisite is unmet (``JourneyHold``) or a safety or resource condition forbids continuing (``JourneyNoGo``).  All three
derive from ``JourneyControl``.  A polling wait must let a ``JourneyControl`` propagate at once: treating it as a transient
probe error would hide a stop condition until the wait times out (the IMG-Q0 physical attempt of 2026-11-05 waited 16
minutes after its resource monitor had tripped).

The module has no imports from the drivers or runners, so ``tk_driver`` and ``golden.session`` can both depend on it.
"""

from __future__ import annotations


class JourneyControl(RuntimeError):
    """Base of every deliberate journey stop; never a transient probe failure."""


class JourneyAbort(JourneyControl):
    """The journey cannot continue; the message is the failed assertion."""


class JourneyHold(JourneyControl):
    """A prerequisite is unmet (not a product failure)."""


class JourneyNoGo(JourneyControl):
    """A safety or resource condition forbids continuing."""


__all__ = ["JourneyAbort", "JourneyControl", "JourneyHold", "JourneyNoGo"]
