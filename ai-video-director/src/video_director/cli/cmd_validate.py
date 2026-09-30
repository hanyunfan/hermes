"""``validate`` command: check that a project is internally consistent."""

from __future__ import annotations

from ..characters import CharacterBibleService
from ..core.project_manager import ProjectManager
from ..utils.io import read_yaml
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
        project = pm.load_project(paths.root)
        bible_service = CharacterBibleService(pm)
        bible = bible_service.load(paths)
        scenes = list(pm.iter_scenes(paths))
        shots = list(pm.iter_shots(paths))
        story = pm.load_story(paths)
        mapping = pm.load_workflow_mapping(paths)
        warnings: list[str] = []
        if not story:
            warnings.append("story.yaml missing or empty")
        if not bible.characters:
            warnings.append("no character files found")
        if not scenes:
            warnings.append("no scene files found (run `video-director storyboard`)")
        if not shots:
            warnings.append("no shot files found (run `video-director storyboard`)")
        if mapping and not mapping.workflow_path:
            warnings.append(
                "workflow.yaml exists but workflow_path is empty; "
                "drop the user's ComfyUI JSON into private/ and update workflow_path"
            )
        char_warnings = bible_service.validate(bible, paths)
        warnings.extend(char_warnings)
        # Continuity scan
        from ..continuity import ContinuityManager
        issues = ContinuityManager().check_story(bible, shots, scenes)
        high = [i for i in issues if i.severity == "high"]
        if high:
            warnings.append(
                f"{len(high)} high-severity continuity issues; first: {high[0].to_dict()}"
            )
        elif issues:
            warnings.append(f"{len(issues)} low/medium continuity issues (informational)")
    except Exception as e:
        return print_error(e)
    print(f"[ok] project {args.project}: {len(warnings)} warning(s)")
    for w in warnings:
        print(f"     - {w}")
    return 0