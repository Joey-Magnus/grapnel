/* (hookshot) nn::nfp: the console's amiibo reader, for the figures the Insert menu puts on it (amiibo.c). One reader, always
   there, as the right Joy-Con's or a Pro Controller's: the game lists it, searches, and finds a figure while one is on it.
   Every call the game imports is here (they were generated stubs that answered 0 and wrote nothing). The amiibo settings
   applets (StartNicknameAndOwnerSettings, StartGameDataEraser, StartRestorer) stay stubs: there is no applet to show.

   After totk-pc-recomp's runtime/nfp.c (valentderah/totk-pc-recomp, MIT, by leonelalej; the notice is in amiibo.c), which serves the same
   calls as the nfp:user service's IPC commands; here they are the SDK's functions. */
#include "hos.h"
#include "amiibo.h"
#include <string.h>

void hos_system_event_init(uint64_t key, int autoclear);   /* nn_os_sync.c */

static int initialized;

/* the guest buffer of n bytes at a, NULL when it is not in the guest window */
static uint8_t *out_buf(uint64_t a, uint64_t n) { return a ? (uint8_t *)hos_guest_range(a, n) : NULL; }

/* nn::nfp::Initialize() */
HLE(_ZN2nn3nfp10InitializeEv) {
    if (!initialized) hos_log("nfp: initialized (an amiibo reader, the Insert menu's Amiibo row puts figures on it)");
    initialized = 1;
    RET(0);
}
/* nn::nfp::Finalize() */
HLE(_ZN2nn3nfp8FinalizeEv) {
    amiibo_detect(0);
    initialized = 0;
    RET(0);
}
/* nn::nfp::AttachAvailabilityChangeEvent(nn::os::SystemEventType*): the reader never comes or goes, so it is never signaled */
HLE(_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE) {
    if (ARG(0)) hos_system_event_init(ARG(0), 0);
    RET(0);
}
/* nn::nfp::ListDevices(DeviceHandle* out, int* count, int max): one reader */
HLE(_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii) {
    uint8_t *handles = out_buf(ARG(0), 8);
    uint8_t *count = out_buf(ARG(1), 4);
    const int n = (int)ARG(2) > 0 && handles ? 1 : 0;
    if (handles && n) {
        static const uint8_t reader[8] = {1, 0, 0, 0, 0, 0, 0, 0};
        memcpy(handles, reader, 8);
        HOS_WRITTEN(handles, 8);
    }
    if (count) {
        memcpy(count, &n, 4);
        HOS_WRITTEN(count, 4);
    }
    RET(n ? 0 : AMIIBO_RESULT_DEVICE_NOT_FOUND);
}
/* nn::nfp::StartDetection(DeviceHandle const&) / StopDetection */
HLE(_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE) {
    amiibo_detect(1);
    RET(0);
}
HLE(_ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE) {
    amiibo_detect(0);
    RET(0);
}
/* nn::nfp::GetDeviceState(DeviceHandle const&) -> DeviceState */
HLE(_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE) { RET(amiibo_state()); }
/* nn::nfp::GetNpadId(unsigned int*, DeviceHandle const&): the first player's controller */
HLE(_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE) {
    uint8_t *p = out_buf(ARG(0), 4);
    if (p) memset(p, 0, 4), HOS_WRITTEN(p, 4);
    RET(0);
}
/* nn::nfp::Mount(DeviceHandle const&, ModelType, MountTarget) */
HLE(_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE) {
    RET(amiibo_mount() ? 0 : amiibo_tag_seen() ? AMIIBO_RESULT_WRONG_STATE : AMIIBO_RESULT_TAG_REMOVED);
}
/* nn::nfp::GetTagInfo(TagInfo*, DeviceHandle const&): the figure while it is on the reader and the game searches */
HLE(_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE) {
    uint8_t *p = out_buf(ARG(0), 0x58);
    if (!amiibo_tag_seen() && !amiibo_mounted()) { RET(AMIIBO_RESULT_TAG_REMOVED); return; }
    if (p) amiibo_tag_info(p), HOS_WRITTEN(p, 0x58);
    RET(0);
}
/* nn::nfp::GetModelInfo(ModelInfo*, DeviceHandle const&), GetCommonInfo(CommonInfo*, ...), GetRegisterInfo(RegisterInfo*, ...):
   mounted only */
HLE(_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE) {
    uint8_t *p = out_buf(ARG(0), 0x40);
    if (!amiibo_mounted()) { RET(AMIIBO_RESULT_WRONG_STATE); return; }
    if (p) amiibo_model_info(p), HOS_WRITTEN(p, 0x40);
    RET(0);
}
HLE(_ZN2nn3nfp13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE) {
    uint8_t *p = out_buf(ARG(0), 0x40);
    if (!amiibo_mounted()) { RET(AMIIBO_RESULT_WRONG_STATE); return; }
    if (p) amiibo_common_info(p), HOS_WRITTEN(p, 0x40);
    RET(0);
}
HLE(_ZN2nn3nfp15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE) {
    uint8_t *p = out_buf(ARG(0), 0x100);
    if (!amiibo_mounted()) { RET(AMIIBO_RESULT_WRONG_STATE); return; }
    if (p) amiibo_register_info(p), HOS_WRITTEN(p, 0x100);
    RET(0);
}
/* nn::nfp::OpenApplicationArea(DeviceHandle const&, unsigned int access_id) */
HLE(_ZN2nn3nfp19OpenApplicationAreaERKNS0_12DeviceHandleEj) { RET(amiibo_area_open((uint32_t)ARG(1))); }
/* nn::nfp::GetApplicationArea(void* buffer, unsigned long* size, DeviceHandle const&, unsigned long buffer_size) */
HLE(_ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm) {
    const uint64_t cap = ARG(3) < AMIIBO_AREA_SIZE ? ARG(3) : AMIIBO_AREA_SIZE;
    uint8_t *p = out_buf(ARG(0), cap ? cap : 1), *size = out_buf(ARG(1), 8);
    uint32_t got = 0;
    const int r = p ? amiibo_area_get(p, (uint32_t)cap, &got) : AMIIBO_RESULT_WRONG_AREA_SIZE;
    if (!r) {
        HOS_WRITTEN(p, got);
        if (size) {
            const uint64_t n = got;
            memcpy(size, &n, 8);
            HOS_WRITTEN(size, 8);
        }
    }
    RET(r);
}
/* nn::nfp::SetApplicationArea(DeviceHandle const&, void const*, unsigned long) */
HLE(_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm) {
    const uint8_t *p = ARG(2) && ARG(2) <= AMIIBO_AREA_SIZE ? out_buf(ARG(1), ARG(2)) : NULL;
    RET(p ? amiibo_area_set(p, (uint32_t)ARG(2)) : AMIIBO_RESULT_WRONG_AREA_SIZE);
}
/* nn::nfp::CreateApplicationArea / RecreateApplicationArea(DeviceHandle const&, ApplicationAreaCreateInfo const&): the info is
   { u32 access id; void* initial data; u32 its size; ... } */
static int create(Ctx *c, int recreate) {
    const uint8_t *info = out_buf(ARG(1), 24);
    if (!info) return AMIIBO_RESULT_WRONG_AREA_SIZE;
    uint32_t id, n;
    uint64_t data;
    memcpy(&id, info, 4), memcpy(&data, info + 8, 8), memcpy(&n, info + 16, 4);
    if (n > AMIIBO_AREA_SIZE) return AMIIBO_RESULT_WRONG_AREA_SIZE;
    const uint8_t *init = n ? out_buf(data, n) : NULL;
    if (n && !init) return AMIIBO_RESULT_WRONG_AREA_SIZE;
    return amiibo_area_create(id, init, n, recreate);
}
HLE(_ZN2nn3nfp21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) { RET(create(c, 0)); }
HLE(_ZN2nn3nfp23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) { RET(create(c, 1)); }
/* nn::nfp::Flush(DeviceHandle const&): the application area kept (amiibo/appdata, never the dump) */
HLE(_ZN2nn3nfp5FlushERKNS0_12DeviceHandleE) { RET(amiibo_flush()); }

/* ---- the Insert menu's Amiibo row (host/rx_backend.c gives these to the Vulkan back end, MkwVkHost.amiibo_*) */
int hos_amiibo_count(void) { return amiibo_rescan(); }
const char *hos_amiibo_name(int i) { return amiibo_file(i); }
int hos_amiibo_choose(int i) { return amiibo_choose(i); }
int hos_amiibo_state(void) { return amiibo_menu_state(); }
