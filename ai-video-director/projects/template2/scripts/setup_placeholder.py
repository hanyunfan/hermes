#!/usr/bin/env python3
"""Generate the placeholder mp4 that the ref_videos_0 chain needs
for shot 1 (which has no previous shot).

This is idempotent — running it twice produces the same file.

Usage:
    python3 scripts/setup_placeholder.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEFAULT_OUT = Path("/home/frank/ComfyUI/input/placeholder_prev_shot.mp4")
DURATION_SEC = 1.0
WIDTH = 320
HEIGHT = 240
FPS = 24


def main() -> int:
    if DEFAULT_OUT.exists() and DEFAULT_OUT.stat().st_size > 0:
        print(f"  {DEFAULT_OUT} already exists ({DEFAULT_OUT.stat().st_size} B); skipping")
        return 0
    DEFAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={DURATION_SEC}",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        str(DEFAULT_OUT),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ffmpeg failed: {r.stderr}", file=sys.stderr)
        return r.returncode
    if not DEFAULT_OUT.exists():
        print(f"  ffmpeg claimed success but {DEFAULT_OUT} missing", file=sys.stderr)
        return 1
    print(f"  created: {DEFAULT_OUT}  ({DEFAULT_OUT.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
