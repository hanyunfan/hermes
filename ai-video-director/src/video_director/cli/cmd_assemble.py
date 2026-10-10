"""``assemble`` command: QA all clips then concat to final.mp4."""

from __future__ import annotations

from ..assembly import FFmpegBuilder, AssemblyConfig, build_assembly_manifest, write_assembly_manifest
from ..core.project_manager import ProjectManager
from ..jobs import StateManager
from ..models import Audio, VideoClip
from ..quality import QAChecker
from ..utils.io import read_yaml, write_json
from .common import print_error


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
        # Build the canonical shot order from yaml BEFORE collecting clips,
        # so the assembled final.mp4 follows the story order, not the
        # filesystem glob order.
        expected_shot_ids = [s.shot_id for s in pm.iter_shots(paths)]
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
        # Optional audio
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