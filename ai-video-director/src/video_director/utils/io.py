"""I/O helpers: YAML/JSON read/write, path utilities, safe-filename helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, IO

import yaml


def read_yaml(path: str | os.PathLike[str]) -> Any:
    """Read a YAML file. Returns ``None`` if the file is empty."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return yaml.safe_load(text)


def write_yaml(path: str | os.PathLike[str], data: Any) -> None:
    """Atomically write ``data`` to YAML at ``path``."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            _jsonable(data),
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    os.replace(tmp, p)


def read_json(path: str | os.PathLike[str]) -> Any:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSON file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return json.loads(text)


def write_json(
    path: str | os.PathLike[str],
    data: Any,
    *,
    indent: int = 2,
    ensure_parents: bool = True,
) -> None:
    p = Path(path)
    if ensure_parents:
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(_jsonable(data), f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def _jsonable(obj: Any) -> Any:
    """Coerce enum / dataclass values so JSON/YAML dump happily."""
    # Enums (including str-based ones) stringify via their .value
    if hasattr(obj, "value") and hasattr(obj, "__class__") and not isinstance(obj, type):
        try:
            return obj.value  # type: ignore[attr-defined]
        except Exception:
            pass
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    """Sanitise a user-supplied filename so it can safely live in a path."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in name.strip())
    out = out.replace("..", "_").strip().strip(".")
    return out or "untitled"


def open_for_write(path: str | os.PathLike[str]) -> IO[bytes]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p.open("wb")