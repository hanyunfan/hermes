"""Import subsystem — load and validate JSON files that an external LLM
(Grok, ChatGPT, Claude, ...) produced from prompts/grok_storyboard.md.

Layout under ``projects/<project_id>/imports/``::

    story.json
    characters.json
    scenes.json
    shots.json
    dialogues.json   (optional)
    references/<character_id>/hero.png  (optional)

Each JSON file maps 1:1 to a model in the existing schema:

  story.json      → Story
  characters.json → list[Character]
  scenes.json     → list[Scene]
  shots.json      → list[Shot]
  dialogues.json  → list[Dialogue]   (new — not yet a yaml-backed model)

The loader is permissive: it accepts the raw LLM output (which may have
extra fields, missing optional fields, etc.) and produces dataclasses
that can be fed straight into :func:`build_yaml_from_imports`.

The checker (:mod:`video_director.imports.checker`) is strict: it raises
:class:`ImportError` with a single actionable message per problem.
"""

from __future__ import annotations

from .loader import (
    Imports,
    load_imports,
    ImportError,
)
from .checker import (
    check_imports,
    CheckReport,
    CheckResult,
    CheckSeverity,
)
from .builder import build_yaml_from_imports

__all__ = [
    "Imports",
    "load_imports",
    "ImportError",
    "check_imports",
    "CheckReport",
    "CheckResult",
    "CheckSeverity",
    "build_yaml_from_imports",
]
