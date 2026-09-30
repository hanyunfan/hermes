"""Enums used across the framework."""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states for a single :class:`GenerationJob`."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ShotStatus(str, Enum):
    """Lifecycle states for a :class:`Shot` through the pipeline.

    Mirror of :class:`JobStatus` but scoped to the shot, so a shot can carry
    multiple jobs (initial + retries) without overwriting its own state.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ContinuityAspect(str, Enum):
    """Aspects the Continuity Manager checks between shots/scenes."""

    FACE = "face"
    HAIR = "hair"
    CLOTHING = "clothing"
    AGE = "age"
    BODY = "body"
    PROPS = "props"
    LOCATION = "location"
    LIGHTING = "lighting"


class GenerationState(str, Enum):
    """Top-level state machine for an entire generation run."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"