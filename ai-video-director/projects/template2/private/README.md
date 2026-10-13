# `private/` — ComfyUI workflow JSON for the ref2v template

This template (`template2/`) ships with a real, ready-to-run ComfyUI
workflow that uses the native `MiniMaxH3ReferenceToVideo` node for
character-consistent video generation.

## Files in this directory

| File | Format | Purpose |
|---|---|---|
| `video_workflow_api_r2v.json` | API | Used by the framework at generation time. WorkflowResolver reads this; the adapter patches the prompt, seed, ref images, and duration per shot. |
| `video_workflow_r2v_ui.json`  | UI  | **For humans.** Drag this file into the ComfyUI frontend (or use the "Load" button in the workflow menu) to see the node graph and inspect the wiring. |

Both files describe the same logical graph; only the on-disk format differs.
API format is what `comfy-cli` and our adapter use; UI format is what the
browser frontend uses.

## How the ref2v workflow works

```
[LoadImage Ref 0] ─┐
[LoadImage Ref 1] ─┼─→ [MiniMax H3 Reference to Video] ─┬─→ [BasicGuider] ─→ [Sampler] ─→ [VAEDecode] ─→ [CreateVideo] ─→ [SaveVideo]
[LoadImage Ref 2] ─┘                                    │
[UNET/CLIP/VAE/Audio-VAE/LoRA] ─────────────────────────┘
```

The `MiniMaxH3ReferenceToVideo` node is the heart of the workflow. It:

1. Encodes each reference image through the video VAE to produce a latent.
2. Encodes the prompt through the CLIP text encoder.
3. Packs the ref latents + text tokens into a single conditioning tensor.
4. Emits the conditioning + an empty target latent that goes into the
   standard sampler chain.

After that, the workflow uses the regular `BasicGuider` +
`SamplerCustomAdvanced` + `VAEDecode` chain to produce the video frames,
and `CreateVideo` + `SaveVideo` to write them out.

## Required models

All paths resolve to `/home/frank/ComfyUI/models/`:

| Node | Model file |
|---|---|
| `Load Diffusion Model` (UNETLoader) | `diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| `Load CLIP` (CLIPLoader) | `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| `Load VAE (Video)` | `vae/minimax_h3_video_vae_int8_convrot.safetensors` |
| `Load VAE (Audio)` | `vae/minimax_h3_audio_vae_fp32.safetensors` |
| `Load LoRA (Ref2V Turbo, optional)` | `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` |

The LoRA is loaded but its `strength_model` is set to `0.0` by default,
so it's effectively bypassed. To enable 4-step turbo sampling, edit the
workflow JSON and:

1. Set `14.inputs.strength_model` to `1.0`
2. Set `43.inputs.steps` to `4`

Without the LoRA, leave the workflow as-is and the model runs in 20-step
default mode (slower but more flexible).

## Reference image slots

| Slot | ComfyUI node | Adapter writes |
|---|---|---|
| `ref_image_0` | `Load Image Ref 0` | First reference (face preferred) |
| `ref_image_1` | `Load Image Ref 1` | Second reference (full / side) |
| `ref_image_2` | `Load Image Ref 2` | Third reference (any other type) |

The runner sorts the character card's `reference_images` list by
`image_type` priority and assigns them in order. You don't need to
manage slot indices in your character cards.

To support more than 3 reference images:

1. Add `ref_image_3: "Load Image Ref 3"` (and beyond) to
   `workflow.yaml:reference_image_nodes`.
2. Add the matching `LoadImage` node to the workflow JSON and wire it
   into the ref2v node's `ref_images.ref_image_<i>` input.

## Prompt format

The `Prompt` node is a `PrimitiveStringMultiline` whose value is patched
per shot. The framework writes the shot's `prompt` field directly.

For best face-lock results, reference your characters explicitly in the
prompt. For example:

> A cinematic medium shot of <Picture 1> in profile, looking over her
> shoulder. The face from <Picture 1> is preserved exactly.

You can also use the MiniMax-H3 ref tags directly. The native ref2v node
accepts `<Picture 1>`, `<Picture 2>`, `<Video 1>`, `<Audio 1>` style
references. The framework's adapter doesn't auto-rewrite the prompt —
add these tags to your shot's `prompt` field if you want them.

## Editing the workflow

To customise the workflow (e.g. add a 4th reference image, change the
sampler, add upscaling):

1. Open `video_workflow_r2v_ui.json` in the ComfyUI frontend
   (drag-and-drop, or Load from the menu).
2. Make your changes.
3. Export the workflow back to API format:
   - In the menu: "Save (API Format)" → save as
     `video_workflow_api_r2v.json`, overwriting the existing file.
   - Or: "Save" → save as `video_workflow_r2v_ui.json` if you want to
     keep the human-readable copy too.

If you only edit the API file by hand, run the workflow through ComfyUI
once and re-export to UI format to keep the human copy in sync.
