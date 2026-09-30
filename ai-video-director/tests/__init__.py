"""Test package init.

Importing the comfyui backend here ensures its ``register_generator`` side
effect runs before any test inspects the registry.
"""

from video_director.generators.comfyui import backend  # noqa: F401  (registers "comfyui")
