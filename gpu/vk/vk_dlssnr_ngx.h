// (hookshot) DLSS 5 neural rendering through NGX directly, and `nr::`, the front the present calls: which backend runs.
//
// What it is, because the name invites the wrong guess: DLSS 5 neural rendering (DLSS-NR) is *not* ray reconstruction.
// Ray reconstruction (NGX's DLSSD) denoises a ray-traced image and needs a G-buffer, which a recompilation of a rasterized
// game does not have. DLSS-NR is an "uplift" pass: colour in, colour out, with depth and motion beside them. That is why it
// can sit at the end of the frame, over the picture the renderer is about to show (docs/neural-rendering.md).
//
// NGX knows the feature as NVSDK_NGX_Feature_Reserved18. The public SDK names nothing else about it -- no capability keys,
// no parameters -- so the parameter set below is the one openNR (https://github.com/clshortfuse/openNR, MIT, Copyright
// 2026 Carlos Lopez) drives it with in its native benchmark: the names are facts about the feature, written out here; none
// of openNR's code is copied. Nothing of NVIDIA's is in this repository, and nothing here reads or patches NVIDIA's files.
//
// It shares the one NGX session DLSS super resolution owns (dlss_ngx_session, gpu/vk/vk_dlss.h; gpu/vk/vk_ngx.h says why
// there is one). It is fed the finished frame, a flat depth and no motion: at this point in the frame the picture is
// already upscaled and has the HUD on it, so the scene's real depth buffer does not describe it.
//
// On Linux the NGX core loads features as libnvidia-ngx-<name>.so* and already answers for DLSS-NR's capability keys. What
// is missing, as of SDK 310.9.16 and driver 615, is NVIDIA's libnvidia-ngx-dlssnr.so itself. Until it ships this path
// says so plainly; the day it does, it should simply run.
//
// `nr::` below is which backend runs: the Insert menu's Neural tab "Backend" row (opts.nr_backend: Auto, NGX direct,
// Open), or RX_VK_DLSS_NR_BACKEND=auto|ngx|open over it. The other backend is the open network, gpu/vk/vk_opennr.h.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "vk_internal.h"

namespace mkwvk::dlssnr_ngx {

/// Whether this build has an NGX SDK (HOOKSHOT_NGX) to compile this path against.
[[nodiscard]] bool built_with_sdk();

/// Whether NGX reports the feature on this GPU and driver. Asked of NGX once, after the device exists; the answer and why
/// are logged once.
[[nodiscard]] bool capable();

/// Why it cannot run, in a line the menu can show: "" while it can, or before it has been asked.
[[nodiscard]] const char* why();

/// The device extensions NGX says feature 18 needs here, asked before the device exists (a device made without a
/// feature's extensions is where CreateFeature answers FAIL_PlatformError). Asked only when the player has neural
/// rendering on at the start, on an NVIDIA GPU, with a Backend that can be this one (Auto or NGX direct): with the row
/// off the device is made exactly as it is without this file. How many names were written, at most `max`; zero
/// otherwise, in a build without NGX, or where NGX does not answer.
size_t device_extensions(VkInstance instance, VkPhysicalDevice gpu, const char** out, size_t max);
/// The device exists, made with these extensions. A row turned on later is checked against them: NGX is asked for
/// feature 18's set then, and only one the device lacks asks the player for a restart (why()).
void device_created(const std::vector<const char*>& enabled);

/// One uplift of `src` (GENERAL, sw x sh), recorded into `cmd`, and the image to present in its place (GENERAL, the same
/// size, this path's own) with its view in `out_view`; VK_NULL_HANDLE when the model did not run, and the caller presents
/// `src` as it would have. `src` is only read: the window texture is the game's, and a frame the game reads back would
/// come back changed.
[[nodiscard]] VkImage apply(VkCommandBuffer cmd, VkImage src, uint32_t sw, uint32_t sh, VkImageView* out_view);
/// The model did not run at the frame before (nr::apply): the next evaluation is told to start its history again
void history_gap();

/// Releases the feature and its images. Before the device goes.
void shutdown();

} // namespace mkwvk::dlssnr_ngx

namespace mkwvk::nr {

/// The Backend row's values, as saved (nr_backend). OPEN: OpenDLSS-NR, gpu/vk/vk_opennr.h
enum Backend : int { AUTO = 0, NGX = 1, OPEN = 2 };

/// The backend asked for (the row, or RX_VK_DLSS_NR_BACKEND over it), and the one that runs for it: NGX or OPEN.
/// Auto is NGX direct where it can run, the open network where the device was made for it or the GPU is not NVIDIA's.
[[nodiscard]] int asked_backend();
[[nodiscard]] int running_backend();

/// Whether neural rendering is switched on (the Neural tab's row, or RX_VK_DLSS_NR over it): read live, each frame.
[[nodiscard]] bool wanted();

/// The present's one call: the running backend over the picture, which is the crop's part of `src` (GENERAL, sw x sh;
/// vk_present_rect.h present_source_rect), at the Resolution scale row's size (vk_nr_scale.h). The image to show in the
/// picture's place (GENERAL, the whole of it the picture), its view in `out_view` and its size in `out_w` x `out_h`;
/// VK_NULL_HANDLE when the model did not run, and the caller presents `src` as it would have.
[[nodiscard]] VkImage apply(VkCommandBuffer cmd, VkImage src, uint32_t sw, uint32_t sh, const int crop[4],
                            VkImageView* out_view, uint32_t* out_w, uint32_t* out_h);

/// Why the running backend cannot run, for the menu: "" while it can or is not known yet.
[[nodiscard]] const char* why();

} // namespace mkwvk::nr
