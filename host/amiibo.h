/* (hookshot) Amiibo dumps on an emulated NFC reader (amiibo.c), read by the game through nn::nfp (nn_nfp.c) */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define AMIIBO_DUMP_SIZE 540   /* an NTAG215's pages */
#define AMIIBO_DUMP_MIN 532    /* (a dump without the password pages) */
#define AMIIBO_DUMP_MAX 572    /* (one with the tag's signature after them) */
#define AMIIBO_AREA_SIZE 0xD8  /* a game's application area */
#define AMIIBO_MAX_FILES 64

/* nn::nfp::DeviceState */
enum { AMIIBO_INITIALIZED = 0, AMIIBO_SEARCHING = 1, AMIIBO_ACTIVE = 2, AMIIBO_DEACTIVE = 3, AMIIBO_MOUNTED = 4 };
/* nn::nfp results (module 115) */
#define AMIIBO_RESULT(desc) (115u | (unsigned)(desc) << 9)
#define AMIIBO_RESULT_DEVICE_NOT_FOUND AMIIBO_RESULT(64)
#define AMIIBO_RESULT_WRONG_AREA_SIZE AMIIBO_RESULT(68)
#define AMIIBO_RESULT_WRONG_STATE AMIIBO_RESULT(73)
#define AMIIBO_RESULT_TAG_REMOVED AMIIBO_RESULT(97)
#define AMIIBO_RESULT_NEED_CREATE AMIIBO_RESULT(128)   /* (ApplicationAreaIsNotInitialized) */
#define AMIIBO_RESULT_WRONG_AREA_ID AMIIBO_RESULT(152)
#define AMIIBO_RESULT_AREA_EXISTS AMIIBO_RESULT(168)

int amiibo_check(const uint8_t *d, size_t n);   /* 1: an amiibo's NTAG215 dump */
int amiibo_load(const char *path, const char *name);
void amiibo_place(void);
void amiibo_take_off(void);
void amiibo_detect(int on);
int amiibo_state(void);
int amiibo_mount(void);
void amiibo_unmount(void);
int amiibo_mounted(void);
int amiibo_tag_seen(void);
void amiibo_tag_info(uint8_t *out);
void amiibo_model_info(uint8_t *out);
void amiibo_common_info(uint8_t *out);
void amiibo_register_info(uint8_t *out);
int amiibo_area_open(uint32_t access_id);
int amiibo_area_get(void *buf, uint32_t cap, uint32_t *size);
int amiibo_area_set(const void *data, uint32_t n);
int amiibo_area_create(uint32_t access_id, const void *data, uint32_t n, int recreate);
int amiibo_flush(void);
int amiibo_rescan(void);
const char *amiibo_file(int i);
int amiibo_choose(int i);
int amiibo_menu_state(void);
