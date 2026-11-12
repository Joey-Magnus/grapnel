# Temporal history validity

DLSS and FSR4 use the shared temporal chain; FSR3.1 prepares its own inputs. If camera reprojection fails, motion vectors are unavailable and the previous picture has no valid mapping to the current one. Each path must deliver a reset in that same frame rather than retaining unusable history.

Validate both input matrices and each result coefficient before converting to float. A finite double outside the float range is rejected before conversion. Preserve the existing algorithm, singularity threshold and age/size rules: valid consecutive camera motion retains history. This adds no camera-cut heuristic or interface change.

The game-free fixture compiles actual reprojection math, both preparation policies, the shared frame reset and all three consumer assignments (DLSS, FSR4, FSR3.1). It covers singular and non-finite inputs, float overflow/boundaries, recovery, frame gaps, FSR3.1 size changes and valid perspectives at16:9 and ultrawide. Engine SDKs and a GPU are not required. CPU cases do not prove in-game frequency, visual gains or GPU handling of injected invalid matrices.

## PsychoV35 with DLSS/DLAA (opt-in)

`RX_VK_PSYCHOV35_DLSS=1` lets NVIDIA DLSS/DLAA take the Native HDR PsychoV35 scene, whose gameplay network input and output are RGBA16F. It is off by default. Vanilla's packed B10G11R11 route is unchanged; this switch does not enable PsychoV35 for FSR or TAAU.

The network's perceptual colour encoding still needs the existing HDR prep square to linear light, even though the scene tone-map pass itself writes linear colour. Storage precision does not determine that encoding. The typed RGBA16F output pass writes DLSS's linear result without squaring again. Changing the tone mapper or input format resets history.

Regenerate the output variant with glslang 16.6.0:

```sh
glslang -V --target-env vulkan1.3 -DDLSS_RGBA16F=1 --vn DLSS_OUT_RGBA_COMP_SPV -o gpu/vk/shaders/dlss_out_rgba_comp_spv.h gpu/vk/shaders/dlss_out.comp
```

The existing packed output header is unchanged. `tests/test_psychov35_dlss.py` checks the opt-in format pairs, the same policy at camera/actor/reactive consumers, history resets, HDR prep selection and the compiled output's RGBA16F storage image type.
