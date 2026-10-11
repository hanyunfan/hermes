# Reference images (PLACEHOLDER)

Drop character reference images here:

```
references/
├── example_character_a/
│   ├── hero.png        # full-body or primary reference
│   ├── face.png        # close-up face
│   └── costume_01.png  # optional variant
└── example_character_b/
    └── hero.png
```

## Rules

1. Real human faces are sensitive — make sure the user owns the images or has
   permission to use them.
2. Keep filenames lowercase, no spaces. They are referenced from
   `characters/*.yaml` → `reference_images[].path`.
3. The whole `references/` directory is **gitignored**. Do not commit it.

## Format / size

- PNG or JPG are both fine.
- 1024x1024 or larger for the hero shot.
- The runner passes paths to the backend; the backend (ComfyUI) handles
  upload / load.