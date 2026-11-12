// (hookshot) The one NGX session, for a feature made beside DLSS's own: gpu/vk/vk_ngx.h says why there is only one.
#if defined(HOOKSHOT_NGX)

#include "vk_ngx.h"
#include "vk_dlss.h"   // (dlss_ngx_session: the one NGX session)

#include <cstdlib>
#include <cstring>
#include <mutex>

#include "vk_loader.h"
#include "vk_work.h"   // (after the others: NGX records into the command buffer itself, which the recorder is told, vk_recorder.h)

namespace mkwvk::ngx {
namespace {

/// The session's own state. The NGX entry points are not resolved by name here: on Linux the
/// driver's core (libnvidia-ngx.so) exports none of the public NVSDK_NGX_* API -- it was tried, and
/// `NVSDK_NGX_VULKAN_Init_with_ProjectID` is simply not in it -- so a build that asks for DLSS links
/// the SDK's own static library, which holds those entry points and calls into the core itself.
/// nx2/build.py's `ngx_link` is the other half of that, and both are inside HOOKSHOT_NGX, so a
/// build without an SDK links and runs exactly as it did before.
struct Session {
    std::mutex mu;   // (start is asked by the present's thread and by the menu's, for its hint)
    bool started = false;
    bool start_failed = false;
};
Session s;

/// The project id the session was started with (vk_dlss.cpp's kProjectId: one project, one session), for the
/// questions asked of NGX before the device exists. A real UUID: NGX validates the shape and answers
/// NVSDK_NGX_Result_FAIL_InvalidParameter (0xbad00005) for anything that is not.
constexpr const char* kProjectId = "7b2f5d0c-6a1e-4c39-9f84-3d5e2a1b0c96";   // (vk_dlss.cpp's: one project, one session)
constexpr const char* kEngineVersion = "1.0";

/// What a discovery call is asked about, for a feature. Used before the device exists, which is why it takes no device.
NVSDK_NGX_FeatureDiscoveryInfo discovery_info(NVSDK_NGX_Feature feature) {
    NVSDK_NGX_FeatureDiscoveryInfo info{};
    info.SDKVersion = NVSDK_NGX_Version_API;
    info.FeatureID = feature;
    info.Identifier.IdentifierType = NVSDK_NGX_Application_Identifier_Type_Project_Id;
    info.Identifier.v.ProjectDesc.ProjectId = kProjectId;
    info.Identifier.v.ProjectDesc.EngineType = NVSDK_NGX_ENGINE_TYPE_CUSTOM;
    info.Identifier.v.ProjectDesc.EngineVersion = kEngineVersion;
    info.ApplicationDataPath = dlss_ngx_data_path();   // (the path the session is started with: vk_dlss.cpp ngx_init)
    return info;
}

} // namespace

bool start() {
    std::lock_guard lk(s.mu);
    if (s.started) return true;
    if (s.start_failed) return false;
    // One NGX session per device, and it is super resolution's (vk_dlss.cpp ngx_init): its project
    // id, its search path for the runtimes, its logging. Another feature is created over that
    // session rather than a second NVSDK_NGX_VULKAN_Init of its own, which NGX does not expect
    // on one device and whose Shutdown1 would take the other's features with it.
    if (!dlss_ngx_session()) {
        logf("vk: ngx: no NGX session on this device");
        s.start_failed = true;
        return false;
    }
    s.started = true;
    return true;
}

NVSDK_NGX_Parameter* allocate_params() {
    if (!start()) return nullptr;
    NVSDK_NGX_Parameter* params = nullptr;
    if (NVSDK_NGX_FAILED(NVSDK_NGX_VULKAN_AllocateParameters(&params))) {
        logf("vk: ngx gave no parameters to evaluate with");
        return nullptr;
    }
    return params;
}

void destroy_params(NVSDK_NGX_Parameter* params) {
    if (params) NVSDK_NGX_VULKAN_DestroyParameters(params);
}

// NGX records its own commands into cmd, which vk_work.h does not see: what this thread recorded through vk_work.h reaches
// cmd first (the B_DIRECT boundary, vk_recorder.h), and what NGX recorded counts as work for the barrier after it
// (vk_dlss.cpp does the same around super resolution's).
NVSDK_NGX_Result create_feature(VkCommandBuffer cmd, NVSDK_NGX_Feature feature,
                                NVSDK_NGX_Parameter* params, NVSDK_NGX_Handle** out_handle) {
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);
    const NVSDK_NGX_Result r = NVSDK_NGX_VULKAN_CreateFeature(cmd, feature, params, out_handle);
    note_work();
    return r;
}

NVSDK_NGX_Result evaluate_feature(VkCommandBuffer cmd, NVSDK_NGX_Handle* handle,
                                  NVSDK_NGX_Parameter* params) {
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);
    const NVSDK_NGX_Result r = NVSDK_NGX_VULKAN_EvaluateFeature(cmd, handle, params, nullptr);
    note_work();
    return r;
}

void release_feature(NVSDK_NGX_Handle* handle) {
    if (handle) NVSDK_NGX_VULKAN_ReleaseFeature(handle);
}

size_t device_extensions(VkInstance instance, VkPhysicalDevice gpu, NVSDK_NGX_Feature feature,
                         const char** out, size_t max) {
    if (!instance || !gpu) return 0;
    const NVSDK_NGX_FeatureDiscoveryInfo info = discovery_info(feature);
    uint32_t n = 0;
    VkExtensionProperties* props = nullptr;
    if (NVSDK_NGX_FAILED(
            NVSDK_NGX_VULKAN_GetFeatureDeviceExtensionRequirements(instance, gpu, &info, &n, &props)) ||
        !props)
        return 0;
    size_t kept = 0;
    for (uint32_t i = 0; i < n && kept < max; i++) out[kept++] = props[i].extensionName;
    return kept;
}

NVSDK_NGX_Resource_VK resource(VkImageView view, VkImage image, VkFormat format, uint32_t width,
                               uint32_t height, bool read_write) {
    VkImageSubresourceRange range{};
    range.aspectMask =
        is_depth_format(format) ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT;
    range.baseMipLevel = 0, range.levelCount = 1;
    range.baseArrayLayer = 0, range.layerCount = 1;
    return NVSDK_NGX_Create_ImageView_Resource_VK(view, image, range, format, width, height,
                                                  read_write);
}

} // namespace mkwvk::ngx

#endif // HOOKSHOT_NGX
