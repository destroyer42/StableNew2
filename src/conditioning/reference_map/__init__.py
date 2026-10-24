"""Operator-invoked reference-map preparation (PR-IMG-CNET-230).

Turns one reference image into a pre-rendered ControlNet map (Canny, relative depth or OpenPose) that the operator then
saves into the existing ``models/OpenPose`` conditioning-image library and explicitly attaches to a ``controlnet.v1``
unit. Preparation never builds a job, never talks to a backend and never changes a contract: the compiler later freezes
the saved image exactly like any hand-supplied map.
"""
