"""Subpackage marker."""

from .base import VideoGenerator, GeneratorCapabilities
from .mock import MockVideoGenerator
from .registry import GeneratorRegistry, get_registry, register_generator

# Import the ComfyUI backend so its module-level ``register_generator("comfyui", ...)``
# call runs and the production registry lists the backend. Without this import
# only ``mock`` is registered and ``--backend comfyui`` fails with
# "unknown backend 'comfyui'". See tests/__init__.py for the same workaround.
from .comfyui import ComfyUIGenerator  # noqa: F401  (registers "comfyui")

__all__ = [
    "VideoGenerator",
    "GeneratorCapabilities",
    "MockVideoGenerator",
    "ComfyUIGenerator",
    "GeneratorRegistry",
    "get_registry",
    "register_generator",
]