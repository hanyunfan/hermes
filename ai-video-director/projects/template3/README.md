# projects/template3 — Motion Context scaffold

## What this is

A project scaffold that points at the
[`seitanism/ComfyUI-H3-Motion-Context-MultiRef`](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef)
plugin. template3 lets ai-video-director route shots through a workflow that
exposes the plugin's multi-ref / masked / music-video node family instead of
the plain `MiniMaxH3ReferenceToVideo` chain used by `template2/`.

## What the plugin adds on top of template2

| Capability | Added by | What it does |
|---|---|---|
| Plain R2V chain | base H3 nodes | template2 already has this |
| **Multi-ref** motion context | `MiniMaxH3SongMaskedAVContext` | multiple motion sources at once |
| **Masked keyframes** | `MiniMaxH3MaskedKeyframes*` | time/space masks on refs |
| **AV Bridge** | `MiniMaxH3AVBridge` | transition between two known videos |
| **Music Video controller** | `MiniMaxH3MusicVideoController` | one master song driving many clips |
| **V2V fractional motion transfer** | `MiniMaxH3V2VFractionalStrength` | 1/4096-step denoise between two videos |
| **2MP De-Rope continuation** | Multi-pass de-rope seam placement | long continuation from a short seed |
| **Custom Keyframes** | `MiniMaxH3CustomKeyframes` | place image guides along a generation |

Under the hood, all of these still call `MiniMaxH3ReferenceToVideo` (the same
H3 node template2 uses). The plugin adds orchestration + masking, not new
model nodes.

## What template3 does NOT ship with this scaffold

### 1. No fabricated workflow JSON

**The single most important rule:**

> DO NOT hand-craft `private/video_workflow_api_motion_context.json`.
> Export it from the ComfyUI frontend after loading the plugin's example
> workflow. A fabricated JSON will not match the title lookups the framework
> does — `WorkflowMapping.prompt_node` and friends are matched by node
> title (not numeric id), so any title drift makes the runner TypeError.

### 2. No plugin install inside this scaffold

The plugin lives under `ComfyUI/custom_nodes/`, **not** inside
`projects/template3/`. ai-video-director does NOT own the ComfyUI runtime.
Whoever maintains the ComfyUI host owns the plugin install.

## Setup recipe

### Step 1 — install plugin + dependencies

```bash
# 1.1 plugin itself (already pulled under /tmp during exploration)
cd /home/frank/ComfyUI/custom_nodes
git clone https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef.git
# NOTE: the original repo URL the user gave — "seitanism/ComfyUI-H3-Motion-Context"
# — does not exist. The correct name is "-MultiRef" (this fork).
# We verify on 2026-10-19. If the repo is renamed again, search GitHub:
#   https://api.github.com/search/repositories?q=ComfyUI+H3+Motion+Context

# 1.2 additional packs called for by workflows (NOT all used by every example)
#    Decide per workflow — see "Workflow pick → required packs" below.
cd /home/frank/ComfyUI/custom_nodes
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite   # VHS — Music Video / AV Extension / V2V / 2MP De-Rope
git clone https://github.com/kijai/ComfyUI-KJNodes                    # KJNodes — 2MP De-Rope
git clone https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler  # 2MP De-Rope ONLY
# Skip ComfyUI-SolAttn_triton unless RTX 4090 / H100 — Triton kernels are GPU-specific.

# 1.3 restart ComfyUI so it picks up the new custom nodes
# (auto Restart=always systemd unit restarts after ~12s; just wait)
```

### Step 2 — verify plugin loads without error

```bash
curl -s http://127.0.0.1:8188/system_stats \
  | jq -r '.system.comfyui_version, .system.python_version'
# expected: comfyui_version ~ 0.37.0 (we run 0.37 in this box)

# then look for these node classes in any workflow you can submit:
curl -s http://127.0.0.1:8188/object_info \
  | jq '.["MiniMaxH3MusicVideoController"], .["MiniMaxH3SongMaskedAVContext"]' | head -20
# expected: non-null entries
```

If those nodes are missing, the plugin didn't load. Check journalctl for the
exception during restart (`RestartSec=10` brings it back fast).

### Step 3 — get a workflow JSON

Pick **one** of the 5 example workflows from the plugin repo:

| Example | What it does | Min packs |
|---|---|---|
| `NEW - Music Video.json` | One master song + N clips conditioned on it | VHS |
| `NEW - AV Extension.json` | Continue an existing video OR generate + extend | VHS |
| `NEW - V2V Latent Motion Transfer (with upscale and de-rope).json` | Motion A→B + upscale + de-rope | VHS + KJNodes + Latent-Upscaler |
| `NEW - 2MP De-Rope Continuation.json` | Two-pass continuation with dynamic seam | VHS + KJNodes + Latent-Upscaler + SolAttn_triton |
| `UTILITY - AV Bridge.json` | Transition between two known videos | VHS |
| `UTILITY - Custom Keyframes.json` | Image guides along a generation | None beyond the main plugin |

In ComfyUI's frontend:

1. Click **Load** in the workflow panel
2. Pick the file from the list
3. Verify it loads (no orange "node not found" warnings)
4. If it has unsatisfied input references (missing models, packs), fix per
   WORKFLOW_PREREQUISITES.md
5. Click **Save (API format)** — file will land where you tell it
6. Move it to `projects/template3/private/video_workflow_api_motion_context.json`

⚠️ Do NOT hand-edit the title strings in the resulting JSON. The framework's
`WorkflowMapping` looks them up by title (e.g. `Prompt` / `RandomNoise`).
Many of the plugin's controller nodes have multi-word titles; verify the
mapping file still works:

```bash
cd /home/frank/hermes/ai-video-director
.venv/bin/video-director validate-imports template3
```

If titles drift, the resolver returns `ValidationError: workflow mapping
references prompt_node='<title>' but no node with that title exists`.

### Step 4 — run the framework against this template

```bash
cd /home/frank/hermes/ai-video-director
.venv/bin/video-director generate template3 --backend comfyui --max-retries 2 \
    > projects/template3/output/logs/run_$(date +%Y%m%d_%H%M%S).log 2>&1
```

The runner uses `workflow.yaml`'s `workflow_path` to load the JSON, resolves
prompt / ref_video / ref_image / output nodes by title, and submits shots
the same way `template2` works. Plugin-only nodes are simply not touched by
the adapter; the framework doesn't need to know about them.

## Model prerequisites (vs what template2 already needed)

| Model | template2 | template3 |
|---|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | ✅ have | ✅ same |
| `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | ✅ have | ✅ same (note: WORKFLOW_PREREQUISITES prefers `qwen3vl_32b_minimax_h3_int8_convrot` but our nvfp4 variant is H3-native, should still work) |
| `minimax_h3_video_vae_fp16.safetensors` | ✅ have | ✅ same |
| `minimax_h3_audio_vae_fp32.safetensors` | ✅ have | ✅ same |
| `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | ✅ have | ✅ same |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | — | ✅ listed in plugin workflows, may need to drop |
| `minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors` | — | ✅ optional, for some example workflows |

## GPU + runtime requirements

MiniMax-H3 is large. We confirmed this scaffold only fires if:

- **GPU present** (RTX PRO 4500 in our box). Plugin's CPU regression tests
  use Python 3.12 + PyTorch 2.14 cpu, but real inference is NOT supported
  on CPU per the plugin's own README.
- **PyTorch 2.14.0+** (we run this via ComfyUI's venv).
- **torchaudio** for audio resampling (VHS uses it for output audio mux).

## Compatibility risk

Plugin `WORKFLOW_PREREQUISITES.md` says workflows were authored against
**ComfyUI 0.30-0.33**. Our box runs **0.37.0**. The framework's last
couple of feature updates (NikoDemon80's `MiniMaxH3ReferenceToVideo` and
its siblings) keep the public class names stable across 0.30 → 0.37, but
internal execution layer changes (e.g. `ModelSamplingAdvanced` API) could
silently affect plugin behavior at submission time. **Watch for the
first-run log for tracebacks from plugin nodes.**

## What this scaffold is / is not

| | Yes | No |
|---|---|---|
| ships a placeholder workflow.yaml | ✅ | |
| ships characters, story, project metadata | ✅ | |
| ships models | | ❌ |
| installs the plugin | | ❌ — ComfyUI host's job |
| runs end-to-end "out of the box" | | ❌ — needs step 1-3 first |
| is identical to template2 capability-wise | | ❌ — plugin adds 5 capabilities above |

## Reference

- Plugin README: https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef
- Plugin prerequisite manifest: `WORKFLOW_PREREQUISITES.md` in plugin repo
- Upstream fork: https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context
- Underlying H3 nodes: `/home/frank/ComfyUI/comfy_extras/nodes_minimax_h3.py`
  (already present in ComfyUI 0.37)

Last verified: 2026-10-19.
