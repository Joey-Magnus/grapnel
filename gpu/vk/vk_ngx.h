// (hookshot) The one NGX session, for a feature made beside DLSS's own.
//
// NGX initializes once per process and hands back one capability-parameter block for every feature
// it knows, so backends that each loaded and initialized it would each be a bug: a second
// NVSDK_NGX_VULKAN_Init over a live session, a second set of parameters, and a shutdown by whichever
// one finished first. The session is gpu/vk/vk_dlss.cpp's (super resolution and frame generation are
// made there); DLSS 5 neural rendering through NGX (gpu/vk/vk_dlssnr_ngx.h) comes through here and
// owns nothing but its own feature handles.
//
// Nothing of NVIDIA's is in this repository and nothing of NVIDIA's is needed to build it: this
// whole file is inside the build-time gate `HOOKSHOT_NGX`, which names the builder's own copy of
// an NGX SDK (scripts/ngx_sdk.py). A tree without it does not compile this file at all, and the
// backend's public header stays free of NGX types so that the renderer can call it either way.
#pragma once

#if defined(HOOKSHOT_NGX)

#include <cstdint>

#include "vk_internal.h"

#include <nvsdk_ngx.h>
#include <nvsdk_ngx_helpers.h>
#include <nvsdk_ngx_helpers_vk.h>
#include <nvsdk_ngx_vk.h>

namespace mkwvk::ngx {

/// Whether the session is up (vk_dlss.cpp's, started if it was not yet). False where NGX refused,
/// which it does on a GPU or driver it does not serve.
[[nodiscard]] bool start();

/// A parameter block of this backend's own, to create and evaluate a feature with. Null where NGX
/// would not give one. The caller keeps it for the life of its feature and frees it with
/// `destroy_params`.
[[nodiscard]] NVSDK_NGX_Parameter* allocate_params();
void destroy_params(NVSDK_NGX_Parameter* params);

/// Creates / evaluates / releases one feature. Thin passes to NGX, here only so that the resolved
/// entry points stay in one place.
[[nodiscard]] NVSDK_NGX_Result create_feature(VkCommandBuffer cmd, NVSDK_NGX_Feature feature,
                                              NVSDK_NGX_Parameter* params,
                                              NVSDK_NGX_Handle** out_handle);
[[nodiscard]] NVSDK_NGX_Result evaluate_feature(VkCommandBuffer cmd, NVSDK_NGX_Handle* handle,
                                                NVSDK_NGX_Parameter* params);
void release_feature(NVSDK_NGX_Handle* handle);

/// The device extensions a feature needs here, asked of NGX (it can be asked before the device
/// exists). How many names were written, at most `max`; the names are NGX's own storage and last as
/// long as the process. Zero means NGX does not answer, which leaves the device as it would have been.
size_t device_extensions(VkInstance instance, VkPhysicalDevice gpu, NVSDK_NGX_Feature feature,
                         const char** out, size_t max);

/// One image as NGX takes it: a view *and* its image, range, format and the extent it is read at.
/// NGX is handed resources, not views, which is the whole reason the renderer records what each
/// binding is a view of.
[[nodiscard]] NVSDK_NGX_Resource_VK resource(VkImageView view, VkImage image, VkFormat format,
                                             uint32_t width, uint32_t height, bool read_write);

} // namespace mkwvk::ngx

#endif // HOOKSHOT_NGX
