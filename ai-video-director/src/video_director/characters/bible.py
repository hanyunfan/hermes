"""Character bible loader + helpers."""

from __future__ import annotations

from pathlib import Path

from ..core.errors import ValidationError
from ..core.paths import ProjectPaths
from ..core.project_manager import ProjectManager
from ..models import Character, CharacterBible
from ..utils.logging import get_logger


_LOG = get_logger("video_director.characters.bible")


class CharacterBibleService:
    """High-level read/write of the project's character bible."""

    def __init__(self, project_manager: ProjectManager):
        self.pm = project_manager

    def load(self, paths: ProjectPaths) -> CharacterBible:
        chars = list(self.pm.iter_characters(paths))
        if not chars:
            _LOG.info("no character files found under %s", paths.characters_dir)
        return CharacterBible(characters=chars)

    def get(self, paths: ProjectPaths, character_id: str) -> Character | None:
        for c in self.pm.iter_characters(paths):
            if c.character_id == character_id:
                return c
        return None

    def save(self, paths: ProjectPaths, character: Character) -> None:
        self.pm.save_character(paths, character)

    def validate(self, bible: CharacterBible, paths: ProjectPaths | None = None) -> list[str]:
        """Return a list of warnings about the bible (empty list = all good).

        ``paths`` is optional. When provided, missing reference image files
        are reported; otherwise the check is skipped so a character-only
        caller doesn't crash.
        """
        warnings: list[str] = []
        ids = {c.character_id for c in bible.characters}
        if len(ids) != len(bible.characters):
            warnings.append("duplicate character_id detected")
        for c in bible.characters:
            if not c.reference_images:
                warnings.append(
                    f"character {c.character_id!r} has no reference_images "
                    f"(continuity will be weaker)"
                )
            if paths is None:
                continue
            for ref in c.reference_images:
                p = Path(paths.references_dir) / ref.path
                if not p.exists():
                    warnings.append(
                        f"reference file missing: {p} (referenced by {c.character_id})"
                    )
        return warnings