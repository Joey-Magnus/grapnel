/* The game's resource size table (host/restbl.c): System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs,
   a zstd-compressed RESTBL. The game sizes the buffer it loads a file into from the file's entry, so a mod file larger than
   the game's own needs a larger entry, and a file a mod adds needs one of its own. host/mods.c merges the tables the mods
   ship and raises the entries of the files they serve.

   From valentderah/totk-pc-recomp runtime/restbl.h (MIT):
   Copyright (c) 2026 Valiantsin Dzerakh
   Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
   documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
   rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
   persons to whom the Software is furnished to do so, subject to the following conditions:
   The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
   Software.
   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
   WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
   COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
   (hookshot) The estimates are Ocarina of Time's (restbl.c), the packs' members are left out. */
#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct Restbl Restbl;

/* The table of a decompressed RESTBL (copied); NULL when it is not one */
Restbl *restbl_parse(const uint8_t *data, size_t n);
void restbl_free(Restbl *t);
/* The table's key of a RomFS path: the path without a trailing .zs or .mc, into buf */
const char *restbl_key(const char *path, char *buf, size_t n);
/* 1 with *size when key has an entry */
int restbl_get(const Restbl *t, const char *key, uint32_t *size);
/* The entry of key raised to size (added when missing); 1 when the table changed */
int restbl_raise(Restbl *t, const char *key, uint32_t size);
/* Every entry of shipped larger than base's (or missing from base) raised in t; the number of entries raised */
int restbl_merge(Restbl *t, const Restbl *base, const Restbl *shipped);
/* The table as a decompressed RESTBL (malloc'd); NULL when out of memory */
uint8_t *restbl_write(const Restbl *t, size_t *n);
/* The number of entries (hashed and named) */
size_t restbl_count(const Restbl *t);

/* The entry a file of the key's type and decompressed size needs when the game has none for it; 0 for a type the
   table never lists (streamed sound) */
uint32_t restbl_estimate(const char *key, uint64_t size);
/* The entry of a file the game lists with `entry` for its own copy of `old` bytes (decompressed), now `new_size`: raised
   in proportion, never lowered */
uint32_t restbl_grow(const char *key, uint32_t entry, uint64_t old, uint64_t new_size);
