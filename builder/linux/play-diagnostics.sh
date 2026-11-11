# Run from the game folder. The Builder supplies this as /bin/sh -c source so
# it is available even after the Builder's AppImage mount goes away.
# The log goes to the game folder's logs folder, beside the game's own log
# (host/hos_data.c); the game folder itself when that cannot be made.
umask 077
logs=logs
mkdir -p -- "$logs" 2>/dev/null || logs=.
temporary=$(mktemp -d "$logs/.hookshot-startup.XXXXXX") || exec "$1"
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
        mv -fT -- "$temporary/stderr" "$logs/hookshot_startup.log"
fi
