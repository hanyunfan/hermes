"""Project registry + lifecycle.

Responsibilities:
  * discover projects under ``projects/``
  * create new project skeletons from the template
  * load/save ``project.yaml``, ``story.yaml``, characters, scenes, shots
  * never mutate a project outside its own directory
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..models import Project, Story, Character, Scene, Shot, WorkflowMapping
from ..utils.io import (
    read_yaml,
    write_yaml,
    ensure_dir,
    safe_filename,
)
from .errors import (
    ProjectExistsError,
    ProjectNotFoundError,
    ValidationError,
)
from .paths import ProjectPaths


TEMPLATE_DIR_NAME = "template"


@dataclass
class ProjectInfo:
    """Lightweight summary of a project for the registry."""

    project_id: str
    title: str
    path: Path
    status: str = "draft"


class ProjectManager:
    """Coordinates project discovery + I/O.

    All paths are interpreted relative to ``root_dir``, which is the
    directory that contains ``projects/<id>/`` and the public
    ``projects/template/`` skeleton.
    """

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).resolve()
        self.projects_dir = self.root_dir / "projects"
        self.template_dir = self.projects_dir / TEMPLATE_DIR_NAME

    # ---- discovery ----------------------------------------------------

    def list_projects(self, include_template: bool = False) -> list[ProjectInfo]:
        if not self.projects_dir.exists():
            return []
        out: list[ProjectInfo] = []
        for child in sorted(self.projects_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name == TEMPLATE_DIR_NAME and not include_template:
                continue
            if child.name.startswith("."):
                continue
            proj_file = child / "project.yaml"
            if not proj_file.exists():
                # Not a project (could be user droppings). Skip silently.
                continue
            try:
                p = self.load_project(child)
                out.append(
                    ProjectInfo(
                        project_id=p.project_id,
                        title=p.title,
                        path=child,
                        status=p.status,
                    )
                )
            except Exception:
                # Corrupt project file — skip but don't blow up the registry.
                continue
        return out

    def get_project_paths(self, project_id: str) -> ProjectPaths:
        """Resolve paths without loading ``project.yaml`` yet.

        Used during ``init`` when we need the paths to *write* project.yaml.
        """
        project_dir = self.projects_dir / project_id
        if project_id == TEMPLATE_DIR_NAME:
            raise ProjectNotFoundError(f"{project_id!r} is reserved for the template")
        if not project_dir.exists():
            raise ProjectNotFoundError(f"project not found: {project_id}")
        # Use the on-disk layout (project.yaml not yet written)
        placeholder = Project(
            project_id=project_id,
            title="",
        )
        return ProjectPaths.from_project(project_dir, placeholder)

    def load_project(self, project_dir: str | Path) -> Project:
        """Load ``project.yaml`` and resolve paths."""
        project_dir = Path(project_dir)
        if not project_dir.is_absolute():
            project_dir = (self.projects_dir / project_dir).resolve()
        project_file = project_dir / "project.yaml"
        if not project_file.exists():
            raise ProjectNotFoundError(f"project.yaml not found in {project_dir}")
        data = read_yaml(project_file)
        if not isinstance(data, dict):
            raise ValidationError(f"project.yaml is not a mapping: {project_file}")
        project = Project.from_dict(data)
        # Cross-check: project_id in file must match the directory name
        if project.project_id != project_dir.name:
            raise ValidationError(
                f"project.yaml project_id={project.project_id!r} does not match "
                f"directory name={project_dir.name!r}"
            )
        return project

    def paths_for(self, project: Project) -> ProjectPaths:
        return ProjectPaths.from_project(self.projects_dir / project.project_id, project)

    def paths_for_id(self, project_id: str) -> ProjectPaths:
        project_dir = self.projects_dir / project_id
        if not project_dir.exists():
            raise ProjectNotFoundError(f"project not found: {project_id}")
        return self.get_project_paths(project_id)

    # ---- creation -----------------------------------------------------

    def init_project(
        self,
        project_id: str,
        *,
        title: str = "",
        description: str = "",
        language: str = "en",
        target_duration_sec: float = 0.0,
        from_template: bool = True,
        template_name: str = TEMPLATE_DIR_NAME,
    ) -> Project:
        """Create a new project skeleton.

        If ``from_template`` is true, copies everything from
        ``projects/<template_name>/`` (default ``template/``, can be set
        to ``template2/`` or any other template variant). Excludes
        ``output/`` and ``state/`` which are regenerated fresh.
        """
        if project_id == template_name:
            raise ValidationError(f"{project_id!r} is a reserved project name")
        project_dir = self.projects_dir / project_id
        if project_dir.exists():
            raise ProjectExistsError(f"project already exists: {project_id}")
        ensure_dir(project_dir)
        if from_template:
            template_dir = self.projects_dir / template_name
            if not template_dir.exists():
                raise ValidationError(
                    f"template directory not found: {template_dir}"
                )
            shutil.copytree(template_dir, project_dir, dirs_exist_ok=True)
            # Wipe runtime artefacts the template only ships as placeholders
            for sub in ("output", "state"):
                target = project_dir / sub
                if target.exists():
                    shutil.rmtree(target)
        # Always create these fresh
        for sub in ("characters", "scenes", "shots", "references", "private"):
            ensure_dir(project_dir / sub)
        for child in ("clips", "final", "logs", "intermediate"):
            ensure_dir(project_dir / "output" / child)
        for child in ("jobs", "clips", "qa"):
            ensure_dir(project_dir / "state" / child)
        ensure_dir(project_dir / "output")
        ensure_dir(project_dir / "state")
        project = Project(
            project_id=project_id,
            title=title or project_id.replace("-", " ").title(),
            description=description,
            language=language,
            target_duration_sec=target_duration_sec,
        )
        self.save_project(project)
        return project

    # ---- persistence --------------------------------------------------

    def save_project(self, project: Project) -> None:
        paths = self.paths_for(project)
        paths.ensure_all()
        write_yaml(paths.project_file, project.to_dict())

    def load_story(self, paths: ProjectPaths) -> Story | None:
        if not paths.story_file.exists():
            return None
        data = read_yaml(paths.story_file)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError(f"story.yaml is not a mapping: {paths.story_file}")
        return Story.from_dict(data)

    def save_story(self, paths: ProjectPaths, story: Story) -> None:
        write_yaml(paths.story_file, story.to_dict())

    def load_workflow_mapping(self, paths: ProjectPaths) -> WorkflowMapping | None:
        if not paths.workflow_mapping_file.exists():
            return None
        data = read_yaml(paths.workflow_mapping_file)
        if not data:
            return WorkflowMapping()
        if not isinstance(data, dict):
            raise ValidationError(
                f"workflow.yaml is not a mapping: {paths.workflow_mapping_file}"
            )
        return WorkflowMapping.from_dict(data)

    def save_workflow_mapping(self, paths: ProjectPaths, mapping: WorkflowMapping) -> None:
        write_yaml(paths.workflow_mapping_file, mapping.to_dict())

    # ---- character / scene / shot loaders -----------------------------

    def iter_characters(self, paths: ProjectPaths) -> Iterator[Character]:
        for f in paths.iter_existing_character_files():
            data = read_yaml(f)
            if data:
                yield Character.from_dict(data)

    def iter_scenes(self, paths: ProjectPaths) -> Iterator[Scene]:
        for f in paths.iter_existing_scene_files():
            data = read_yaml(f)
            if data:
                yield Scene.from_dict(data)

    def iter_shots(self, paths: ProjectPaths) -> Iterator[Shot]:
        for f in paths.iter_existing_shot_files():
            data = read_yaml(f)
            if data:
                yield Shot.from_dict(data)

    def save_character(self, paths: ProjectPaths, character: Character) -> None:
        ensure_dir(paths.characters_dir)
        fname = safe_filename(character.character_id) + ".yaml"
        write_yaml(paths.characters_dir / fname, character.to_dict())

    def save_scene(self, paths: ProjectPaths, scene: Scene) -> None:
        ensure_dir(paths.scenes_dir)
        fname = safe_filename(scene.scene_id) + ".yaml"
        write_yaml(paths.scenes_dir / fname, scene.to_dict())

    def save_shot(self, paths: ProjectPaths, shot: Shot) -> None:
        ensure_dir(paths.shots_dir)
        fname = safe_filename(shot.shot_id) + ".yaml"
        write_yaml(paths.shots_dir / fname, shot.to_dict())

    # ---- convenience --------------------------------------------------

    def project_root_for(self, project_id: str) -> Path:
        return self.projects_dir / project_id