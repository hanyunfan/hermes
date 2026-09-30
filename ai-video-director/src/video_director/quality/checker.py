"""Quality control for generated clips.

First-version checks are file-level (existence, decodability, sane duration,
resolution, fps, file size). The same surface accepts a vision-model QA
pluggable for the future.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from ..core.errors import QAFailure
from ..models import VideoClip
from ..utils.logging import get_logger


_LOG = get_logger("video_director.quality.checker")


@dataclass
class QARule:
    """One QA rule. ``predicate`` returns ``None`` for pass, or a string reason."""

    name: str
    predicate: Callable[[VideoClip, dict[str, Any]], Optional[str]]


@dataclass
class QAResult:
    """Outcome of running the QA suite against one clip."""

    shot_id: str
    passed: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"shot_id": self.shot_id, "passed": self.passed, "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QAResult":
        return cls(
            shot_id=str(data.get("shot_id", "")),
            passed=bool(data.get("passed", False)),
            notes=list(data.get("notes", []) or []),
        )


def _ffprobe_json(path: Path, ffprobe: str = "ffprobe") -> dict[str, Any] | None:
    """Return the ffprobe JSON for a media file, or None on failure."""
    cmd = [
        ffprobe, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        _LOG.warning("ffprobe failed for %s: %s", path, e)
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _stream_video(meta: dict[str, Any]) -> dict[str, Any] | None:
    for s in meta.get("streams", []) or []:
        if s.get("codec_type") == "video":
            return s
    return None


def _parse_dimensions(stream: dict[str, Any]) -> tuple[int, int]:
    """Parse ``WIDTHxHEIGHT`` from the stream dict. Returns (0, 0) on miss."""
    text = stream.get("width"), stream.get("height")
    if isinstance(text[0], int) and isinstance(text[1], int):
        return int(text[0]), int(text[1])
    return 0, 0


def _parse_fps(stream: dict[str, Any]) -> float:
    """Parse avg frame rate (``30000/1001``) into a float."""
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    if isinstance(raw, str) and "/" in raw:
        num, den = raw.split("/", 1)
        try:
            n = float(num)
            d = float(den)
            return n / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _parse_duration(meta: dict[str, Any]) -> float:
    fmt = meta.get("format") or {}
    raw = fmt.get("duration")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


# ---- built-in rules ------------------------------------------------------

def rule_exists(_clip: VideoClip, _meta: dict[str, Any]) -> Optional[str]:
    p = Path(_clip.path)
    if not p.exists():
        return f"file missing: {p}"
    if p.stat().st_size == 0:
        return f"file is empty: {p}"
    return None


def rule_min_size(_clip: VideoClip, _meta: dict[str, Any]) -> Optional[str]:
    p = Path(_clip.path)
    if p.exists() and p.stat().st_size < 256:
        return f"file suspiciously small ({p.stat().st_size} bytes)"
    return None


def rule_decodable(clip: VideoClip, meta: dict[str, Any]) -> Optional[str]:
    if not meta:
        return "ffprobe could not read file (corrupted or unsupported codec)"
    return None


def rule_min_duration(clip: VideoClip, meta: dict[str, Any]) -> Optional[str]:
    if clip.duration_sec > 0:
        target = clip.duration_sec
        actual = _parse_duration(meta)
        if actual and actual < 0.8 * target:
            return f"actual duration {actual:.2f}s < 80% of target {target:.2f}s"
    return None


def rule_min_resolution(clip: VideoClip, meta: dict[str, Any]) -> Optional[str]:
    stream = _stream_video(meta)
    if not stream:
        return None
    w, h = _parse_dimensions(stream)
    if w <= 0 or h <= 0:
        return f"invalid dimensions {w}x{h}"
    if min(w, h) < 144:
        return f"resolution too low: {w}x{h}"
    return None


def rule_min_fps(_clip: VideoClip, meta: dict[str, Any]) -> Optional[str]:
    stream = _stream_video(meta)
    if not stream:
        return None
    fps = _parse_fps(stream)
    if fps <= 0:
        return "invalid fps"
    if fps < 8:
        return f"fps too low: {fps:.2f}"
    return None


DEFAULT_RULES: list[QARule] = [
    QARule("exists", rule_exists),
    QARule("min_size", rule_min_size),
    QARule("decodable", rule_decodable),
    QARule("min_duration", rule_min_duration),
    QARule("min_resolution", rule_min_resolution),
    QARule("min_fps", rule_min_fps),
]


class QAChecker:
    """Apply a suite of :class:`QARule` against one or many clips."""

    def __init__(
        self,
        rules: list[QARule] | None = None,
        ffprobe: str = "ffprobe",
    ):
        # ``rules=None`` (default) -> use DEFAULT_RULES.
        # ``rules=[]`` (explicit empty) -> use no rules (useful for tests).
        self.rules = list(rules) if rules is not None else list(DEFAULT_RULES)
        self.ffprobe = ffprobe

    def check_clip(self, clip: VideoClip) -> QAResult:
        meta = _ffprobe_json(Path(clip.path), self.ffprobe) or {}
        # If the rule already had pre-filled info, propagate it
        if clip.width == 0 or clip.height == 0:
            stream = _stream_video(meta)
            if stream:
                w, h = _parse_dimensions(stream)
                if w and h:
                    clip.width = w
                    clip.height = h
        if not clip.fps:
            stream = _stream_video(meta)
            if stream:
                clip.fps = _parse_fps(stream)
        if not clip.duration_sec:
            clip.duration_sec = _parse_duration(meta)
        notes: list[str] = []
        for rule in self.rules:
            try:
                bad = rule.predicate(clip, meta)
            except Exception as e:  # noqa: BLE001 — never let a buggy rule kill QA
                bad = f"rule {rule.name!r} crashed: {e}"
            if bad:
                notes.append(f"{rule.name}: {bad}")
        clip.qa_passed = not notes
        clip.qa_notes = list(notes)
        return QAResult(shot_id=clip.shot_id, passed=clip.qa_passed, notes=notes)

    def check_clips(self, clips: Iterable[VideoClip]) -> list[QAResult]:
        return [self.check_clip(c) for c in clips]