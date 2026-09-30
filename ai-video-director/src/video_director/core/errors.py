"""Common framework errors."""


class ProjectError(Exception):
    """Base class for project-level errors."""


class ProjectExistsError(ProjectError):
    """Raised when ``init`` is called on an existing project id."""


class ProjectNotFoundError(ProjectError):
    """Raised when a project id is not registered under ``projects/``."""


class ValidationError(ProjectError):
    """Raised when a project asset fails validation (missing files, bad schema, ...)."""


class WorkflowNotFoundError(ProjectError):
    """Raised when the user-provided ComfyUI workflow JSON cannot be located."""


class GenerationError(ProjectError):
    """Raised by backends when generation fails."""


class QAFailure(ProjectError):
    """Raised when QA rejects a clip."""


class AssemblyError(ProjectError):
    """Raised when the FFmpeg assembly step fails."""