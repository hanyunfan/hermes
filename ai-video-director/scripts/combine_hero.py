"""Composite the male and female hero references into one side-by-side
image so the second real shot (shot_002) can use it as its first frame.

Output: projects/new_grok_story/imports/references/combined/hero.jpg
"""
from PIL import Image
import os
import sys

REF_DIR = "projects/new_grok_story/imports/references"
H = 1024  # common height


def resize_h(img: Image.Image, target_h: int) -> Image.Image:
    w, h = img.size
    new_w = int(w * target_h / h)
    return img.resize((new_w, target_h), Image.LANCZOS)


def main() -> int:
    woman = Image.open(f"{REF_DIR}/young_woman/hero.jpg")
    man = Image.open(f"{REF_DIR}/young_man/hero.jpg")
    print(f"woman: {woman.size}  man: {man.size}", file=sys.stderr)

    w_r = resize_h(woman, H)
    m_r = resize_h(man, H)
    print(f"after resize: woman={w_r.size}  man={m_r.size}", file=sys.stderr)

    gap = 32
    total_w = w_r.size[0] + gap + m_r.size[0]
    combined = Image.new("RGB", (total_w, H), (255, 255, 255))
    combined.paste(w_r, (0, 0))
    combined.paste(m_r, (w_r.size[0] + gap, 0))

    out_dir = os.path.join(REF_DIR, "combined")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "hero.jpg")
    combined.save(out, "JPEG", quality=92)
    print(f"saved: {out}  size={combined.size}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())