"""Subpackage marker."""

from .base import VideoGenerator, GeneratorCapabilities
from .mock import MockVideoGenerator
from .registry import GeneratorRegistry, get_registry, register_generator

__all__ = [
    "VideoGenerator",
    "GeneratorCapabilities",
    "MockVideoGenerator",
    "GeneratorRegistry",
    "get_registry",
    "register_generator",
]