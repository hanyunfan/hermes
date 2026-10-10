"""Video-Director CLI entry point.

Standard usage:

    video-director init    <project>
    video-director list
    video-director analyze <project>
    video-director storyboard <project>
    video-director validate  <project>
    video-director generate  <project> [--backend mock|comfyui] [--max-retries N]
    video-director status    <project> [--json]
    video-director retry     <project> [--shot id[,id...]] [--reset-all]
    video-director assemble  <project> [--skip-qa] [--allow-qa-fail]
    video-director run       <project>

All commands take ``--root <dir>`` (default: ``$VIDEO_DIRECTOR_ROOT`` or cwd)
to point at the framework root containing ``projects/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cmd_init, cmd_analyze, cmd_storyboard, cmd_validate
from . import cmd_generate, cmd_status, cmd_assemble, cmd_retry, cmd_run, cmd_list
from . import cmd_validate_imports, cmd_build
from .common import make_project_manager, print_error


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-director",
        description="AI long-form story video production framework",
    )
    p.add_argument(
        "--root",
        default=None,
        help="Framework root directory (default: $VIDEO_DIRECTOR_ROOT or cwd).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_project_arg(sp, *, required: bool = True) -> None:
        sp.add_argument("project", help="Project id (under projects/<project>/)")

    sp = sub.add_parser("init", help="Create a new project skeleton.")
    add_project_arg(sp)
    sp.add_argument("--title", default="")
    sp.add_argument("--description", default="")
    sp.add_argument("--language", default="en")
    sp.add_argument("--duration", type=float, default=0.0,
                    help="Target duration in seconds (advisory only).")
    sp.add_argument("--no-template", action="store_true",
                    help="Skip copying projects/template/ into the new project.")

    sp = sub.add_parser("list", help="List registered projects.")
    sp.add_argument("--include-template", action="store_true")

    sp = sub.add_parser("analyze", help="Build a StoryBible from story.yaml.")
    add_project_arg(sp)

    sp = sub.add_parser("storyboard", help="Build scenes + shots from story.yaml.")
    add_project_arg(sp)

    sp = sub.add_parser("validate", help="Validate a project's assets + continuity.")
    add_project_arg(sp)

    sp = sub.add_parser("validate-imports",
                        help="Validate projects/<id>/imports/*.json before building yaml.")
    add_project_arg(sp)

    sp = sub.add_parser("build",
                        help="Convert imports/*.json into framework yaml.")
    add_project_arg(sp)

    sp = sub.add_parser("generate", help="Generate clips for every shot.")
    add_project_arg(sp)
    sp.add_argument("--backend", default="mock", choices=["mock", "comfyui"])
    sp.add_argument("--max-concurrent-jobs", type=int, default=1)
    sp.add_argument("--max-retries", type=int, default=3)
    sp.add_argument("--no-new-seed", action="store_true",
                    help="Keep the original seed across retries.")
    sp.add_argument("--only", default=None,
                    help="Comma-separated shot ids to (re)generate.")
    sp.add_argument("--reset", action="store_true",
                    help="Wipe all prior jobs/clips before running.")
    sp.add_argument("--force", action="store_true",
                    help="Regenerate even if mp4 already exists in output/clips/.")

    sp = sub.add_parser("status", help="Print run state.")
    add_project_arg(sp)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("assemble", help="Concatenate clips into final.mp4.")
    add_project_arg(sp)
    sp.add_argument("--skip-qa", action="store_true",
                    help="Skip the QA pass over clips before assembly.")
    sp.add_argument("--allow-qa-fail", action="store_true",
                    help="Proceed with assembly even if QA rejects some clips.")
    sp.add_argument("--width", type=int, default=None)
    sp.add_argument("--height", type=int, default=None)
    sp.add_argument("--audio", action="append", default=None,
                    help="Audio track path; pass multiple times for multiple tracks.")
    sp.add_argument("--audio-kind", action="append", default=None,
                    help="One of: voice, bgm, sfx. Pairs with --audio.")

    sp = sub.add_parser("retry", help="Re-run generation for selected shots.")
    add_project_arg(sp)
    sp.add_argument("--shot", default=None,
                    help="Comma-separated shot ids whose state to clear + rerun.")
    sp.add_argument("--reset-all", action="store_true",
                    help="Clear ALL state before re-running.")
    sp.add_argument("--backend", default="mock", choices=["mock", "comfyui"])
    sp.add_argument("--max-concurrent-jobs", type=int, default=1)
    sp.add_argument("--max-retries", type=int, default=3)
    sp.add_argument("--no-new-seed", action="store_true")

    sp = sub.add_parser("run", help="analyze → storyboard → generate → assemble.")
    add_project_arg(sp)
    sp.add_argument("--backend", default="mock", choices=["mock", "comfyui"])
    sp.add_argument("--max-concurrent-jobs", type=int, default=1)
    sp.add_argument("--max-retries", type=int, default=3)
    sp.add_argument("--no-new-seed", action="store_true")

    return p


def _dispatch(args, pm) -> int:
    cmd = args.command
    if cmd == "init":
        return cmd_init.run(args, pm)
    if cmd == "list":
        return cmd_list.run(args, pm)
    if cmd == "analyze":
        return cmd_analyze.run(args, pm)
    if cmd == "storyboard":
        return cmd_storyboard.run(args, pm)
    if cmd == "validate":
        return cmd_validate.run(args, pm)
    if cmd == "validate-imports":
        return cmd_validate_imports.run(args, pm)
    if cmd == "build":
        return cmd_build.run(args, pm)
    if cmd == "generate":
        return cmd_generate.run(args, pm)
    if cmd == "status":
        return cmd_status.run(args, pm)
    if cmd == "assemble":
        return cmd_assemble.run(args, pm)
    if cmd == "retry":
        return cmd_retry.run(args, pm)
    if cmd == "run":
        return cmd_run.run(args, pm)
    print(f"unknown command: {cmd}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pm = make_project_manager(args.root)
    return _dispatch(args, pm)


if __name__ == "__main__":
    sys.exit(main())