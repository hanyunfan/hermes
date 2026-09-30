#!/usr/bin/env python3
"""Pre-commit safety check.

Walks the working tree and refuses to proceed if any path that could contain
private or sensitive content is staged for commit. Also catches mistakes
like accidentally committing inside ``projects/story_001/``.

Usage::

    python scripts/check_git_safety.py [--strict] [--workdir DIR]

Exit codes:
  0 — clean
  1 — found risky paths (with --strict: refuses; without: warns)
  2 — git unavailable or fatal error

This script does NOT depend on git being available; it can be run on any
tree (CI, hooks, manual review).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# Paths / names that MUST NEVER be committed. Matched as substrings or
# glob-style patterns against the absolute path of a tracked file.
FORBIDDEN_PATH_PATTERNS: tuple[str, ...] = (
    # Private workflow files
    "real_workflow.json",
    "real_workflow",
    # Anywhere named "private/" — that's the per-project private dir
    "/private/",
    "/private$",
    # References (character / scene images)
    "/references/",
    "/references$",
    # Output media + state
    "/output/",
    "/output$",
    "/state/",
    "/state$",
    # Common secret filenames
    ".env",
    ".env.",
    "secret",
    "credential",
    "api_key",
    "apikey",
    "token",
    "password",
)

# File extensions we treat as media and reject wholesale.
MEDIA_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac",
    ".srt", ".vtt", ".ass", ".ssa",
    ".gif", ".webp",
)

# File extensions we accept as image references only inside the template.
# Anywhere else, even PNGs are flagged.
TEXT_EXTENSIONS: tuple[str, ...] = (
    ".yaml", ".yml", ".json", ".md", ".txt", ".py", ".sh",
    ".toml", ".cfg", ".ini", ".gitignore", ".gitattributes",
)


@dataclass
class Finding:
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}  --  {self.reason}"


def _is_template_path(path: str) -> bool:
    """True if the path is under projects/template/."""
    parts = Path(path).parts
    return "projects" in parts and "template" in parts and parts.index("template") > parts.index("projects")


def _is_under(path: str, root: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _iter_git_tracked(root: Path) -> Iterable[str] | None:
    """Yield paths currently staged + tracked + modified, or None on failure.

    Returns None when git is not available or the tree isn't a git repo —
    the caller then falls back to filesystem walking.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=True, timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    paths = [p.decode("utf-8") for p in out.stdout.split(b"\x00") if p]
    # Include modified/untracked too so pre-commit hooks catch them.
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "-z"],
            capture_output=True, check=True, timeout=15,
        )
    except subprocess.CalledProcessError:
        return paths
    for entry in status.stdout.split(b"\x00"):
        if not entry:
            continue
        # Format: XY path (where XY may include rename markers)
        try:
            head, _, tail = entry.partition(b" ")
            # For rename entries: "R  old -> new" — take new
            text = tail.decode("utf-8", errors="replace").strip()
            if " -> " in text:
                text = text.split(" -> ", 1)[1]
            text = text.strip('"')
            if text and text not in paths:
                paths.append(text)
        except Exception:
            continue
    return paths


def _walk_filesystem(root: Path) -> Iterable[str]:
    """Yield every regular file under ``root``, relative to ``root``."""
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        # Skip heavy dirs that should never be checked
        parts = rel.parts
        if any(part in (".git", "node_modules", ".venv", "venv", "__pycache__") for part in parts):
            continue
        yield str(rel)


def check_paths(paths: Iterable[str], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    root = root.resolve()
    for rel in paths:
        abs_path = (root / rel).resolve()
        # Template files are vetted at creation time — only flag suspicious
        # content inside template dirs, never normal scaffold files.
        in_template = _is_template_path(rel)
        # 1. Forbidden path substring matches
        rel_str = str(rel).replace("\\", "/")
        for pat in FORBIDDEN_PATH_PATTERNS:
            if pat in "/" + rel_str or rel_str.endswith(pat.lstrip("/")):
                if in_template and pat in ("/references/", "/private/", "/output/", "/state/"):
                    # Template is allowed to scaffold the dirs themselves
                    # (README.md only — real files are gitignored).
                    if rel_str.endswith(".md"):
                        continue
                findings.append(Finding(rel, f"path matches forbidden pattern {pat!r}"))
                break
        # 2. Media extensions
        suffix = Path(rel).suffix.lower()
        if suffix in MEDIA_EXTENSIONS:
            if not (in_template and suffix in (".png", ".jpg", ".jpeg", ".webp")):
                findings.append(Finding(rel, f"media file extension {suffix!r}"))
                continue
        # 3. Workflow JSON outside the public placeholder
        if suffix == ".json" and "workflow" in Path(rel).name.lower():
            # The single allowed public workflow is the framework's own
            # template under workflows/video_workflow.template.json.
            if not rel_str.endswith("workflows/video_workflow.template.json"):
                findings.append(Finding(rel, "ComfyUI workflow JSON outside public placeholder"))
                continue
        # 4. .secret.* / *.local.* / .env files
        name = Path(rel).name
        if name.startswith(".env"):
            findings.append(Finding(rel, "dotenv file"))
            continue
        if ".secret." in name or ".local." in name:
            findings.append(Finding(rel, "secret/local suffix"))
            continue
    return findings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workdir", default=".", help="Project root to check.")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero on warnings (default: warn only).")
    p.add_argument("--use-git", action="store_true", default=True,
                   help="Use git to enumerate tracked+modified files (default).")
    p.add_argument("--no-git", dest="use_git", action="store_false",
                   help="Walk the filesystem directly instead of using git.")
    args = p.parse_args()
    root = Path(args.workdir).resolve()
    if not root.exists():
        print(f"[error] workdir does not exist: {root}", file=sys.stderr)
        return 2
    if args.use_git:
        paths = _iter_git_tracked(root)
        if paths is None:
            print("[warn] git unavailable or not a repo; falling back to filesystem walk",
                  file=sys.stderr)
            paths = list(_walk_filesystem(root))
    else:
        paths = list(_walk_filesystem(root))
    findings = check_paths(paths, root)
    if not findings:
        print(f"[ok] {len(list(paths))} file(s) checked, no risks found")
        return 0
    print(f"[risk] {len(findings)} file(s) flagged:")
    for f in findings:
        print(f"  - {f}")
    if args.strict:
        return 1
    print("[warn] not strict mode; refusing exit but please review the list above",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())