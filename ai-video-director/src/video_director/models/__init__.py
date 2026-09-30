"""Data models for projects, stories, characters, scenes, shots, jobs, and clips.

All models are deliberately framework-agnostic dataclasses so they can be
serialised to/from YAML/JSON without external dependencies. Validation lives
here, not in callers.
"""

from .enums import (
    JobStatus,
    ShotStatus,
    ContinuityAspect,
    GenerationState,
)
from .project import Project
from .story import Story, StoryBible, ScriptSection
from .character import Character, CharacterReference, CharacterBible
from .scene import Scene
from .shot import Shot
from .workflow import WorkflowMapping, WorkflowTemplate
from .job import GenerationJob, VideoClip, Audio, FinalVideo, AssemblyManifest
from .continuity import ContinuityState, ContinuityRule

__all__ = [
    "JobStatus",
    "ShotStatus",
    "ContinuityAspect",
    "GenerationState",
    "Project",
    "Story",
    "StoryBible",
    "ScriptSection",
    "Character",
    "CharacterReference",
    "CharacterBible",
    "Scene",
    "Shot",
    "WorkflowMapping",
    "WorkflowTemplate",
    "GenerationJob",
    "VideoClip",
    "Audio",
    "FinalVideo",
    "AssemblyManifest",
    "ContinuityState",
    "ContinuityRule",
]