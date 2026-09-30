"""Path resolution for a project.

Every project is rooted at ``projects/<project_id>/`` with these sub-paths
(overridable via ``project.yaml``):

  project.yaml
  story.yaml
  workflow.yaml             (the per-project workflow mapping; user-supplied)
  characters/<id>.yaml
  scenes/<id>.yaml
  shots/<id>.yaml
  references/<character_id>/<image>.png     (private, gitignored)
  private/                                  (private, gitignored)
  output/clips/   output/final/   output/logs/   output/intermediate/
  state/generation_state.json
  state/jobs/<job_id>.json
  state/clips/<shot_id>.json
  state/qa/<shot_id>.json
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..models.project import Project


@dataclass
class ProjectPaths:
    """Resolved filesystem paths for a project."""

    root: Path
    project_file: Path
    story_file: Path
    workflow_mapping_file: Path
    characters_dir: Path
    scenes_dir: Path
    shots_dir: Path
    references_dir: Path
    private_dir: Path
    output_dir: Path
    output_clips_dir: Path
    output_final_dir: Path
    output_logs_dir: Path
    output_intermediate_dir: Path
    state_dir: Path
    state_jobs_dir: Path
    state_clips_dir: Path
    state_qa_dir: Path
    assembly_manifest_file: Path
    final_video_file: Path

    @classmethod
    def from_project(cls, project_root: Path, project: Project) -> "ProjectPaths":
        """Resolve paths from a parsed :class:`Project`."""
        root = Path(project_root).resolve()
        return cls(
            root=root,
            project_file=root / "project.yaml",
            story_file=root / project.story_path,
            workflow_mapping_file=root / project.workflow_config,
            characters_dir=root / project.characters_dir,
            scenes_dir=root / project.scenes_dir,
            shots_dir=root / project.shots_dir,
            references_dir=root / project.references_dir,
            private_dir=root / "private",
            output_dir=root / project.output_dir,
            output_clips_dir=root / project.output_dir / "clips",
            output_final_dir=root / project.output_dir / "final",
            output_logs_dir=root / project.output_dir / "logs",
            output_intermediate_dir=root / project.output_dir / "intermediate",
            state_dir=root / project.state_dir,
            state_jobs_dir=root / project.state_dir / "jobs",
            state_clips_dir=root / project.state_dir / "clips",
            state_qa_dir=root / project.state_dir / "qa",
            assembly_manifest_file=root / project.state_dir / "assembly_manifest.json",
            final_video_file=root / project.output_dir / "final" / "final.mp4",
        )

    def ensure_all(self) -> None:
        """Create every directory this project needs."""
        for d in (
            self.characters_dir,
            self.scenes_dir,
            self.shots_dir,
            self.references_dir,
            self.private_dir,
            self.output_dir,
            self.output_clips_dir,
            self.output_final_dir,
            self.output_logs_dir,
            self.output_intermediate_dir,
            self.state_dir,
            self.state_jobs_dir,
            self.state_clips_dir,
            self.state_qa_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def iter_existing_character_files(self) -> Iterable[Path]:
        if not self.characters_dir.exists():
            return []
        return sorted(self.characters_dir.glob("*.yaml")) + sorted(self.characters_dir.glob("*.yml"))

    def iter_existing_scene_files(self) -> Iterable[Path]:
        if not self.scenes_dir.exists():
            return []
        return sorted(self.scenes_dir.glob("*.yaml")) + sorted(self.scenes_dir.glob("*.yml"))

    def iter_existing_shot_files(self) -> Iterable[Path]:
        if not self.shots_dir.exists():
            return []
        return sorted(self.shots_dir.glob("*.yaml")) + sorted(self.shots_dir.glob("*.yml"))