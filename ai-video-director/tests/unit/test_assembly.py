"""Tests for FFmpegBuilder."""

from __future__ import annotations

from pathlib import Path

from video_director.assembly import (
    AssemblyConfig,
    FFmpegBuilder,
    build_assembly_manifest,
    write_assembly_manifest,
)
from video_director.core.errors import AssemblyError
from video_director.generators import MockVideoGenerator
from video_director.models import Audio, Shot, VideoClip


def _make_three_clips(tmp_path: Path) -> list[VideoClip]:
    g = MockVideoGenerator()
    clips = []
    for i in range(3):
        shot = Shot(shot_id=f"s{i}", scene_id="sc1", duration_sec=0.5, prompt=str(i), action="x")
        out = g.generate(shot, output_dir=tmp_path / "clips")
        clips.append(VideoClip(
            shot_id=shot.shot_id, path=str(out.output_path),
            duration_sec=out.duration_sec,
            width=out.width, height=out.height, fps=out.fps,
            file_size_bytes=out.file_size_bytes,
        ))
    return clips


def test_build_assembly_manifest_roundtrip(tmp_path):
    clips = _make_three_clips(tmp_path)
    manifest = build_assembly_manifest(
        clips, project_id="p",
        output_path=str(tmp_path / "final.mp4"),
    )
    path = tmp_path / "manifest.json"
    write_assembly_manifest(manifest, path)
    assert path.exists()
    assert manifest.clips == clips


def test_assemble_produces_final_video(tmp_path):
    clips = _make_three_clips(tmp_path)
    manifest = build_assembly_manifest(
        clips, project_id="p", output_path=str(tmp_path / "final.mp4"),
    )
    final = FFmpegBuilder(AssemblyConfig()).run(manifest)
    assert Path(final.path).exists()
    assert final.file_size_bytes > 0
    # 3 × 0.5s = ~1.5s
    assert final.duration_sec >= 1.0


def test_assemble_without_clips_raises(tmp_path):
    manifest = build_assembly_manifest(
        [], project_id="p", output_path=str(tmp_path / "final.mp4"),
    )
    with __import__("pytest").raises(AssemblyError):
        FFmpegBuilder(AssemblyConfig()).run(manifest)


def test_assemble_handles_target_dimensions(tmp_path):
    clips = _make_three_clips(tmp_path)
    manifest = build_assembly_manifest(
        clips, project_id="p", output_path=str(tmp_path / "final.mp4"),
    )
    final = FFmpegBuilder(AssemblyConfig(target_width=160, target_height=90)).run(manifest)
    assert Path(final.path).exists()


def test_assemble_with_audio_track(tmp_path):
    clips = _make_three_clips(tmp_path)
    # Generate a tiny silent audio track for the assembler to mix
    import subprocess
    audio_path = tmp_path / "tone.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
        str(audio_path),
    ], check=True, capture_output=True)
    audio = Audio(track_id="a1", kind="bgm", path=str(audio_path))
    manifest = build_assembly_manifest(
        clips, project_id="p", output_path=str(tmp_path / "final.mp4"),
        audios=[audio],
    )
    final = FFmpegBuilder(AssemblyConfig()).run(manifest)
    assert Path(final.path).exists()