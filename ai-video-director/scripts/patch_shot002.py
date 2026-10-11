"""Update shot_002 in shots.json to use the combined hero image
as its first frame (manual source, since shot_001 is a quick check
that doesn't enter the final video)."""
import json
import sys

PATH = "projects/new_grok_story/imports/shots.json"


def main() -> int:
    with open(PATH) as f:
        shots = json.load(f)
    s2 = shots[1]
    s2["start_frame_source"] = "manual"
    s2["start_frame"] = "imports/references/combined/hero.jpg"
    with open(PATH, "w") as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)
    print(f"shot_002 updated: start_frame_source={s2['start_frame_source']!r}  start_frame={s2['start_frame']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())