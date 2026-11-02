"""Motion asset inventory, Blender conversion and conditioning preview (PR-VID-MOTION-354).

Nothing here owns a queue, runner, job record or catalog: a converted clip is an ordinary video that enters the existing
Motion Library, and a conversion is operator-triggered, offline and CPU-only.
"""
