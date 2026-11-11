# Run from the game folder. The Builder supplies this as /bin/sh -c source so
# it is available even after the Builder's AppImage mount goes away.
# The log goes to the game's data folder, as its own log does (host/hos_data.c):
# $XDG_DATA_HOME/hookshot when that is an absolute path, else
# ~/.local/share/hookshot; the game folder when neither can be made.
umask 077
case ${XDG_DATA_HOME-} in
    /*) data=$XDG_DATA_HOME/hookshot ;;
    *) data=${HOME:-}/.local/share/hookshot ;;
esac
case $data in
    /*) mkdir -p -- "$data" 2>/dev/null || data=. ;;
    *) data=. ;;
esac
temporary=$(mktemp -d "$data/.hookshot-startup.XXXXXX") || exec "$1"
trap 'rm -f -- "$temporary/stderr" "$temporary/status"; rmdir -- "$temporary"' EXIT

# The game keeps stdout discarded. Drain all of stderr so a noisy game can
# continue after the retained prefix is full.
{
    "$1" 2>&1 >/dev/null
    printf '\nHookshot exited with status %s\n' "$?" > "$temporary/status"
} | {
    head -c 65536 > "$temporary/stderr"
    cat >/dev/null
}
if [ -f "$temporary/stderr" ] && [ -f "$temporary/status" ]; then
    cat "$temporary/status" >> "$temporary/stderr" &&
        mv -fT -- "$temporary/stderr" "$data/hookshot_startup.log"
fi
