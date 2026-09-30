"""Generator registry.

Backends are registered by string name; the runner looks them up by name.
Built-ins: ``mock``. ComfyUI lives in :mod:`video_director.generators.comfyui`
and registers itself on import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .base import VideoGenerator
from .mock import MockVideoGenerator


@dataclass
class GeneratorRegistry:
    """Maps ``name -> factory()`` so projects can pick a backend by config."""

    _factories: dict[str, Callable[[], VideoGenerator]] = field(default_factory=dict)

    def register(self, name: str, factory: Callable[[], VideoGenerator]) -> None:
        self._factories[name] = factory

    def names(self) -> list[str]:
        return sorted(self._factories)

    def create(self, name: str) -> VideoGenerator:
        if name not in self._factories:
            raise KeyError(
                f"unknown backend {name!r}; known: {self.names()}"
            )
        return self._factories[name]()


_REGISTRY = GeneratorRegistry()
_REGISTRY.register("mock", MockVideoGenerator)


def get_registry() -> GeneratorRegistry:
    return _REGISTRY


def register_generator(name: str, factory: Callable[[], VideoGenerator]) -> None:
    _REGISTRY.register(name, factory)