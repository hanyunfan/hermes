"""VideoGenerator interface.

Every backend — ComfyUI, cloud API, mock — implements this. The runner
talks to backends via this interface so swapping is free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..models import Shot


@dataclass
class GeneratorCapabilities:
    """What a backend can do."""

    name: str = ""
    supports_seed: bool = False
    supports_image_input: bool = False
    supports_negative_prompt: bool = False
    is_offline: bool = False  # True if no GPU/network required


class VideoGenerator(ABC):
    """Backend-agnostic video generator interface."""

    capabilities: GeneratorCapabilities = GeneratorCapabilities()

    @abstractmethod
    def generate(
        self,
        shot: Shot,
        *,
        output_dir: Path,
        references: Mapping[str, str] | None = None,
        seed_override: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> "GenerationOutcome":
        """Produce one video clip and return where it landed."""

    @abstractmethod
    def cancel(self, shot_id: str) -> bool:
        """Cancel an in-flight job. Returns True if cancellation was accepted."""


@dataclass
class GenerationOutcome:
    """Result of a single backend call."""

    output_path: Path
    seed_used: int = 0
    prompt_used: str = ""
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    file_size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)