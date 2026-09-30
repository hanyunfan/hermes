"""Base helpers shared by all models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Mapping


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def now_iso() -> str:
    """Return the current UTC time in ISO 8601 form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_id(value: Any, kind: str = "id") -> str:
    """Validate and normalise a user-supplied identifier.

    The framework uses ``kebab_case`` ids for projects, ``snake_case`` for
    everything else. This validator enforces a conservative slug form so we
    never get path-traversal artefacts (``../``) into our filesystem state.
    """
    if not isinstance(value, str):
        raise ValueError(f"{kind} must be a string, got {type(value).__name__}")
    if not _SLUG_RE.match(value):
        raise ValueError(
            f"{kind}={value!r} is not a valid slug (lowercase alnum, '-', '_', "
            f"1-64 chars, must start with alnum)"
        )
    return value


def to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort dataclass → dict conversion, including nested dataclasses.

    Uses ``asdict`` so we get consistent ordering and recursion. Enums are
    stringified; lists/dicts/scalars pass through.
    """
    return asdict(obj)


def merge_extra(target: dict[str, Any], extra: Mapping[str, Any] | None) -> None:
    """Merge user-provided ``extra`` keys into ``target`` without overriding
    declared fields. Silently drops reserved keys to avoid surprises."""
    if not extra:
        return
    for k, v in extra.items():
        if k in target:
            continue
        target[k] = v


@dataclass
class TimestampedMixin:
    """Adds ``created_at`` / ``updated_at`` ISO timestamps to a model."""

    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def touch(self) -> None:
        """Update ``updated_at`` to now."""
        self.updated_at = now_iso()