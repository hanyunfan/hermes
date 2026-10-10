"""Validate a loaded :class:`Imports` bundle.

Every problem is reported as a :class:`CheckResult`, never raised. The
:class:`CheckReport` returned by :func:`check_imports` separates
ERRORs (must fix before build) from WARNINGs (advisory).

Rules implemented (mirror ``prompts/grok_storyboard.md``):

  * Slug format on every ID
  * Reference integrity: ``scene_id``, ``character_id``, ``previous_shot``,
    ``next_shot``, dialogue ``shot_id``/``character_id``
  * Chain integrity: ``shot N.next_shot = shot M`` implies
    ``shot M.previous_shot = shot N``
  * shot count <= 150
  * non-empty prompt/negative_prompt
  * duration_sec in [2, 15]
  * shot_index monotonic within scene, starting at 1
  * unique shot_id, unique character_id, unique scene_id
  * dialogue shot_id/character_id resolution
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

from .loader import Imports, ImportedCharacter, ImportedScene, ImportedShot


class CheckSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class CheckResult:
    severity: CheckSeverity
    code: str  # short stable identifier, e.g. BROKEN_CHAIN
    message: str  # human-readable, includes entity ids
    location: str = ""  # file or entity path, e.g. "shots[42].previous_shot"
    fix_hint: str = ""  # optional one-line guidance

    def render(self) -> str:
        loc = f" [{self.location}]" if self.location else ""
        hint = f" — {self.fix_hint}" if self.fix_hint else ""
        return f"[{self.severity.value.upper():7}] {self.code}{loc}: {self.message}{hint}"


@dataclass
class CheckReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def errors(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity == CheckSeverity.ERROR]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity == CheckSeverity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def render(self) -> str:
        if not self.results:
            return "[ok] ALL CHECKS PASSED"
        lines = [r.render() for r in self.results]
        if self.errors:
            lines.append(f"[FAIL] {len(self.errors)} errors, {len(self.warnings)} warnings")
        else:
            lines.append(f"[ok] no errors, {len(self.warnings)} warnings")
        return "\n".join(lines)


_SLUG_RE = __import__("re").compile(r"^[a-z0-9_]+$")


def _check_slug(report: CheckReport, value: str, kind: str, location: str) -> None:
    if not value:
        report.add(CheckResult(
            CheckSeverity.ERROR,
            "EMPTY_SLUG",
            f"{kind} is empty",
            location=location,
            fix_hint=f"set a non-empty {kind} like 'lin_xi'",
        ))
        return
    if not _SLUG_RE.match(value):
        report.add(CheckResult(
            CheckSeverity.ERROR,
            "INVALID_SLUG",
            f"{kind}={value!r} must match [a-z0-9_]+",
            location=location,
            fix_hint="lowercase letters, digits, and underscores only; no spaces or hyphens",
        ))


def check_imports(bundle: Imports) -> CheckReport:
    """Run every rule. Never raises; everything goes into the report."""
    report = CheckReport()

    _check_story(bundle, report)
    _check_characters(bundle, report)
    _check_scenes(bundle, report)
    _check_shots(bundle, report)
    _check_dialogues(bundle, report)
    _check_chain(bundle, report)

    return report


def _check_story(bundle: Imports, report: CheckReport) -> None:
    story = bundle.story
    if story is None:
        report.add(CheckResult(
            CheckSeverity.ERROR, "STORY_MISSING",
            "story.json is missing or failed to load",
        ))
        return
    _check_slug(report, story.story_id, "story.story_id", "story.json")
    if not story.title:
        report.add(CheckResult(
            CheckSeverity.WARNING, "EMPTY_TITLE",
            "story.title is empty",
            location="story.json",
        ))
    if story.target_duration_sec <= 0:
        report.add(CheckResult(
            CheckSeverity.WARNING, "NO_TARGET_DURATION",
            "story.target_duration_sec is 0 (or unset)",
            location="story.json",
        ))


def _check_characters(bundle: Imports, report: CheckReport) -> None:
    seen: set[str] = set()
    project_root = bundle.project_dir
    for i, ch in enumerate(bundle.characters):
        loc = f"characters[{i}]"
        _check_slug(report, ch.character_id, "character_id", f"{loc}.character_id")
        if ch.character_id in seen:
            report.add(CheckResult(
                CheckSeverity.ERROR, "DUPLICATE_CHARACTER_ID",
                f"character_id={ch.character_id!r} appears multiple times",
                location=loc,
            ))
        seen.add(ch.character_id)
        if not ch.appearance:
            report.add(CheckResult(
                CheckSeverity.WARNING, "EMPTY_APPEARANCE",
                f"character {ch.character_id!r} has no appearance description",
                location=f"{loc}.appearance",
                fix_hint="add a 100-200 char Chinese appearance paragraph",
            ))
        # Verify reference_image points to a real file under the project.
        # If the path is wrong (e.g. character_id doesn't match the dir, or
        # file extension mismatch), the runner silently generates the video
        # WITHOUT a visual anchor — pure-prompt output looks nothing like
        # the intended character. Catch this at validate time.
        if ch.reference_image:
            ref_path = project_root / ch.reference_image
            if not ref_path.exists():
                report.add(CheckResult(
                    CheckSeverity.ERROR, "MISSING_REFERENCE_IMAGE",
                    f"character {ch.character_id!r}.reference_image={ch.reference_image!r} does not exist",
                    location=f"{loc}.reference_image",
                    fix_hint=(
                        f"either place the image at this path, or change "
                        f"reference_image to point to your actual file "
                        f"(likely under imports/references/<dir>/hero.jpg)"
                    ),
                ))
            else:
                # Cross-check: is the dir name == character_id?
                # Common error: Grok names the dir differently than the character.
                # E.g. character_id='young_woman' but file at references/1/hero.jpg
                parts = ch.reference_image.split("/")
                # look for .../references/<dir>/<filename>
                try:
                    ref_idx = parts.index("references")
                    ref_dir = parts[ref_idx + 1]
                except (ValueError, IndexError):
                    ref_dir = None
                if ref_dir and ref_dir != ch.character_id:
                    report.add(CheckResult(
                        CheckSeverity.WARNING,
                        "REFERENCE_DIR_MISMATCH",
                        f"character_id={ch.character_id!r} but reference_image lives in "
                        f"references/{ref_dir!r}/ — the directory name should match "
                        f"character_id (or the path should be imports/references/<character_id>/hero.ext)",
                        location=f"{loc}.reference_image",
                        fix_hint=(
                            f"either rename the dir to references/{ch.character_id}/ "
                            f"or update reference_image to match"
                        ),
                    ))


def _check_scenes(bundle: Imports, report: CheckReport) -> None:
    char_ids = {ch.character_id for ch in bundle.characters}
    seen: set[str] = set()
    for i, sc in enumerate(bundle.scenes):
        loc = f"scenes[{i}]"
        _check_slug(report, sc.scene_id, "scene_id", f"{loc}.scene_id")
        if sc.scene_id in seen:
            report.add(CheckResult(
                CheckSeverity.ERROR, "DUPLICATE_SCENE_ID",
                f"scene_id={sc.scene_id!r} appears multiple times",
                location=loc,
            ))
        seen.add(sc.scene_id)
        for j, cid in enumerate(sc.character_ids):
            if cid not in char_ids:
                report.add(CheckResult(
                    CheckSeverity.ERROR, "MISSING_REFERENCE",
                    f"scene {sc.scene_id!r} references character {cid!r} which does not exist",
                    location=f"{loc}.character_ids[{j}]",
                    fix_hint="add the character to characters.json or remove from scene",
                ))


def _check_shots(bundle: Imports, report: CheckReport) -> None:
    if len(bundle.shots) > 150:
        report.add(CheckResult(
            CheckSeverity.ERROR, "TOO_MANY_SHOTS",
            f"shot count {len(bundle.shots)} > 150",
            fix_hint="split into multiple stories or reduce shots/second",
        ))

    scene_ids = {sc.scene_id for sc in bundle.scenes}
    char_ids = {ch.character_id for ch in bundle.characters}
    seen: set[str] = set()
    per_scene_index: dict[str, list[int]] = defaultdict(list)

    for i, sh in enumerate(bundle.shots):
        loc = f"shots[{i}]"
        _check_slug(report, sh.shot_id, "shot_id", f"{loc}.shot_id")
        if sh.shot_id in seen:
            report.add(CheckResult(
                CheckSeverity.ERROR, "DUPLICATE_SHOT_ID",
                f"shot_id={sh.shot_id!r} appears multiple times",
                location=loc,
            ))
        seen.add(sh.shot_id)

        if sh.scene_id not in scene_ids:
            report.add(CheckResult(
                CheckSeverity.ERROR, "MISSING_REFERENCE",
                f"shot {sh.shot_id!r} references scene {sh.scene_id!r} which does not exist",
                location=f"{loc}.scene_id",
            ))

        for j, cid in enumerate(sh.character_ids):
            if cid not in char_ids:
                report.add(CheckResult(
                    CheckSeverity.ERROR, "MISSING_REFERENCE",
                    f"shot {sh.shot_id!r} references character {cid!r} which does not exist",
                    location=f"{loc}.character_ids[{j}]",
                ))

        if not sh.prompt:
            report.add(CheckResult(
                CheckSeverity.ERROR, "EMPTY_PROMPT",
                f"shot {sh.shot_id!r} has empty prompt",
                location=f"{loc}.prompt",
                fix_hint="add a 200-400 char English prompt",
            ))
        if not sh.negative_prompt:
            report.add(CheckResult(
                CheckSeverity.WARNING, "EMPTY_NEGATIVE_PROMPT",
                f"shot {sh.shot_id!r} has empty negative_prompt",
                location=f"{loc}.negative_prompt",
            ))

        if sh.duration_sec < 2 or sh.duration_sec > 15:
            report.add(CheckResult(
                CheckSeverity.ERROR, "BAD_DURATION",
                f"shot {sh.shot_id!r} duration_sec={sh.duration_sec} not in [2, 15]",
                location=f"{loc}.duration_sec",
                fix_hint="keep each shot 5-10 seconds for best results",
            ))

        if sh.start_frame_source not in {"manual", "previous_shot"}:
            report.add(CheckResult(
                CheckSeverity.ERROR, "BAD_START_FRAME_SOURCE",
                f"shot {sh.shot_id!r} start_frame_source={sh.start_frame_source!r}",
                location=f"{loc}.start_frame_source",
                fix_hint="must be 'manual' or 'previous_shot'",
            ))

        per_scene_index[sh.scene_id].append(sh.shot_index)

    # Monotonic shot_index within scene, starting at 1
    for scene_id, indices in per_scene_index.items():
        sorted_idx = sorted(indices)
        if sorted_idx and sorted_idx[0] != 1:
            report.add(CheckResult(
                CheckSeverity.ERROR, "OUT_OF_ORDER_INDEX",
                f"scene {scene_id!r} shot_index starts at {sorted_idx[0]}, expected 1",
                location=f"shots[scene={scene_id}]",
            ))
        if sorted_idx != list(range(sorted_idx[0], sorted_idx[0] + len(sorted_idx))):
            report.add(CheckResult(
                CheckSeverity.ERROR, "OUT_OF_ORDER_INDEX",
                f"scene {scene_id!r} shot_index is not contiguous: {sorted_idx}",
                location=f"shots[scene={scene_id}]",
            ))


def _check_dialogues(bundle: Imports, report: CheckReport) -> None:
    if not bundle.dialogues:
        return
    shot_ids = {sh.shot_id for sh in bundle.shots}
    char_ids = {ch.character_id for ch in bundle.characters}
    seen: set[str] = set()
    for i, dl in enumerate(bundle.dialogues):
        loc = f"dialogues[{i}]"
        _check_slug(report, dl.dialogue_id, "dialogue_id", f"{loc}.dialogue_id")
        if dl.dialogue_id in seen:
            report.add(CheckResult(
                CheckSeverity.ERROR, "DUPLICATE_DIALOGUE_ID",
                f"dialogue_id={dl.dialogue_id!r} appears multiple times",
                location=loc,
            ))
        seen.add(dl.dialogue_id)

        if dl.shot_id not in shot_ids:
            report.add(CheckResult(
                CheckSeverity.ERROR, "DIALOGUE_BAD_REFERENCE",
                f"dialogue {dl.dialogue_id!r} references shot {dl.shot_id!r} which does not exist",
                location=f"{loc}.shot_id",
            ))
        if dl.character_id not in char_ids:
            report.add(CheckResult(
                CheckSeverity.ERROR, "DIALOGUE_BAD_REFERENCE",
                f"dialogue {dl.dialogue_id!r} references character {dl.character_id!r} which does not exist",
                location=f"{loc}.character_id",
            ))
        if not dl.line:
            report.add(CheckResult(
                CheckSeverity.WARNING, "EMPTY_LINE",
                f"dialogue {dl.dialogue_id!r} has empty line",
                location=f"{loc}.line",
            ))
        # timing sanity
        # we need to look up shot duration; do a simple membership check
        for sh in bundle.shots:
            if sh.shot_id == dl.shot_id:
                if dl.timing_sec < 0 or dl.timing_sec > sh.duration_sec + 0.5:
                    report.add(CheckResult(
                        CheckSeverity.WARNING, "BAD_TIMING",
                        f"dialogue {dl.dialogue_id!r} timing={dl.timing_sec} outside shot duration {sh.duration_sec}",
                        location=f"{loc}.timing_sec",
                    ))
                break


def _check_chain(bundle: Imports, report: CheckReport) -> None:
    by_id = {sh.shot_id: sh for sh in bundle.shots}
    # previous_shot/next_shot must point to existing shots
    for sh in bundle.shots:
        if sh.previous_shot and sh.previous_shot not in by_id:
            report.add(CheckResult(
                CheckSeverity.ERROR, "MISSING_REFERENCE",
                f"shot {sh.shot_id!r}.previous_shot={sh.previous_shot!r} does not exist",
                location=f"shots[{sh.shot_id}].previous_shot",
            ))
        if sh.next_shot and sh.next_shot not in by_id:
            report.add(CheckResult(
                CheckSeverity.ERROR, "MISSING_REFERENCE",
                f"shot {sh.shot_id!r}.next_shot={sh.next_shot!r} does not exist",
                location=f"shots[{sh.shot_id}].next_shot",
            ))
    # Bidirectional chain: if A.next_shot == B, then B.previous_shot == A
    for sh in bundle.shots:
        if sh.next_shot:
            other = by_id.get(sh.next_shot)
            if other and other.previous_shot != sh.shot_id:
                report.add(CheckResult(
                    CheckSeverity.ERROR, "BROKEN_CHAIN",
                    f"shot {sh.shot_id!r}.next_shot={sh.next_shot!r} but {sh.next_shot!r}.previous_shot={other.previous_shot!r} (expected {sh.shot_id!r})",
                    location=f"shots[{sh.shot_id}].next_shot",
                    fix_hint="set both sides to each other",
                ))
    # Exactly one shot per chain must have empty previous_shot, and one with empty next_shot
    starts = [sh.shot_id for sh in bundle.shots if not sh.previous_shot]
    ends = [sh.shot_id for sh in bundle.shots if not sh.next_shot]
    if len(starts) > 1:
        report.add(CheckResult(
            CheckSeverity.WARNING, "MULTIPLE_CHAIN_STARTS",
            f"{len(starts)} shots have empty previous_shot: {starts[:5]}{'...' if len(starts) > 5 else ''}",
            fix_hint="set previous_shot on all but the first shot of each chain",
        ))
    if len(ends) > 1:
        report.add(CheckResult(
            CheckSeverity.WARNING, "MULTIPLE_CHAIN_ENDS",
            f"{len(ends)} shots have empty next_shot: {ends[:5]}{'...' if len(ends) > 5 else ''}",
            fix_hint="set next_shot on all but the last shot of each chain",
        ))
