/* The game's data folder (host/hos_data.c): where everything that belongs to this PC and its player is kept, apart from the
   game folder the builder makes. Saves, settings (hookshot_options.ini, hookshot_env.txt, language.txt), the log, and in
   shaders/ the shader and pipeline caches. %LOCALAPPDATA%\Hookshot on Windows, $XDG_DATA_HOME/hookshot (~/.local/share/hookshot)
   on Linux; --user <folder> names another; a run given its image.bin (a development run) uses "user" in the current folder.
   Paths are UTF-8. */
#pragma once
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Once, first thing in main (before hookshot_env.txt is read and the log opened): the folder chosen from the arguments and
   made, the files an older build left in the game folder moved into it, hos_user_dir set */
void hos_data_init(int argc, char **argv);
/* The data folder, absolute, no separator at its end ("user" before hos_data_init) */
const char *hos_data_dir(void);
/* <data folder>/<name> into out (name may hold a sub-folder: "shaders/x.bin"); 0 when it does not fit */
int hos_data_path(char *out, size_t cap, const char *name);
/* <game folder>/<name> (host/hos_paths.h's game folder: the one with image.bin); 0 when there is none or it does not fit */
int hos_game_file(char *out, size_t cap, const char *name);
/* What hos_data_init moved, said in the log (which may itself have been one of the files moved: so after it is open) */
void hos_data_log_migration(void);
#ifdef _WIN32
/* The data folder as a wide string, for the code that works in wide paths (host/hos_update.c) */
const wchar_t *hos_data_dir_w(void);
#endif
#ifdef __cplusplus
}
#endif
