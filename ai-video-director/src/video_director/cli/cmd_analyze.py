"""``analyze`` command: produce a StoryBible from story.yaml."""

from __future__ import annotations

from ..core.project_manager import ProjectManager
from ..story import StoryAnalyzer
from ..utils.io import write_yaml
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
        project = pm.load_project(paths.root)
        story = pm.load_story(paths)
        if story is None:
            from ..core.errors import ValidationError
            raise ValidationError(f"story.yaml not found at {paths.story_file}")
        bible = StoryAnalyzer().analyze(story)
    except Exception as e:
        return print_error(e)
    bible_path = paths.state_dir / "story_bible.json"
    write_yaml(bible_path, bible.to_dict())
    print(f"[ok] story bible written to {bible_path}")
    print(f"     logline: {bible.logline[:120]}")
    print(f"     characters: {bible.characters}")
    print(f"     locations: {bible.locations}")
    print(f"     acts: {len(bible.acts)}; beats: {len(bible.beats)}")
    return 0