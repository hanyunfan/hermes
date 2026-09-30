"""``assemble`` command: QA all clips then concat to final.mp4."""

from __future__ import annotations

from ..assembly import FFmpegBuilder, AssemblyConfig, build_assembly_manifest, write_assembly_manifest
from ..core.project_manager import ProjectManager
from ..jobs import StateManager
from ..models import Audio, VideoClip
from ..quality import QAChecker
from ..utils.io import read_yaml, write_json
from .common import print_error


def _collect_clips(paths, sm: StateManager) -> list[VideoClip]:
    by_id: dict[str, VideoClip] = {}
    for c in sm.iter_clips():
        if c.path and Path_present(c.path):
            by_id[c.shot_id] = c
    # Fallback: scan output/clips/*.mp4
    if not by_id:
        for f in sorted(paths.output_clips_dir.glob("*.mp4")):
            cid = VideoClip(
                shot_id=f.stem,
                path=str(f),
                duration_sec=0.0,
            )
            by_id[cid.shot_id] = cid
    return list(by_id.values())


def Path_present(p: str) -> bool:
    from pathlib import Path
    return Path(p).exists()


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
        pm.load_project(paths.root)
        sm = StateManager(paths)
        clips = _collect_clips(paths, sm)
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