"""Unattended work.

Everything in :mod:`tilt.agents` runs because something asked for it. These jobs
run because time passed. That is the whole difference, and it is what turns Tilt
from a notebook that answers into one that notices.

Each job is idempotent, bounded, and triggerable by hand — waiting until 3am to
discover a scheduled job is broken is not a debugging strategy.
"""

from __future__ import annotations

from tilt.jobs.runner import JOBS, run_job
from tilt.jobs.scheduler import Schedule
from tilt.jobs.scout import scout
from tilt.jobs.sweep import sweep
from tilt.jobs.themes import keep_themes
from tilt.jobs.vectors import embed_pending

__all__ = [
    "JOBS",
    "Schedule",
    "embed_pending",
    "keep_themes",
    "run_job",
    "scout",
    "sweep",
]
