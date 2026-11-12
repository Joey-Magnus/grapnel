# DLSS 5 neural rendering

The Insert menu's **Neural** tab: a model run over each finished frame at present time. Off by default; with it off the
renderer does nothing of this and the device is made exactly as without it (below, "What is asked of the device").

## What it is

DLSS 5 neural rendering (DLSS-NR; NVIDIA's own name for it is *3D-Guided Neural Rendering*) is easily taken for
something that needs ray tracing. It does not. That guess conflates it with **DLSS Ray Reconstruction** (NGX's `DLSSD`),
which denoises a ray-traced image and needs a G-buffer -- albedo, normals, roughness -- that a recompilation of a
rasterized game does not have. DLSS-NR is a different feature with different inputs. NVIDIA's public Streamline headers
name them:

```
sl_core_types.h:210  kBufferTypeUpliftInputColor  = 70
sl_core_types.h:213  kBufferTypeUpliftOutputColor = 71   // may alias the input (in-place uplift)
sl_core_types.h:215  kBufferTypeUpliftControlMask = 72   // optional, 4-channel
sl_core_types.h:253  kFeatureDLSS_NR              = 1004
```

Colour in, colour out, plus depth and motion vectors. It is an image-enhancement pass, not a denoiser, and it is why the
feature can be put over rasterized content at all.

Two backends run it, chosen by the tab's **Backend** row (`opts.nr_backend`, saved as `nr_backend`: 0 Auto, 1 NGX
direct, 2 Open; `RX_VK_DLSS_NR_BACKEND=auto|ngx|open` over it for a run), behind one front, `nr::` in
`gpu/vk/vk_dlssnr_ngx.cpp`:

- **NGX direct** (`gpu/vk/vk_dlssnr_ngx.cpp`): NVIDIA's own model, as NGX feature 18, over the NGX session DLSS super
  resolution already owns. Only in a build with NVIDIA's NGX SDK.
- **Open** (`gpu/vk/vk_opennr.cpp`): OpenDLSS-NR, an MIT-licensed Vulkan implementation of the same network, on the
  renderer's own device, from a model folder the player supplies. In every build.

Auto is NGX direct where it can run, else Open where the device was made for it, and Open on a GPU that is not NVIDIA's
(`nr::running_backend`). NVIDIA's Streamline, the other way to NVIDIA's model, is not part of this: nothing here loads
it or is built against it.

## Where it runs here

At the present, over the frame the game finished, before the menu and the FPS counter are drawn on
top (`gpu/vk/vk_replay.cpp`, `do_present`: `nr::apply` in the recording after the present's own, as
frame generation's is, so the model's GPU time does not hold the game's next frame back; with no window,
`HOS_HEADLESS`, in the present's own recording, so a headless run exercises it). It is not
an upscaler and is not part of the upscaling path: input and output are both at the game's output
size, and the Upscaler is untouched by it.

It runs **once for each of the game's frames, before frame generation**: the made frames are made
from the model's picture. Not in `present_image`, which the display thread calls for every frame it
shows: with frame generation at 4x the model would run four times a game frame, three of them over
interpolated pictures and with a history fed frames that were never rendered. It is left
out while the picture is the game's own HDR10 (the Insert menu's HDR at Native): that one is PQ codes
in RGB10A2, and the model's working copy is eight-bit SDR. HDR's Expanded is made from the model's
picture.

NVIDIA's model is handed a flat depth and no motion at all, with no jitter
(`vk_dlssnr_ngx.cpp`, `clear_scene` and the evaluation's parameters). That is deliberate, not laziness: by this point in the frame the picture is
already upscaled and already has the HUD on it, so the scene's real depth buffer does not describe
the image being handed over. Giving it the real camera would have it reproject detail that is not
where it thinks it is. The renderer *does* have real scene depth and camera motion (`vk_fsr3_inputs.cpp`),
and feeding them to NVIDIA's model is the obvious next experiment -- it would mean moving the pass before the HUD.
The open backend's temporal path already reads the scene's motion (below).

Dagor's shipping integration also runs NR on a **tonemapped, display-referred SDR image** and
inverse-tonemaps afterwards. Here the window image already is that, which is a second reason this is
the right place in the frame.

## What is asked of the device, and when

A device cannot gain extensions after it is made, and both backends want some. They are asked for **only when the
player has asked for neural rendering by the time the game starts**; otherwise `vkCreateDevice` is given exactly what it
is given without this feature, on every vendor:

| | asked for at device creation when |
|---|---|
| NGX direct (`dlssnr_ngx::device_extensions`): whatever NGX names for feature 18 | Neural rendering is saved On (or `RX_VK_DLSS_NR=1`), the GPU is NVIDIA's, the Backend is Auto or NGX direct, and `RX_VK_DLSS` is not 0 |
| Open (`opennr::selected`): `VK_NV_cooperative_matrix2`, `VK_EXT_shader_float8`, `VK_NV_cuda_kernel_launch`, `VK_NV_shader_sm_builtins`, where the GPU has them, and their feature structs | Neural rendering is saved On (or `RX_VK_DLSS_NR=1`) with the Backend at Open, or at Auto on a GPU that is not NVIDIA's; or a model folder is in place (`nr-model/manifest.json`); or `RX_VK_DLSS_NR_BACKEND=open` |

A row turned on while the game runs, on a device made without them:

- NGX direct asks NGX for feature 18's set then and compares it with what the device was made with
  (`dlssnr_ngx::device_created`, `probe`). Where the device already has them all (on the Linux driver measured below NGX
  names `VK_KHR_buffer_device_address` alone) it runs at once; otherwise the row's hint says
  "Turned on after the start: restart the game for NGX direct".
- Open cannot run, and the hint says "Open was not asked for at the start: restart the game with this on".

`tests/test_opennr_backend.py` cuts `opennr::selected()` out of the source and runs it over the cases (off on AMD, Intel
and NVIDIA: no), and checks that each of Open's three device hooks returns at once without it and that NGX is asked
nothing with the row off.

## NGX direct

`gpu/vk/vk_dlssnr_ngx.{h,cpp}` creates NVIDIA's model as NGX feature 18 (`NVSDK_NGX_Feature_Reserved18`), over the one NGX
session DLSS super resolution owns (`dlss_ngx_session`, `gpu/vk/vk_dlss.cpp`; `gpu/vk/vk_ngx.{h,cpp}` is the thin layer over
it for a feature made beside DLSS's own). `nr::apply` is the present's one call (`vk_replay.cpp` `do_present`).

**The parameter set is openNR's** ([clshortfuse/openNR](https://github.com/clshortfuse/openNR), MIT), from its native
benchmark (`benchmarks/native/d3d11/main.cpp`, `benchmarks/native/include/neural_rendering_direct.hpp`). The public NGX
SDK names the feature id and nothing else. Names and types were taken as facts; no code was copied:

| when | keys | type |
|---|---|---|
| create | `Width`/`Height`/`OutWidth`/`OutHeight`, `DLSSNR.Width`/`Height`, `DLSSNR.InputWidth`/`InputHeight`, `DLSSNR.OutputWidth`/`OutputHeight`, `DLSSNR.Output.Width`/`Output.Height` | uint |
| create | `DLSSNR.Hint.Render.Preset` (0 default, 1-7 = A-G) | uint |
| create | `PerfQualityValue` = the DLSS mode number - 1 (the Model row: 0 perf, 1 balanced, 2 quality, 5 DLAA) | int |
| create | `DLSSNRComputeScalingRatioCallback`: NGX calls it with a parameter block and it answers `DLSSNR.ScalingRatio` = 1, i.e. no upscaling | void* |
| create | `DLSSNR.ScalingRatio` 1, `DLSSNR.Scale` 1 / `DLSSNR.Upscaling` 0 | float / int |
| evaluate | `DLSSNR.Color`, `Output`, `MVec`, `Depth` (`NVSDK_NGX_Resource_VK`, images in `GENERAL`), `UI`/`UIAlpha` null | void* |
| evaluate | `DLSSNR.<Color/Output/MVec/Depth>Subrect<BaseX/BaseY/Width/Height>` | uint |
| evaluate | `Jitter.Offset.X/Y`, `DLSSNR.JitterOffsetX/Y` 0, `DLSSNR.MVecScaleX/Y` 1 | float |
| evaluate | `DLSSNR.DepthInverted` 0, `Enabled` 1, `Reset` (first frame of a feature), `UseAutoMask`, `UICorrection` 0 | int |
| evaluate | `DLSSNR.Intensity`, `LocalToneStrength`, `LocalStructureStrength`, `GlobalToneStrength`, `SkinStructureStrength` | float |
| evaluate | `DLSSNR.Style` | uint |

All of them are set with NGX's C functions (`NVSDK_NGX_Parameter_SetUI/SetI/SetF/SetVoidPointer`), not the
`NVSDK_NGX_Parameter` virtuals: NGX's Windows object is MSVC-built and llvm-mingw's vtable does not line up with it
(`vk_dlss.cpp`). Preset and Model are creation parameters, so changing either remakes the feature; the rest go with every
evaluation. A refusal is held against those exact settings (any row change tries again), and six refusals turn it off
for the run. The device is created with whatever extensions NGX names for feature 18
(`NVSDK_NGX_VULKAN_GetFeatureDeviceExtensionRequirements`, `vk_main.cpp`) when the row is on at the start (above).

Two defaults worth not getting wrong: `Hint.Render.Preset` 0 is the model's default network and 1 to 7 pin presets A to G,
so a default of 1 would silently pin preset A; and the skin structure strength defaults to 1.0 in its documented range of
0 to 1 (no source gives a negative value a meaning).

Its inputs: the picture copied into an `R8G8B8A8_UNORM` image of its own, a flat 0.5 `R32`
depth, zero `R16G16` motion, no jitter. openNR's benchmark feeds `RGBA16F`; whether 8-bit colour is accepted by feature
18 on Vulkan is not known yet.

**Availability.** It reads `DLSSNR.Available` and `DLSSNR.FeatureInitResult` from NGX's capability parameters (and
`DLSSNR.NeedsUpdatedDriver` / `MinDriverVersionMajor/Minor` by the naming every NGX feature's keys follow; a key NGX does
not answer is reported as such) and logs them. Where NGX does not answer for the feature at all, the first frame's
`CreateFeature` is the answer. When it is refused:

- **Linux**: NGX loads features as `libnvidia-ngx-<name>.so*` from the folders `vk_dlss.cpp ngx_init` gives it, and then
  the game folder itself (`dlss_ngx_runtime` lists them all), and NVIDIA ships no `libnvidia-ngx-dlssnr.so` -- SDK 310.9.16's Linux libraries are
  dlss, dlssd and dlssg only. The log and the Neural tab say exactly that, and that the Windows build under Proton is the
  way to the feature today. The day NVIDIA ships the library, putting it in the game folder's `ngx` folder should be all
  it takes. That is a prediction, not a measurement.
- **Windows** (`explain`): the GPU's generation, the `nvngx_dlssnr.dll` found in NGX's folders and whether Windows trusts
  its signature (`WinVerifyTrust`; `nx2/build.py` `ngx_link` links wintrust for it), and NGX's signature override, read
  and never written. NVIDIA's shipped `nvngx_dlssnr.dll` is **Blackwell-only** (its kernels are SM120): on an RTX 20, 30 or
  40 NGX refuses it with `0xbad00001` (`FAIL_FeatureNotSupported`). The arch gate and the kernels are both inside that one
  file, which is why community builds of it exist ([dlssnr-patcher](https://github.com/dev-camo/dlssnr-patcher), GPL-2.0;
  [openNR](https://github.com/clshortfuse/openNR)'s compatibility build, MIT), made from the player's own copy. Hookshot
  needs nothing special for them and ships nothing of NVIDIA's: it loads whatever `nvngx_dlssnr.dll` NGX finds. A patched
  file has no NVIDIA signature, and NGX loads an unsigned feature only with its signature override
  (`HKLM\SOFTWARE\NVIDIA Corporation\Global\NGXCore`, DWORD `EnableSignatureOverride` = 1). That is the player's to set;
  the log says which of these is missing and the Neural tab gets a one-line reason. None of this was run here.

### What is measured for NGX direct, and what is not

- Measured, 2026-11-09, Linux, RTX 5060 Ti (Blackwell), driver 615.71.09, NGX SDK 310.9.16, windowed on Xvfb (a
  `HOS_HEADLESS=1` run did not reach the backends then; it does now, above):
  - NGX asks for `VK_KHR_buffer_device_address` for feature 18 (`vk: dlss-nr wants ...: enabled`).
  - With Backend Auto, the run chose NGX direct; with NGX direct, the same.
  - NGX's own log (`RX_VK_DLSS_LOG=1`) shows it looking for `libnvidia-ngx-dlssnr.so` in the game folder's `ngx`, then
    `~/.local/share/hookshot/ngx`, then the game folder itself, and finding none.
  - NGX answers `DLSSNR.Available = 0`, `DLSSNR.FeatureInitResult = 0xbad00004` (`FAIL_FeatureNotFound`): the core
    knows the feature and has no library for it. The Linux message is logged once; the game went on to gameplay
    (~2,185 draws a frame, ~36 fps) for 10,000+ presents.
  - Nothing on Linux has created or evaluated feature 18, because there is nothing to create it from.
  - These runs were made before the device extensions were tied to the row being on at the start (above), with NGX asked
    at every device creation. The gated form builds and passes its source checks; it has not been run in the game.
- Not measured: anything on Windows. No run has created feature 18 through NGX on Vulkan, evaluated it, or seen a frame
  from it; whether NGX's Windows core answers `DLSSNR.Available` for a patched DLL on RTX 20-40; whether
  `PerfQualityValue` and `Hint.Render.Preset` are taken at creation as openNR's D3D11/D3D12 benchmark takes them; and
  whether openNR's D3D parameter set is the whole Vulkan set (its benchmark loads the snippet itself, not through NGX's
  core, so the core's own checks are not exercised by it).

## The open backend (OpenDLSS-NR)

The other way to run the same network: **[OpenDLSS-NR](https://github.com/maanHimself/OpenDLSS-NR)**
(MIT, Copyright 2026 maan), a Vulkan reimplementation of the DLSS-NR 310.8.0 network that its author proves bit-exact
against NVIDIA's at all 75 block boundaries. It is vendored unmodified in `third_party/opendlss-nr` (its
`PROVENANCE.md` says what and from which commit) and runs on the renderer's own device: no NVIDIA runtime, no DLL,
and so **natively on Linux**. `gpu/vk/vk_opennr.cpp` is the backend; `gpu/vk/opennr/` is the layer around
upstream's code (its Vulkan shim, the network behind a small interface); `scripts/opennr_kernels.py` makes its kernels.

Chosen by the Backend row's Open (or Auto, above), or `RX_VK_DLSS_NR_BACKEND=open` for a run, and switched on by the
Neural rendering row or `RX_VK_DLSS_NR=1`. Other switches: `RX_VK_OPENNR_MODEL=<dir>`, `RX_VK_OPENNR_ROUTE=fast|glsl|reference|khr`, `RX_VK_OPENNR_KHR_VARIANT=<name>`,
`RX_VK_OPENNR_TEMPORAL=0`, and upstream's own `DLSS5VK_*` switches, which its kernels read as they always do.

### What the player must supply, and what Hookshot does not do

**The weights.** The network reads a model directory -- `manifest.json` and its eleven stage files under `model/`, in
the layout of upstream's `docs/weights.md` -- and nothing public produces one. **Hookshot includes no weights and
provides no way to get them**: nothing here extracts, converts or downloads model data, and nothing reads any NVIDIA
binary. The player puts their own directory in `nr-model` beside the game, or names it with `RX_VK_OPENNR_MODEL`. It is
checked the way upstream's loader checks it -- every stage file's length and SHA-256 against the manifest, every
tensor inside its stage, the 71-block network and no other -- on a thread of its own, since hashing 141 MiB takes
a while; until it is done, and without one, frames go to the window untouched. Without a model the log says
`open NR: no usable model: ...` with the path it looked in, and the row's hint says the player has to supply one.
Whatever licence covers the data a player uses is theirs to respect; upstream says the same.

**The GPU.** For upstream's own routes, an NVIDIA card whose driver has `VK_KHR_cooperative_matrix`,
`VK_NV_cooperative_matrix2` (all seven of its features) and `VK_EXT_shader_float8`. With `VK_NV_cuda_kernel_launch` as
well the fast route runs (upstream's PTX kernels, counter-chained); without it the GLSL kernels run alone, which give the
same bytes. Anywhere else with `VK_KHR_cooperative_matrix`, the khr route (below). The extensions are asked for only when
this backend was asked for by the start (`opennr::selected`, above; `vk_main.cpp`, three hooks), and what is missing is
named in the log.

### The frame

Same place and contract as NGX direct: over the finished frame at display size, before the menu, into the
frame's own command buffer (`do_present`, through `nr::apply`; and, with no window, in the headless present
path, so a headless run exercises it). The window's frame is blitted into an RGBA8 copy, and two passes of ours
surround the network (`gpu/vk/shaders/opennr_pre.comp`, `opennr_post.comp`, following upstream's `docs/frame.md`):

- **in**: the sixteen lanes -- Gaussian noise hashed from the padded pixel, the frame centred
  (`f16((f16(c) - 0.5) * 0.125)`), the previous output reprojected (or the frame again without a history), the five
  conditioning scalars. The frame is already a display image, so it is its own proxy: no paper white, no shoulder.
  Outside the frame the field is a mirrored copy, as upstream pads it;
- **the network**: recorded once per frame size into a secondary command buffer and executed every frame. Nothing is
  allocated per frame; a new size rebuilds the graph with the device idle;
- **out**: `clamp(proxy + rgb / 4)`, the temporal blend by the head's own logit times the model's
  `blend_scale`, the next history truncated to half, then the style operator and the intensity blend.

**Temporal or single-frame: temporal**, with the scene's camera motion where there is a scene
(`vk_fsr3_inputs.cpp`'s frame, read with `fsr3_inputs::latest`: the one validated copy of the scene's depth and motion,
kept while the temporal path asks for it, `opennr::scene_motion_wanted`); `RX_VK_OPENNR_TEMPORAL=0` is single-frame (lanes
7-9 a copy of the frame, a fixed noise seed, no blend). The motion is the 3D scene's at its render size, so the HUD gets
the scene's motion under it -- wrong for the HUD, and left to the network's per-pixel blend logit to reject, which is what
upstream's demo leaves disocclusion to as well. A frame the scene calls a reset (a cut, a new size) has no motion and
starts the history again, and the descriptor sets are written again whenever the motion's view is another one, so a set
never names a view that has been retired. The network sees the game's own frames only: frame generation's made frames
come after it. How well any of this looks is unmeasured (below).

**The Neural tab's rows**, against what the network actually takes:

| row | what it becomes here |
| --- | --- |
| Neural rendering | on / off, live |
| Style | lane 10 (`style / 128`) **and** upstream's post-blend style operator (Natural, Cinematic), as its demo does |
| Local tone | lane 11, and the style operator's strength |
| Local structure | lane 12 (or lanes 12-14 with Auto mask) |
| Skin structure | lane 13, with Auto mask only (as in NVIDIA's runtime: without it the lane is -1) |
| Auto mask | which form the structure / skin / mask triple of lanes 12-14 takes |
| Intensity | the blend back toward the frame after the network; not a network input |
| Global tone | **no counterpart**: the network has five conditioning scalars and this is not one |
| Preset | **no counterpart**: there is one network, the model directory's; NVIDIA's presets pick among networks |
| Model (Performance ... DLAA) | **no counterpart**: the network has no quality modes and always runs at the frame's size |
| Passes | **no counterpart**: the open network runs one pass (NGX direct makes a feature a pass, below) |
| Resolution scale | the size of the picture the network is given (`vk_nr_scale.cpp`): the network is built again at that size |

### Passes, Resolution scale, and the part of the frame the model is given

Three things sit between the present and whichever backend runs, in `nr::apply` (`vk_dlssnr_ngx.cpp`). A fourth: a
frame at which the model did not run (the row off, a stretch of Native HDR, another backend, a refusal) ends its
history, and the first frame back starts it again (`history_gap`) rather than blending with a picture from before.

- **The picture's part of the frame.** The game presents a part of a larger window image (2048x1152 of 2560x1440 at
  the default output resolution). The model used to be run over all of it: a third of its time on pixels nobody sees,
  and with what lay outside the picture in what it takes the frame's tone from. It is given the crop alone now
  (`vk_nr_scale.cpp take`), and its image is shown whole. Measured with the open network on an RTX 5060 Ti: 21.1 ms
  a frame over 2560x1440 before, 13.4 ms over the 2048x1152 picture after.
- **Resolution scale** (`nr_plan.h`, 50% to 100%; the RenoDX DLSS add-on's processing scale). Under 100% the model
  is given a smaller copy of the picture, and `shaders/nr_detail.comp` adds its detail -- its picture less that copy,
  both stretched back -- to the picture at full size. Where the model changed nothing the picture comes out as it
  went in. Measured the same way: 13.4 ms at 100%, 4.2 ms at 50%; with the network's blend at 0% a capture through
  the 50% path differs from an unprocessed one by no more than two unprocessed captures differ from each other (the
  scene's own animation), and at 100% the model's change shows at both scales.
- **Passes** (`nr_plan.h`, 1 to 10; the add-on's pass count). The model goes over the frame that many times, each
  pass on the picture of the one before. Each pass is a feature of its own (NGX direct: one `CreateFeature` a pass),
  because the model keeps a history and one feature evaluated twice a frame would
  be handed its own output as the next frame. The passes read and write a pair of images in turn, and passes after
  the first are given no local tone, the convention of the multipass integrations this follows. A pass NGX cannot
  make (each holds the model's memory again) is left out and the log says how many run. **Not run here**: NVIDIA's
  model has no Linux runtime, so the passes are checked by `tests/test_nr_plan.py`
  (which image each pass reads and writes, the tone each is given, that NGX direct takes both from `nr_plan.h`)
  and by compiling the backend for Windows, not by a frame.

### What was measured, and what was not

There are no real weights on any machine this was built on, so **image quality and real-frame timing are not
measured**. What was measured is that the integration computes exactly what OpenDLSS-NR computes, with
`scripts/opennr_harness.py` (and `tests/test_opennr_harness.py`, its quick form; it says SKIP without the GPU). It
builds upstream's own `dlss5vk` tool from the vendored sources with Hookshot's clang, the same shim and portability
patch, and the kernels the renderer ships, then runs it on a **synthetic model directory** (deterministic E4M3
values in exactly the manifest layout, scaled so the activations stay alive through all 71 blocks, which the harness
checks) and a synthetic frame. Measured on an RTX 5060 Ti (Blackwell), driver 615.71.09, Linux:

- **Every route bit-exact with every other**, by upstream's own `parity` checker, on all 75 block boundaries and the
  head, at 384x256, 1280x720 and 2048x1152 (the last the game's default output size): the GLSL reference route
  (unfused, with every PTX family off and the PTX folder empty, so it provably launched none) as the references;
  upstream's `DLSS5VK_UNFUSED=1` alone; the default fast route (PTX + counter chaining); the PTX route with barriers;
  the fused GLSL route. Each also repeatable over three submissions, and the barrier and chained schedules identical.
- **Except when the activations get large.** With the synthetic decoder's weights 6-12% stronger (the harness's
  `OPENNR_SYNTH_GAIN_DECODER` at 0.85 or 0.9 instead of 0.8, decoder activations at an rms of 60-190 rather than
  under 10) the fused routes stopped agreeing with the unfused reference at 1280x720 and 2048x1152 -- from block 58
  for the fused GLSL kernels alone at 0.85, from blocks 40-45 for every fused route at 0.9 -- while they still agreed
  with each other at 384x256. Not root-caused. An f16 overflow inside a fused kernel, handled differently from the
  unfused kernels' publications, fits (the fused GLSL head carried NaNs at 0.9), but that is a guess. Whether real
  weights ever drive the network there is unknown; it is the first thing to look at if a real model's routes disagree.
- **Block 0 against upstream's CPU reference (`src/reference.cpp`) does NOT match as shipped**: every tensor-core
  kernel differs by an ulp in a quarter to a half of its values (the window normalize, which uses no tensor cores,
  matches). Upstream's reference models Ada's tensor cores -- an FP8 m16n8k32 step as two fixed-point groups of 16
  products with 13 fractional bits, an FP16 m16n8k16 step as two groups of 8 with 24. **This Blackwell card does each
  step as one group**: with the reference changed to one group of 32 FP8 products and one of 16 FP16 products (the
  harness builds both; the group width and the fraction bits are the only change), every kernel of block 0 matches
  exactly -- all 122,880 rows at 384x256 and 262,144 rows at 1280x720. The FP16 group needed at least 25 fractional
  bits; the FP8 group 19 passed 20,000 rows and failed 3 values in 8.4 million at 720p, 20 and 24 passed, so the
  harness uses 24. More bits could not be told apart on this data. Upstream's CPU reference covers block 0 only; at
  2048x1152 the CPU check was not run here (upstream's `verify` ran out of VRAM beside another game on the GPU).
- What that means: on Blackwell, OpenDLSS-NR is not bit-exact with upstream's captures, which were made on Ada; the
  same `mma.sync` instruction rounds differently on the two. Whether it is bit-exact with NVIDIA's own runtime on
  Blackwell (whose kernels run that instruction too) cannot be checked without captures from it.
- **In the game** (headless, the synthetic model, 2560x1440 frames, field 2560x1472): after the model check (a couple
  of seconds, off the display thread) it loads in about a second, then runs end to end -- 4,000-5,400 presents a run into
  gameplay, no device loss, no chained-wait timeout. The log's GPU time for the whole pass (copy, input, network,
  output) was 24-43 ms a frame on average and 20-35 ms at the least per 300 frames, over two runs; those stamps bracket the pass in a
  command buffer that overlaps the game's own work, and another game was running on the same GPU at the time, so
  they are an upper bound, not a cost. The harness measured the network alone at 2.5-5.6 ms at 384x256, 6-13 ms at
  1280x720 and 23-31 ms at 2048x1152 (minimum of three, across runs) (fast route; also with that other game running). Upstream measured 12.6 ms at
  2560x1440 on an RTX 4070 SUPER. With the synthetic weights the picture is saturated noise, as it should be; with
  Intensity at 0 the same pipeline gives back the game's frame unchanged, which checks the copy and the passes.
- Not measured: image quality, the temporal path's behaviour on real content, real-weight timing, Windows, and
  robust buffer access's cost (the renderer turns it on by default, device-wide; upstream measured ~15% for it).

VRAM: the model's raw tensors and their re-laid-out matrices, the activations of the field, and a 256 MiB host-visible
staging buffer that upstream's context keeps.

### The khr route (AMD, and anything else with KHR cooperative matrices)

`gpu/vk/opennr/khr` is the same unfused graph on kernels that need `VK_KHR_cooperative_matrix` alone: no
`VK_NV_cooperative_matrix2`, no PTX, no `VK_NV_cuda_kernel_launch`, so no counter chaining either. The kernel layer is
separate (`gpu/vk/opennr/opennr_net.h` is the seam: a device in, a features buffer and a head buffer out), so the frame
passes, the model check and the menu wiring are shared with upstream's routes. What it changes:

- **The matrix kernels are written again** (`khr/gemm_fp8.comp`, `gemm_f16.comp`, `window_attend.comp`,
  `global_attend.comp`, on `khr/khr_mma.glsl`) for subgroup-scope KHR matrices of the sizes a driver lists. They come in
  **variants** (`gpu/vk/opennr/opennr_khr.h` `kVariants`, the same table as `scripts/opennr_kernels.py` `KHR_VARIANTS`),
  each compiled into its own kernel folder, and a GPU is given the first whose shapes its driver lists
  (`vkGetPhysicalDeviceCooperativeMatrixPropertiesKHR`): E4M3 16x16x32 into f16 (NVIDIA's own MMA, the bytes of
  upstream's GLSL route), E4M3 into f32 (AMD RDNA 4, with `VK_EXT_shader_float8`), E4M3 widened to f16 into f32 (AMD RDNA
  3, which has no FP8), and an 8-lane f16 variant for llvmpipe.
- **Upstream's other kernels** (`ops`, `gemm_reduce`, the two normalizes) are compiled from build-time copies with their
  hardware E4M3 conversions spelled in integers and their half fma, inverse square root and conversions made exact
  (`KHR_SOURCE_PATCHES`, `khr/khr_e4m3.glsl`, `khr/khr_numerics.glsl`); `third_party/opendlss-nr` stays byte for byte
  upstream's.
- **Its own numerics.** A variant with f32 accumulators rounds to half once a step, as the network has it, but cannot
  promise the hardware's own order of adding the products inside an MMA: it is close to NVIDIA's bytes, not equal to
  them. By how much on real hardware is not recorded here.
- **Subgroup size** 32 (8 on llvmpipe): upstream's pipelines assume 32, and the route's are made with its variant's.

Checked by `tests/test_opennr_khr.py` (`scripts/opennr_harness.py run --khr`): every variant a device here can run, on a
device made with nothing but what that route needs, against the references of upstream's GLSL route, and block 0
against the CPU reference; on a PC with an NVIDIA GPU and llvmpipe that is the NVIDIA-shaped variants and the 8-lane
one. **It has not been run on an AMD GPU by this text's author**, in the harness or in the game: the RDNA variants are
written to what AMD's drivers list and are unmeasured.

## On AMD

What exists for neural rendering on an AMD card, as of November 2026, and what of it can be used here:

- **[DLSS-NR on AMD](https://github.com/danielblnc/DLSS-NR-on-AMD)** (NeuralHub) reimplements the model in HIP and hooks
  D3D12 games. Its licence forbids redistribution, bundling and reverse engineering, and it is D3D12 only -- Vulkan is
  "planned". Hookshot is Vulkan, so it cannot hook it, and may not ship it.
- **[OpenDLSS-NR](https://github.com/maanHimself/OpenDLSS-NR)** (MIT) is a Vulkan reimplementation of the 310.8.0
  network, bit-exact block by block. Its own kernels need `VK_NV_cooperative_matrix2` and `VK_NV_cuda_kernel_launch` (the
  fast path is PTX), so upstream is NVIDIA-only as it stands, and it reads the weights from a model directory that "nothing
  in this repository produces". It is the Open backend here (above), and its khr route is what an AMD GPU runs. The model
  directory stays the player's to supply on AMD as on NVIDIA.

## What is still unproven

Being plain about this, because the rest of this file reads confident:

- **Nobody has been found shipping or measuring DLSS-NR on Vulkan.** Dagor's NR path is written to be
  API-agnostic and does handle Vulkan resources, but every measurement found was D3D. This is the
  least-trodden configuration of the feature.
- **Nothing in this project has yet seen NVIDIA's model produce a frame**: NGX direct has not created or evaluated
  feature 18 anywhere (above, "What is measured for NGX direct").
- Whether a flat depth and zero motion are *acceptable* rather than merely *accepted*: whether the model wants
  physically meaningful depth is untested. The ReShade addon's present-time hook strongly suggests dummies are tolerated.
- The open backend with real weights: its image quality, its temporal path on real content, and the khr route on AMD
  hardware.
- The upper bound of `style`. Three values are documented (Default, Natural, Cinematic); the row
  offers exactly those three.
