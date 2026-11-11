// (hookshot) Workarounds for one GPU vendor's or driver's behaviour, chosen from the device's properties alone: who made it
// (vendorID), whose driver it runs (driverID, and driverInfo where a driver names its compiler) and what kind of GPU it is.
// vendor_fixes() is plain code with no Vulkan calls, so tests/test_vendor_fixes.py runs it on made-up devices: each fix on
// the GPUs it is for and on no other, and NVIDIA's driver with none of them (the GPU every row of the game was checked on).
// Each one has an RX_VK_ switch to force it on (1) or off (0) on any GPU, to test it where it is not needed.
#pragma once

#include <cstdint>
#include <cstdlib>

#include <vulkan/vulkan_core.h>

namespace mkwvk {

struct VendorFacts {
    uint32_t vendor_id = 0;
    VkDriverId driver_id{};
    VkPhysicalDeviceType device_type = VK_PHYSICAL_DEVICE_TYPE_OTHER;
    const char* driver_info = "";   // (VkPhysicalDeviceDriverProperties::driverInfo)
};

struct VendorFixes {
    // Pipeline builds into the pipeline cache kept apart from vkGetPipelineCacheData (vk_draw.cpp pipeline_cache_save). Vulkan
    // allows the two at once on a cache made without VK_PIPELINE_CACHE_CREATE_EXTERNALLY_SYNCHRONIZED_BIT, but Intel's Windows
    // driver faults in vkGetPipelineCacheData (an access violation in igvk64.dll) when a save meets pipelines being built:
    // totk-pc-recomp b358b8f1f1 (itaskaev2, MIT) and Eglantine db093d7325 (kraibse, GPL) found it, the second for MKW. Intel's
    // Windows driver, any GPU. RX_VK_PCACHE_APART
    bool pcache_apart = false;
    // Alpha to coverage set in the pipeline, not as dynamic state (VK_EXT_extended_dynamic_state3). Intel's Windows driver on its
    // integrated GPUs (UHD Graphics, Iris Xe) drew coloured noise on foliage with the dynamic state, and players saw it go with
    // it off (totk-pc-recomp 905e2e720d, Valiantsin Dzerakh, MIT: its issues 970, 992, 419). Arc cards and Mesa's ANV keep it:
    // no report there. RX_VK_DYN_A2C=0 / 1
    bool static_a2c = false;
};

/// Which of the fixes the device needs (before the RX_VK_ switches: vendor_fixes_env)
inline VendorFixes vendor_fixes(const VendorFacts& f) {
    VendorFixes x;
    const bool intel_windows = f.driver_id == VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS;
    x.pcache_apart = intel_windows;
    x.static_a2c = intel_windows && f.device_type == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    return x;
}

/// The RX_VK_ switches over them: 0 off, anything else on, unset as the device has it. get: getenv, or a test's own
template <class Get> void vendor_fixes_env(VendorFixes& x, Get get) {
    const auto over = [&](const char* name, bool& v) {
        if (const char* e = get(name); e && *e) v = std::atoi(e) != 0;
    };
    over("RX_VK_PCACHE_APART", x.pcache_apart);
    bool dyn_a2c = !x.static_a2c;
    over("RX_VK_DYN_A2C", dyn_a2c);
    x.static_a2c = !dyn_a2c;
}

} // namespace mkwvk
