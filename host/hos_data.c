/* The game's data folder (hos_data.h): chosen once at the start, and the files a build from before kept loose in the game folder
   put where they go now.

   Which folder: --user <folder> when given; else, for a game started with nothing (as a player starts it: image.bin in the
   game folder), %LOCALAPPDATA%\Hookshot on Windows and $XDG_DATA_HOME/hookshot (~/.local/share/hookshot) on Linux; else (a
   development run given its image.bin) "user" in the current folder, as before. A builder's folder whose platform folder cannot
   be made keeps <game>/user.

   What goes where:
   - the data folder: the saves and the settings (hookshot_options.ini, hookshot_env.txt), what belongs to the player;
   - <game>/cache: the shader and pipeline caches, made for this build and this GPU, several GB, beside the game the player put
     on the drive with room for it. Its name says it can be deleted: the next start prepares the shaders again. One cache per
     game folder, so a release and a nightly side by side do not throw each other's away;
   - <game>/logs: hookshot_log.txt and the runs before it, and the other logs and traces a run writes.

   The move, each entry once and never over one already there:
   - for the platform folder only (a --user folder or a development run is the caller's to fill): <game>/user/* (the saves;
     on Linux since an earlier build already, on Windows now) into the data folder, a rename, else a copy and delete (another
     drive). When one of its entries is in the data folder already, none moves: the saves stay in <game>/user, as they were
     (hos_user_dir names it), and nothing is lost or mixed. The settings likewise; one that cannot move stays, and is then the
     default. The button prompts made from the player's controls (prompts/Common.*, External.bfotf.zs: host/prompts.c) are
     deleted: they are made again, in the data folder;
   - whenever the game folder is known: its loose caches into cache/ and its logs into logs/ (renames on the same drive), the
     Vulkan pipeline cache renamed from mkw_vk_pipelines*.bin to hookshot_vk_pipelines*.bin on the way.
   language.txt is not moved: the builder writes the build's language beside the game (nx2/make_game.py), and host/nn_applet.c
   reads the data folder's first, then that one. */
#include "hos_paths.h"   /* (first: windows.h, host/posix's on Linux) */
#include "hos_data.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define SEP 92
#define SEP_S "\\"
#else
#include <limits.h>
#define SEP '/'
#define SEP_S "/"
#endif

extern const char *hos_user_dir;   /* (nn_fs.c: the saves) */
void hos_log(const char *fmt, ...);   /* (hos.h; declared here so tests/test_data_dir.py builds this file alone) */

static char data_dir[MAX_PATH] = "user";
static int data_ready;

/* (what the move did, for the log once it is open) */
static int moved_files, tidied_files, kept_files, saves_moved, saves_kept;
static char kept_first[MAX_PATH];
static char saves_from[MAX_PATH];

/* The settings a game folder had, moved into the data folder; its logs into logs/, its caches into cache/ */
static const char *const to_data[] = {"hookshot_options.ini", "hookshot_env.txt"};
static const char *const to_logs[] = {
    "hookshot_log.txt", "hookshot_log.1.txt", "hookshot_log.2.txt", "hookshot_log.3.txt", "hookshot_log.4.txt",
    "hookshot_startup.log", "hookshot_frames.csv",
};
static const char *const to_cache[] = {
    "hookshot_programs.bin", "hookshot_programs.idx", "hookshot_pipelines.bin", "hookshot_computes.bin",
    "hookshot_pipeline_states.bin", "hookshot_pipeline_states_v1.bin", "hookshot_prepared.bin", "hookshot_prepare_skipped",
};
/* The Vulkan pipeline cache, mkw_vk_pipelines.bin and its play files mkw_vk_pipelines_play_<n>.bin (mkw-recomp's names), renamed
   hookshot_vk_pipelines*.bin as they move into cache/ (gpu/vk/vk_draw.cpp). Those an earlier build of the change put in cache/
   with the old name are renamed there too */
static const char old_pcache[] = "mkw_vk_pipelines", new_pcache[] = "hookshot_vk_pipelines";
/* Made from the player's choices and made again when missing: deleted from the game folder */
static const char *const made_again[] = {
    "prompts" SEP_S "Common.bntx.zs", "prompts" SEP_S "Common.blarc.zs", "prompts" SEP_S "Common.key",
    "prompts" SEP_S "Common.blarc.key", "prompts" SEP_S "External.bfotf.zs",
};

static int exists(const char *p) { return GetFileAttributesA(p) != INVALID_FILE_ATTRIBUTES; }
static int is_dir(const char *p) {
    const DWORD a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
static int copy_tree(const char *from, const char *to) {
    if (!is_dir(from)) {
        FILE *in = fopen(from, "rb"), *out = in ? fopen(to, "wb") : NULL;
        int ok = in && out;
        static char buf[1 << 16];
        for (size_t n; ok && (n = fread(buf, 1, sizeof buf, in)) > 0;) ok = fwrite(buf, 1, n, out) == n;
        ok = ok && in && !ferror(in);
        if (in) fclose(in);
        if (out && fclose(out)) ok = 0;
        return ok;
    }
    if (!CreateDirectoryA(to, NULL) && !is_dir(to)) return 0;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", from);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    int ok = 1;
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            char a[MAX_PATH], b[MAX_PATH];
            snprintf(a, sizeof a, "%s" SEP_S "%s", from, fd.cFileName);
            snprintf(b, sizeof b, "%s" SEP_S "%s", to, fd.cFileName);
            ok = copy_tree(a, b);
        } while (ok && FindNextFileA(h, &fd));
        FindClose(h);
    }
    return ok;
}
static void delete_tree(const char *p) {
    if (!is_dir(p)) {
        DeleteFileA(p);
        return;
    }
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", p);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
            char a[MAX_PATH];
            snprintf(a, sizeof a, "%s" SEP_S "%s", p, fd.cFileName);
            delete_tree(a);
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    RemoveDirectoryA(p);
}
/* from to to, which is not there yet: a rename, else a copy and delete. 1 moved, 0 left where it was */
static int move_entry(const char *from, const char *to) {
    if (MoveFileExA(from, to, 0)) return 1;
    if (copy_tree(from, to)) {
        delete_tree(from);
        return 1;
    }
    delete_tree(to);   /* (a copy cut short) */
    return 0;
}

/* <game>/user's entries into the data folder: the folder the saves are in after it */
static const char *move_saves(const char *beside) {
    if (!is_dir(beside)) return data_dir;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s" SEP_S "*", beside);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return data_dir;
    /* (first, whether any entry is in the data folder already: then none moves, and the saves stay whole where they were) */
    do {
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
        char to[MAX_PATH];
        snprintf(to, sizeof to, "%s" SEP_S "%s", data_dir, fd.cFileName);
        if (exists(to)) saves_kept++;
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    snprintf(saves_from, sizeof saves_from, "%s", beside);
    if (saves_kept) return beside;
    h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return data_dir;
    do {
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
        char from[MAX_PATH], to[MAX_PATH];
        snprintf(from, sizeof from, "%s" SEP_S "%s", beside, fd.cFileName);
        snprintf(to, sizeof to, "%s" SEP_S "%s", data_dir, fd.cFileName);
        if (move_entry(from, to)) saves_moved++;
        else saves_kept++;   /* (a copy that failed, the disk full: what moved is in the data folder, the rest here) */
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    if (saves_kept) return beside;   /* (the saves stay where they were: the game reads them there) */
    RemoveDirectoryA(beside);
    return data_dir;
}

/* game's file name into the folder dir (with its separator): 1 when it moved */
static int move_as(const char *game, const char *name, const char *dir, const char *as) {
    char from[MAX_PATH], to[MAX_PATH];
    if (snprintf(from, sizeof from, "%s%s", game, name) >= (int)sizeof from || !exists(from) || is_dir(from)) return 0;
    if (snprintf(to, sizeof to, "%s%s", dir, as) >= (int)sizeof to) return 0;
    if (!exists(to) && move_entry(from, to)) return 1;
    if (!kept_files++) snprintf(kept_first, sizeof kept_first, "%s", from);
    return 0;
}
static int move_file(const char *game, const char *name, const char *dir) { return move_as(game, name, dir, name); }

/* folder's mkw_vk_pipelines*.bin into cache as hookshot_vk_pipelines*.bin (folder and cache: with their separators) */
static int move_pcache(const char *folder, const char *cache) {
    int moved = 0;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s%s*.bin", folder, old_pcache);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        char as[MAX_PATH];
        if (strncmp(fd.cFileName, old_pcache, sizeof old_pcache - 1)) continue;
        snprintf(as, sizeof as, "%s%s", new_pcache, fd.cFileName + sizeof old_pcache - 1);
        moved += move_as(folder, fd.cFileName, cache, as);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    return moved;
}

/* the game folder's loose caches and logs of a build from before into its cache/ and logs/ (game: the folder, with its
   separator) */
static void tidy_game(const char *game) {
    char cache[MAX_PATH], logs[MAX_PATH];
    snprintf(cache, sizeof cache, "%scache" SEP_S, game);
    snprintf(logs, sizeof logs, "%slogs" SEP_S, game);
    for (size_t i = 0; i < sizeof to_logs / sizeof *to_logs; i++) tidied_files += move_file(game, to_logs[i], logs);
    for (size_t i = 0; i < sizeof to_cache / sizeof *to_cache; i++) tidied_files += move_file(game, to_cache[i], cache);
    tidied_files += move_pcache(game, cache) + move_pcache(cache, cache);
    char lock[MAX_PATH];   /* (the program cache's lock, made again beside it in cache/) */
    snprintf(lock, sizeof lock, "%shookshot_programs.bin.lock", game);
    if (exists(lock)) DeleteFileA(lock);
}

/* the game folder's saves and settings of a build from before, into the data folder (game: the folder, with its separator) */
static void migrate(const char *game) {
    char path[MAX_PATH];
    snprintf(path, sizeof path, "%suser", game);
    const char *saves = move_saves(path);
    if (saves != data_dir) {
        static char kept[MAX_PATH];
        snprintf(kept, sizeof kept, "%s", saves);
        hos_user_dir = kept;
    }
    char data[MAX_PATH];
    snprintf(data, sizeof data, "%s" SEP_S, data_dir);
    for (size_t i = 0; i < sizeof to_data / sizeof *to_data; i++) moved_files += move_file(game, to_data[i], data);
    for (size_t i = 0; i < sizeof made_again / sizeof *made_again; i++) {
        snprintf(path, sizeof path, "%s%s", game, made_again[i]);
        if (exists(path)) DeleteFileA(path);
    }
    if (moved_files || saves_moved) {   /* (a note where they were, for a player who looks there) */
        snprintf(path, sizeof path, "%sfiles-moved.txt", game);
        FILE *f = fopen(path, "w");
        if (f) {
            fprintf(f, "Hookshot's saves and settings are now in\n%s\n\nThey moved there from this folder. The shader caches are in "
                       "this folder's cache folder (it can be deleted: the next start prepares the shaders again), the logs in its "
                       "logs folder.\n", data_dir);
            fclose(f);
        }
    }
}

/* the platform's data folder into data_dir: 0 when there is none */
static int platform_dir(void) {
#ifdef _WIN32
    wchar_t w[MAX_PATH];
    const DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", w, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    char base[MAX_PATH * 3];
    if (!WideCharToMultiByte(CP_UTF8, 0, w, -1, base, (int)sizeof base, NULL, NULL)) return 0;
    if (snprintf(data_dir, sizeof data_dir, "%s\\Hookshot", base) >= (int)sizeof data_dir) return 0;
#else
    const char *xdg = getenv("XDG_DATA_HOME"), *home = getenv("HOME");
    char base[MAX_PATH];
    if (xdg && xdg[0] == '/') snprintf(base, sizeof base, "%s", xdg);
    else if (home && home[0] == '/') {
        snprintf(base, sizeof base, "%s/.local", home);
        CreateDirectoryA(base, NULL);
        snprintf(base, sizeof base, "%s/.local/share", home);
    } else return 0;
    CreateDirectoryA(base, NULL);
    if (snprintf(data_dir, sizeof data_dir, "%s/hookshot", base) >= (int)sizeof data_dir) return 0;
#endif
    CreateDirectoryA(data_dir, NULL);
    return is_dir(data_dir);
}

/* data_dir as an absolute path (a relative --user or "user" would move with the current folder) */
static void make_absolute(void) {
    char full[MAX_PATH];
#ifdef _WIN32
    if (_fullpath(full, data_dir, sizeof full)) snprintf(data_dir, sizeof data_dir, "%s", full);
#else
    char real[PATH_MAX];
    if (realpath(data_dir, real) && strlen(real) < sizeof full) snprintf(data_dir, sizeof data_dir, "%s", real);
#endif
    size_t n = strlen(data_dir);
    while (n > 1 && (data_dir[n - 1] == '/' || data_dir[n - 1] == '\\') && !(n == 3 && data_dir[1] == ':')) data_dir[--n] = 0;
}

int hos_game_file(char *out, size_t cap, const char *name) {
    char path[MAX_PATH];
    const DWORD n = hos_game_path_a(path, MAX_PATH);
    if (!n || n >= MAX_PATH || !cap) return 0;
    char *slash = strrchr(path, SEP);
#ifdef _WIN32
    if (!slash) slash = strrchr(path, '/');
#endif
    if (!slash) return 0;
    slash[1] = 0;
    const int len = snprintf(out, cap, "%s%s", path, name);
#ifdef _WIN32
    for (char *p = out + strlen(path); *p; p++)
        if (*p == '/') *p = SEP;
#endif
    return len >= 0 && len < (int)cap;
}

void hos_data_init(int argc, char **argv) {
    if (data_ready) return;
    data_ready = 1;
    const char *user = NULL;
    int image = 0;
    for (int i = 1; i < argc; i++) {   /* (hos_main.c's arguments) */
        if (!strcmp(argv[i], "--romfs") && i + 1 < argc) i++;
        else if (!strcmp(argv[i], "--user") && i + 1 < argc) user = argv[++i];
        else if (!strcmp(argv[i], "--trace") || !strcmp(argv[i], "--prepare-shaders")) continue;
        else image = 1;
    }
    char game_image[MAX_PATH];
    const int builder_folder = !image && hos_game_file(game_image, sizeof game_image, "image.bin") && exists(game_image);
    int move = 0;
    if (user && *user) snprintf(data_dir, sizeof data_dir, "%s", user);
    else if (builder_folder && platform_dir()) move = 1;
    else if (builder_folder) hos_game_file(data_dir, sizeof data_dir, "user");   /* (no platform folder: the game folder's, as before) */
    else snprintf(data_dir, sizeof data_dir, "user");
    CreateDirectoryA(data_dir, NULL);
    make_absolute();
    hos_user_dir = data_dir;
    char game[MAX_PATH], sub[MAX_PATH];
    if (hos_game_file(game, sizeof game, "")) {
        if (hos_game_file(sub, sizeof sub, "cache")) CreateDirectoryA(sub, NULL);
        if (hos_game_file(sub, sizeof sub, "logs")) CreateDirectoryA(sub, NULL);
        tidy_game(game);
        if (move) migrate(game);
    }
}

const char *hos_data_dir(void) { return data_dir; }

int hos_data_path(char *out, size_t cap, const char *name) {
    if (!cap) return 0;
    const int n = snprintf(out, cap, "%s" SEP_S "%s", data_dir, name);
#ifdef _WIN32
    for (char *p = out + strlen(data_dir); *p; p++)
        if (*p == '/') *p = SEP;
#endif
    return n >= 0 && n < (int)cap;
}

#ifdef _WIN32
const wchar_t *hos_data_dir_w(void) {
    static wchar_t w[MAX_PATH];
    if (!MultiByteToWideChar(CP_UTF8, 0, data_dir, -1, w, MAX_PATH)) w[0] = 0;
    return w;
}
#endif

void hos_data_log_migration(void) {
    hos_log("data: %s", data_dir);
    if (saves_moved || saves_kept) {
        if (saves_kept) hos_log("data: %d of %s's entries could not move: the saves stay in %s", saves_kept, saves_from, saves_from);
        else hos_log("data: the saves moved from %s", saves_from);
    }
    if (moved_files) hos_log("data: %d settings files moved from the game folder", moved_files);
    if (tidied_files) hos_log("data: %d logs and shader caches moved into the game folder's logs and cache folders", tidied_files);
    if (kept_files) hos_log("data: %d files stayed in the game folder (one there already, or no room): %s, ...", kept_files, kept_first);
}
