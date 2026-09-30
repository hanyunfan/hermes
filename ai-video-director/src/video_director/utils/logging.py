"""Logging helpers. Keep it stdlib-only so we don't need a runtime dep."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-5s %(name)s :: %(message)s"


def get_logger(name: str, level: int | str | None = None) -> logging.Logger:
    """Return a configured logger.

    Uses a single handler; repeated calls with the same name do not duplicate.
    Level resolution: explicit arg > ``VIDEO_DIRECTOR_LOG_LEVEL`` env > INFO.
    """
    logger = logging.getLogger(name)
    if getattr(logger, "_vd_configured", False):
        if level is not None:
            logger.setLevel(level)
        return logger
    if level is None:
        env = os.environ.get("VIDEO_DIRECTOR_LOG_LEVEL")
        level = int(env) if env and env.isdigit() else logging.INFO
    logger.setLevel(level)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
        logger.addHandler(h)
    logger.propagate = False
    logger._vd_configured = True  # type: ignore[attr-defined]
    return logger


def setup_file_logging(log_path: str | os.PathLike[str], level: int | str | None = None) -> logging.FileHandler:
    """Add a file handler to the named logger. Returns the handler."""
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    logger = get_logger("video_director", level)
    handler = logging.FileHandler(p, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
    logger.addHandler(handler)
    return handler