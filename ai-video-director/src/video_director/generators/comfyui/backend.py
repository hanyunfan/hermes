"""ComfyUI backend implementing :class:`VideoGenerator`.

Bridges the :class:`VideoGenerator` interface and :class:`ComfyUIWorkflowAdapter`.
Registered as ``"comfyui"`` in the registry on import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ...core.errors import GenerationError
from ...models import Shot
from ...workflow.adapter import ComfyUIConfig, ComfyUIWorkflowAdapter
from ..base import GenerationOutcome, GeneratorCapabilities, VideoGenerator
from ..registry import register_generator


class ComfyUIGenerator(VideoGenerator):
    capabilities = GeneratorCapabilities(
        name="comfyui",
        supports_seed=True,
        supports_image_input=True,
        supports_negative_prompt=True,
        is_offline=False,
    )

    def __init__(self, config: ComfyUIConfig | None = None):
        self.config = config or ComfyUIConfig()
        self.adapter = ComfyUIWorkflowAdapter(self.config)

    def generate(
        self,
        shot: Shot,
        *,
        output_dir: Path,
        references: Mapping[str, str] | None = None,
        seed_override: int | None = None,
        context: Mapping[str, Any] | None = None,
        reference_images_ordered: list[dict[str, Any]] | None = None,
        reference_videos_ordered: list[dict[str, Any]] | None = None,
    ) -> GenerationOutcome:
        context = context or {}
        paths = context.get("paths")
        mapping = context.get("workflow_mapping")
        if paths is None or mapping is None:
            raise GenerationError(
                "ComfyUIGenerator requires context['paths'] and context['workflow_mapping']"
            )
        result = self.adapter.generate_clip(
            shot=shot,
            paths=paths,
            mapping=mapping,
            output_dir=output_dir,
            references=references,
            seed_override=seed_override,
            reference_images_ordered=reference_images_ordered,
            reference_videos_ordered=reference_videos_ordered,
        )
        return GenerationOutcome(
            output_path=result.output_path,
            seed_used=result.seed_used,
            prompt_used=result.prompt_used,
            duration_sec=shot.duration_sec,
            file_size_bytes=result.output_path.stat().st_size if result.output_path.exists() else 0,
            metadata=result.metadata,
        )

    def cancel(self, shot_id: str) -> bool:
        # ComfyUI HTTP /queue endpoint supports delete; left as TODO so we
        # don't half-implement and silently fail. Returning False signals
        # "not supported yet" rather than a fake success.
        return False


register_generator("comfyui", ComfyUIGenerator)