"""``storyboard`` command: build scenes + shots from a story."""

from __future__ import annotations

from ..core.errors import ValidationError
from ..core.project_manager import ProjectManager
from ..story import ScenePlanner, ShotPlanner
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
        story = pm.load_story(paths)
        if story is None:
            raise ValidationError(f"story.yaml not found at {paths.story_file}")
        from ..story import StoryAnalyzer
        bible = StoryAnalyzer().analyze(story)
        scenes = ScenePlanner().plan(story, bible)
        if not scenes:
            raise ValidationError("planner produced no scenes (empty script?)")
        shot_plans = ShotPlanner().plan_story(scenes)
        for sc in scenes:
            pm.save_scene(paths, sc)
        n_shots = 0
        for plan in shot_plans:
            shot = plan.to_shot()
            pm.save_shot(paths, shot)
            n_shots += 1
    except Exception as e:
        return print_error(e)
    print(f"[ok] wrote {len(scenes)} scenes and {n_shots} shots under {paths.root}")
    return 0