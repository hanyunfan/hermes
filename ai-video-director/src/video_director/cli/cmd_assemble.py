"""``assemble`` command: QA all clips then concat to final.mp4.

Audio handling:
  * Each clip from the runner already carries its own aac audio track
    (ComfyUI's MiniMaxH3 I2V output produces a quiet ambient aac for
    every clip). We pass those audio streams through the concat filter
    so the final video has the natural ambient sound.
  * We do NOT synthesise voice from a dialogues field. We do NOT
    auto-add background music. The user can opt-in to music by passing
    ``--audio <wav>`` explicitly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..assembly import FFmpegBuilder, AssemblyConfig, build_assembly_manifest, write_assembly_manifest
from ..core.project_manager import ProjectManager
from ..jobs import StateManager
from ..models import Audio, VideoClip
from ..quality import QAChecker
from ..utils.io import read_yaml, write_json
from .common import print_error

_LOG = logging.getLogger(__name__)


def _stamp_final_filename(paths, now: datetime | None = None) -> Path:
    """Rewrite ``paths.final_video_file`` to ``final_<YYYYMMDDHHMMSS>.mp4``.

    Each assemble run produces its own timestamped file so multiple runs of
    the same project never silently overwrite each other's output. The
    filename is decided once at assemble entry and stays stable for the
    rest of the run (manifest writer, FFmpegBuilder, end-of-run report).

    Returns the new final_video_file Path (already mutated on ``paths``).
    """
    ts = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
    new_path = paths.output_final_dir / f"final_{ts}.mp4"
    paths.final_video_file = new_path
    return new_path


def _collect_clips(paths, sm: StateManager, expected_order: list[str] | None = None) -> list[VideoClip]:
    """Build VideoClip records in deterministic order.

    If ``expected_order`` is given (the shot ids from yaml, in order), use it;
    otherwise fall back to alphabetical glob order. The caller should always
    pass the yaml order so that assembling never rearranges clips based on
    filesystem ordering, which is fragile.
    """
    # Index clips by shot_id for O(1) lookup.
    by_id: dict[str, VideoClip] = {}
    for c in sm.iter_clips():
        if c.path and Path_present(c.path):
            by_id[c.shot_id] = c
    # Fallback: scan output/clips/*.mp4 if state has nothing.
    if not by_id:
        for f in sorted(paths.output_clips_dir.glob("*.mp4")):
            cid = VideoClip(
                shot_id=f.stem,
                path=str(f),
                duration_sec=0.0,
            )
            by_id[cid.shot_id] = cid
    # Emit in expected_order, skipping any clip not present.
    if expected_order is not None:
        ordered = [by_id[sid] for sid in expected_order if sid in by_id]
    else:
        ordered = sorted(by_id.values(), key=lambda c: c.shot_id)
    return ordered


def Path_present(p: str) -> bool:
    from pathlib import Path
    return Path(p).exists()


def _check_orphan_clips(paths, expected_shot_ids: set[str]) -> tuple[list[str], list[str]]:
    """Compare ``output/clips/`` against the shot yaml set.

    Returns ``(missing, orphans)`` — shots that have a yaml but no mp4, and
    mp4 files that exist but have no corresponding yaml.

    Orphan mp4s in particular are dangerous: if the runner accidentally
    produced a clip for a shot that has since been deleted from shots/, the
    assemble step would silently include it unless we filter here.
    """
    on_disk = {p.stem for p in paths.output_clips_dir.glob("*.mp4")}
    missing = sorted(expected_shot_ids - on_disk)
    orphans = sorted(on_disk - expected_shot_ids)
    return missing, orphans


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
        pm.load_project(paths.root)
        sm = StateManager(paths)
        # Stamp the final filename once at entry so the manifest writer,
        # FFmpegBuilder and end-of-run report all agree on the same path.
        final_path = _stamp_final_filename(paths)
        # Build the canonical shot order from yaml BEFORE collecting clips,
        # so the assembled final.mp4 follows the story order, not the
        # filesystem glob order.
        expected_shot_ids = [s.shot_id for s in pm.iter_shots(paths)]

        # Default behaviour: hard-filter shots whose id starts with
        # ``example_`` (template scaffolding, quick-checks). Use
        # ``--exclude-ids`` for ad-hoc exclusions; there is no flag to
        # re-include example_ shots.
        explicit_excludes = set()
        if getattr(args, "exclude_ids", None):
            explicit_excludes = {s.strip() for s in args.exclude_ids.split(",") if s.strip()}
        explicit_excludes.update(s for s in expected_shot_ids if s.startswith("example_"))

        if explicit_excludes:
            print(
                f"[info] filtering {len(explicit_excludes)} shot(s) from final video: "
                f"{sorted(explicit_excludes)[:5]}{'...' if len(explicit_excludes) > 5 else ''}"
            )
            expected_shot_ids = [s for s in expected_shot_ids if s not in explicit_excludes]

        clips = _collect_clips(paths, sm, expected_order=expected_shot_ids)

        # Orphan check: ensure output/clips/ matches the project's declared
        # shots. This is the wall against "runner produced extra clips that
        # silently accumulated in output/clips/".
        missing, orphans = _check_orphan_clips(paths, set(expected_shot_ids))
        if orphans:
            print(
                f"[warning] {len(orphans)} orphan mp4 in output/clips/ with no matching "
                f"shot yaml (refusing to include in final): {orphans[:5]}"
                f"{'...' if len(orphans) > 5 else ''}"
            )
        if missing:
            print(
                f"[warning] {len(missing)} shot yaml(s) have no mp4 in output/clips/: "
                f"{missing[:5]}{'...' if len(missing) > 5 else ''}"
            )

        if not clips:
            from ..core.errors import ValidationError
            raise ValidationError("no clips to assemble (run `video-director generate` first)")
        # Optional QA gate
        qa = QAChecker()
        if not args.skip_qa:
            results = qa.check_clips(clips)
            failed = [r for r in results if not r.passed]
            qa_summary_path = paths.state_dir / "qa" / "last_assembly_qa.json"
            qa_summary_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(qa_summary_path, {"results": [r.to_dict() for r in results]})
            print(
                f"[qa] {len(results)} clip(s) checked, {len(failed)} failed; "
                f"summary: {qa_summary_path}"
            )
            for r in failed:
                print(f"     FAIL {r.shot_id}: {r.notes}")
            if failed and not args.allow_qa_fail:
                from ..core.errors import AssemblyError
                raise AssemblyError(
                    f"QA failed for {len(failed)} clip(s); use --allow-qa-fail to ignore"
                )
        # Optional user-supplied audio tracks (bgm / extra voice). NOT
        # auto-added — user must explicitly pass --audio for any music.
        audios: list[Audio] = []
        if args.audio:
            for i, p in enumerate(args.audio):
                audios.append(
                    Audio(
                        track_id=f"audio_{i:03d}",
                        kind=args.audio_kind[i] if args.audio_kind and i < len(args.audio_kind) else "voice",
                        path=str(p),
                    )
                )
        manifest = build_assembly_manifest(
            clips,
            project_id=args.project,
            output_path=str(paths.final_video_file),
            audios=audios,
        )
        write_assembly_manifest(manifest, paths.assembly_manifest_file)
        builder = FFmpegBuilder(AssemblyConfig(target_width=args.width, target_height=args.height))
        final = builder.run(manifest)
    except Exception as e:
        return print_error(e)
    print(f"[ok] assembled {final.path} size={final.file_size_bytes} duration={final.duration_sec:.2f}s")
    return 0