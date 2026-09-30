"""``run`` command: end-to-end pipeline (analyze → storyboard → generate → assemble)."""

from __future__ import annotations

from ..core.errors import ValidationError
from ..core.project_manager import ProjectManager
from ..jobs import GenerationRunner, RunnerConfig
from ..quality import QAChecker
from ..story import ScenePlanner, ShotPlanner, StoryAnalyzer
from .cmd_generate import _build_runner_config
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    config = _build_runner_config(args)
    try:
        paths = pm.paths_for_id(args.project)
        pm.load_project(paths.root)
        story = pm.load_story(paths)
        if story is None:
            raise ValidationError(f"story.yaml not found at {paths.story_file}")
        bible = StoryAnalyzer().analyze(story)
        scenes = ScenePlanner().plan(story, bible)
        for sc in scenes:
            pm.save_scene(paths, sc)
        shot_plans = ShotPlanner().plan_story(scenes)
        for plan in shot_plans:
            pm.save_shot(paths, plan.to_shot())
        runner = GenerationRunner(paths, project_manager=pm, config=config)
        summary = runner.run()
        # Assemble
        from ..assembly import AssemblyConfig, FFmpegBuilder, build_assembly_manifest, write_assembly_manifest
        from ..jobs import StateManager
        sm = StateManager(paths)
        clips = []
        for c in sm.iter_clips():
            from pathlib import Path
            if c.path and Path(c.path).exists():
                clips.append(c)
        manifest = build_assembly_manifest(
            clips, project_id=args.project,
            output_path=str(paths.final_video_file),
        )
        write_assembly_manifest(manifest, paths.assembly_manifest_file)
        FFmpegBuilder(AssemblyConfig()).run(manifest)
    except Exception as e:
        return print_error(e)
    print(f"[ok] full pipeline done for {args.project}; final={paths.final_video_file}")
    return 0