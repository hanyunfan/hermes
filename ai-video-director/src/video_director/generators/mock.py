"""Mock video generator.

Creates a real video file with FFmpeg so the entire pipeline can be exercised
in CI without a GPU or ComfyUI server. The clip is a coloured gradient with
text overlay showing the shot id and prompt — visually meaningless but real.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import GenerationError
from ..models import Shot
from ..utils.logging import get_logger
from .base import GenerationOutcome, GeneratorCapabilities, VideoGenerator


_LOG = get_logger("video_director.generators.mock")


class MockVideoGenerator(VideoGenerator):
    """Deterministic, offline generator backed by FFmpeg."""

    capabilities = GeneratorCapabilities(
        name="mock",
        supports_seed=True,
        supports_image_input=False,
        supports_negative_prompt=False,
        is_offline=True,
    )

    def __init__(self, ffmpeg_binary: str = "ffmpeg", width: int = 320, height: int = 180):
        self.ffmpeg = ffmpeg_binary
        self.width = width
        self.height = height
        if not shutil.which(ffmpeg_binary):
            raise GenerationError(
                f"ffmpeg binary not found: {ffmpeg_binary!r}; "
                f"install ffmpeg or pass an explicit path"
            )

    def generate(
        self,
        shot: Shot,
        *,
        output_dir: Path,
        references: Mapping[str, str] | None = None,
        seed_override: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> GenerationOutcome:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{shot.shot_id}.mp4"
        duration = max(0.5, float(shot.duration_sec))
        # Deterministic colour from shot id so shots differ.
        seed_src = (seed_override if seed_override is not None else (shot.seed or hash(shot.shot_id)))
        colour_seed = abs(int(seed_src)) % 0xFFFFFF
        hue = (colour_seed >> 16) & 0xFF
        sat = (colour_seed >> 8) & 0xFF
        val = colour_seed & 0xFF
        text = f"{shot.shot_id} | {shot.prompt[:40]}".replace("'", "\\'").replace(":", "\\:")
        vf = (
            f"drawtext=text='{text}':fontcolor=white:fontsize=14:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.4"
        )
        cmd = [
            self.ffmpeg,
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x{hue:02x}{sat:02x}{val:02x}:s={self.width}x{self.height}:r=12:d={duration}",
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            "-movflags", "+faststart",
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except subprocess.CalledProcessError as e:
            raise GenerationError(
                f"mock ffmpeg failed: {e.stderr.decode(errors='ignore')[:400]}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise GenerationError("mock ffmpeg timed out") from e
        size = out_path.stat().st_size
        return GenerationOutcome(
            output_path=out_path,
            seed_used=int(seed_src) if seed_src is not None else 0,
            prompt_used=shot.prompt,
            duration_sec=duration,
            width=self.width,
            height=self.height,
            fps=12.0,
            file_size_bytes=size,
            metadata={"backend": "mock", "shot_id": shot.shot_id},
        )

    def cancel(self, shot_id: str) -> bool:
        # Mock generator is synchronous and runs to completion in <1s.
        return False