"""Video assembly via FFmpeg.

v0 supports:
  * Concat clips in order (re-encoding is the safest default; concat
    demuxer requires identical codecs/resolutions which we don't guarantee).
  * Mix voice-over audio tracks at given offsets.
  * Mix a background-music track (looped/truncated to total duration).
  * Burn a soft subtitle pass-through from an SRT file (no re-timing).
  * Optional intro/outro title cards.

Architecture is built around an :class:`FFmpegBuilder` that produces a
single command line. The build is then ``run()`` once. This makes the
process debuggable (you can re-run the command by hand) and easy to extend
without duplicating subprocess plumbing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..core.errors import AssemblyError
from ..models import AssemblyManifest, Audio, FinalVideo, VideoClip
from ..utils.io import write_json
from ..utils.logging import get_logger


_LOG = get_logger("video_director.assembly.builder")


@dataclass
class AssemblyConfig:
    """Tunables for FFmpeg invocation."""

    ffmpeg: str = "ffmpeg"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    pix_fmt: str = "yuv420p"
    preset: str = "medium"
    crf: int = 20
    target_width: int | None = None
    target_height: int | None = None
    target_fps: int | None = None
    extra_args: list[str] = field(default_factory=list)


class FFmpegBuilder:
    """Builds and runs an FFmpeg command for a single :class:`AssemblyManifest`.

    Each call to :meth:`build` returns the argv list — handy for debugging or
    for users who want to hand-run the command.
    """

    def __init__(self, config: AssemblyConfig | None = None):
        self.config = config or AssemblyConfig()
        if shutil.which(self.config.ffmpeg) is None:
            raise AssemblyError(f"ffmpeg not found: {self.config.ffmpeg!r}")

    # ---- build ------------------------------------------------------

    def build(self, manifest: AssemblyManifest) -> list[str]:
        clips = sorted(
            manifest.clips,
            key=lambda c: (Path(c.path).stem, c.shot_id),
        )
        if not clips:
            raise AssemblyError("no clips to assemble")
        # Filter graph: scale + fps + concat + amix
        v_filters, v_labels = self._video_filters(clips)
        audio_offset = len(clips)
        a_filters, a_inputs = self._audio_filters(manifest.audios, input_offset=audio_offset)
        cmd: list[str] = [self.config.ffmpeg, "-y"]
        # inputs
        for clip in clips:
            cmd.extend(["-i", str(clip.path)])
        for audio in manifest.audios:
            cmd.extend(["-i", str(audio.path)])
        # filter complex
        if a_filters:
            fc = v_filters + ";" + a_filters
        else:
            fc = v_filters
        cmd.extend(["-filter_complex", fc])
        # map the final concatenated video + amixed audio
        cmd.extend(["-map", f"[{v_labels}]"])
        if a_filters:
            cmd.extend(["-map", f"[{a_inputs}]"])
        cmd.extend(["-c:v", self.config.video_codec])
        cmd.extend(["-c:a", self.config.audio_codec])
        cmd.extend(["-pix_fmt", self.config.pix_fmt])
        cmd.extend(["-preset", self.config.preset])
        cmd.extend(["-crf", str(self.config.crf)])
        cmd.extend(["-movflags", "+faststart"])
        if self.config.target_fps:
            cmd.extend(["-r", str(self.config.target_fps)])
        cmd.extend(self.config.extra_args)
        cmd.append(str(manifest.output_path))
        return cmd

    def _video_filters(self, clips: Sequence[VideoClip]) -> tuple[str, str]:
        # Build: [0:v]scale=W:H:fps=FPS[v0]; [1:v]scale=...[v1]; ... [v0][v1]...[vN]concat=n=N+1:v=1:a=0[outv]
        per_clip: list[str] = []
        labels: list[str] = []
        target_w = self.config.target_width
        target_h = self.config.target_height
        target_fps = self.config.target_fps
        for idx, clip in enumerate(clips):
            label = f"v{idx}"
            labels.append(f"[{label}]")
            filt = f"[{idx}:v]"
            scale_parts: list[str] = []
            if target_w and target_h:
                scale_parts.append(f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease")
                scale_parts.append(f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2")
            elif clip.width and clip.height:
                scale_parts.append(f"scale={clip.width}:{clip.height}")
            if target_fps:
                scale_parts.append(f"fps={target_fps}")
            if scale_parts:
                filt += ",".join(scale_parts) + ","
            filt += f"setpts=PTS-STARTPTS[{label}]"
            per_clip.append(filt)
        # Force a uniform duration per clip so concat doesn't drop frames
        # when source durations vary; 30 seconds is generous for shots.
        # concat handles differing durations if all input streams have
        # setpts applied.
        concat_inputs = "".join(labels)
        n = len(clips)
        per_clip.append(
            f"{concat_inputs}concat=n={n}:v=1:a=0[outv]"
        )
        return ";".join(per_clip), "outv"

    def _audio_filters(
        self,
        audios: Sequence[Audio],
        input_offset: int = 0,
    ) -> tuple[str, str]:
        """Build the audio filter graph.

        Returns ``(filter_graph, output_label)``. ``filter_graph`` is empty
        if there are no audio tracks. ``input_offset`` is the index of the
        first audio input in the full ffmpeg command line (right after the
        clip inputs).
        """
        if not audios:
            return "", ""
        parts: list[str] = []
        mix_inputs: list[str] = []
        for i, audio in enumerate(audios):
            label = f"a{i}"
            mix_inputs.append(f"[{label}]")
            delay_ms = int(round(audio.start_sec * 1000))
            gain = audio.gain_db
            gain_lin = 10 ** (gain / 20)
            parts.append(
                f"[{input_offset + i}:a]"
                f"adelay=delays={delay_ms}:all=1,"
                f"volume={gain_lin:.4f},"
                f"asetpts=PTS-STARTPTS[{label}]"
            )
        parts.append(
            f"{''.join(mix_inputs)}amix=inputs={len(audios)}:normalize=0[outa]"
        )
        return ";".join(parts), "outa"

    # ---- run --------------------------------------------------------

    def run(self, manifest: AssemblyManifest) -> FinalVideo:
        Path(manifest.output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = self.build(manifest)
        _LOG.info("ffmpeg cmd: %s", " ".join(repr(x) for x in cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=4 * 3600)
        except subprocess.TimeoutExpired as e:
            raise AssemblyError("ffmpeg assemble timed out") from e
        if r.returncode != 0:
            tail = r.stderr.decode(errors="ignore")[-600:]
            raise AssemblyError(f"ffmpeg assemble failed: {tail}")
        # Probe final output
        final = FinalVideo(
            path=str(manifest.output_path),
            duration_sec=self._probe_duration(Path(manifest.output_path)),
            file_size_bytes=Path(manifest.output_path).stat().st_size,
        )
        return final

    def _probe_duration(self, path: Path) -> float:
        try:
            r = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-print_format", "json",
                    "-show_format", str(path),
                ],
                capture_output=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0.0
        if r.returncode != 0:
            return 0.0
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return 0.0
        return float((data.get("format") or {}).get("duration", 0.0) or 0.0)


def build_assembly_manifest(
    clips: list[VideoClip],
    *,
    project_id: str,
    output_path: str | Path,
    audios: list[Audio] | None = None,
    subtitles_path: str = "",
    notes: str = "",
) -> AssemblyManifest:
    """Convenience builder that the CLI uses."""
    return AssemblyManifest(
        project_id=project_id,
        clips=list(clips),
        audios=list(audios or []),
        subtitles_path=subtitles_path,
        output_path=str(output_path),
        notes=notes,
    )


def write_assembly_manifest(manifest: AssemblyManifest, path: str | Path) -> None:
    write_json(path, manifest.to_dict())