#!/bin/sh
# LP2-M7.3-INSTALLER-V1. Fixed board paths; never called remotely by tests.
# No update-rc.d/insserv/systemctl; no other service is edited or stopped.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
ROOT=/opt/lp2-media
ETC=/etc
PROC=/proc
INIT=$ETC/init.d/lp2-media
LINK=$ETC/rc5.d/S91lp2-media
CONTROL=$ROOT/service-management
STAGED=$ROOT/service-staging/lp2-media
action=${1:-check}
approval=${2:-}
dry=0
for arg in "$@"; do [ "$arg" != --dry-run ] || dry=1; done
fail() { printf 'LP2 INSTALL ERROR: %s\n' "$*" >&2; exit 1; }
hash_ok() { [ "${#1}" = 64 ] && ! printf '%s' "$1" | grep -q '[^0-9a-f]'; }
root_owned() {
    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] && [ "$(stat -c '%u' "$ROOT")" = 0 ] &&
    [ -f "$ROOT/.lp2-owned" ] && [ ! -L "$ROOT/.lp2-owned" ] &&
    [ "$(cat "$ROOT/.lp2-owned")" = LP2-M7-RELEASE-V1 ] || fail 'Not a root-owned LP2 release root'
    [ -d "$ETC/init.d" ] && [ ! -L "$ETC/init.d" ] &&
    [ -d "$ETC/rc5.d" ] && [ ! -L "$ETC/rc5.d" ] || fail 'Expected non-symlink SysVinit directories absent'
    [ "$(readlink "$PROC/1/exe")" = /sbin/init.sysvinit ] || fail 'This target is not the confirmed board SysVinit'
    [ -L "$ROOT/current" ] || fail 'No activated release; finish M7.2 first'
}
tools() {
    for cmd in cat sha256sum awk grep readlink stat id cp chmod mkdir rmdir mv ln rm ls; do
        command -v "$cmd" >/dev/null || fail "Missing tool: $cmd"
    done
    mv --help 2>&1 | grep -q '\-T' || fail 'mv -T required'
}
control_owned() {
    [ -d "$CONTROL" ] && [ ! -L "$CONTROL" ] && [ "$(stat -c '%u:%a' "$CONTROL")" = 0:700 ] &&
    [ -f "$CONTROL/.lp2-owned" ] && [ ! -L "$CONTROL/.lp2-owned" ] &&
    [ "$(cat "$CONTROL/.lp2-owned")" = LP2-M7.3-INSTALL-V1 ] || fail 'Unknown service-management directory'
    [ ! -L "$CONTROL/installed.sha256" ] || fail 'Unsafe installation receipt'
    [ ! -e "$CONTROL/installed.sha256" ] || [ -f "$CONTROL/installed.sha256" ] || fail 'Unsafe receipt type'
}
installed_owned() {
    control_owned
    [ -f "$CONTROL/installed.sha256" ] || fail 'No LP2 installation receipt'
    installed=$(cat "$CONTROL/installed.sha256")
    hash_ok "$installed" || fail 'Invalid receipt'
    [ -f "$INIT" ] && [ ! -L "$INIT" ] && [ "$(sha256sum "$INIT" | awk '{print $1}')" = "$installed" ] || fail 'Init script was changed or is unknown; refusing overwrite/removal'
    [ -L "$LINK" ] && [ "$(readlink "$LINK")" = ../init.d/lp2-media ] || fail 'Autostart link is missing or belongs elsewhere'
}
staged_valid() {
    [ -d "$ROOT/service-staging" ] && [ ! -L "$ROOT/service-staging" ] &&
    [ -f "$STAGED" ] && [ ! -L "$STAGED" ] || fail 'Expected independent service staging file missing'
    hash_ok "$approval" && [ "$(sha256sum "$STAGED" | awk '{print $1}')" = "$approval" ] || fail 'Exact reviewed service-script SHA256 required'
    grep -q '^# LP2-M7.3-SERVICE-V1$' "$STAGED" || fail 'Wrong staging script identity'
    /bin/sh -n "$STAGED" || fail 'Staged service syntax invalid'
    /bin/sh "$STAGED" check || fail 'Service dependency/current-release check failed'
}
lock() {
    [ "$dry" = 1 ] && return 0
    [ "$(id -u)" = 0 ] || fail 'Root required'
    umask 077
    if [ ! -e "$CONTROL" ] && [ ! -L "$CONTROL" ]; then
        mkdir "$CONTROL"
        printf '%s\n' LP2-M7.3-INSTALL-V1 > "$CONTROL/.lp2-owned"
    fi
    control_owned
    mkdir "$CONTROL/manage.lock" 2>/dev/null || fail 'Installer locked; inspect manually'
    trap 'rmdir "$CONTROL/manage.lock"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
}
tools; root_owned
case "$action" in
  check)
    printf 'Read-only: proposed %s -> ../init.d/lp2-media\n' "$LINK"
    printf 'Current release: '; readlink -f "$ROOT/current"
    printf 'Existing rc5 names (ordering evidence only; no other script contents read):\n'
    ls -1 "$ETC/rc5.d"
    if [ -e "$INIT" ] || [ -L "$INIT" ] || [ -e "$LINK" ] || [ -L "$LINK" ]; then
        installed_owned
        printf 'Existing LP2 init/link ownership verified\n'
    else
        printf 'LP2 names currently free; board PID1/runlevel/toolchain readiness must be checked separately\n'
    fi
    if [ -e "$CONTROL" ] || [ -L "$CONTROL" ]; then control_owned; fi
    ;;
  install)
    staged_valid
    if [ -e "$INIT" ] || [ -L "$INIT" ] || [ -e "$LINK" ] || [ -L "$LINK" ]; then
        installed_owned
        [ "$installed" = "$approval" ] || fail 'Already installed different script; review an explicit upgrade plan'
        printf 'Already installed exactly this approved service\n'; exit 0
    fi
    [ ! -e "$INIT.lp2-next" ] && [ ! -L "$INIT.lp2-next" ] &&
    [ ! -e "$LINK.lp2-next" ] && [ ! -L "$LINK.lp2-next" ] || fail 'Stale install transaction; inspect manually'
    if [ -e "$CONTROL" ] || [ -L "$CONTROL" ]; then control_owned; fi
    printf 'Plan: copy reviewed LP2 init, create S91 link; DO NOT start any process\n'
    [ "$dry" = 0 ] || exit 0
    lock
    [ ! -e "$CONTROL/installed.sha256.next" ] && [ ! -L "$CONTROL/installed.sha256.next" ] || fail 'Stale receipt transaction'
    # Record provenance before installing; a partial failure is visible and
    # requires manual review, never overwritten by an automatic retry.
    printf '%s\n' "$approval" > "$CONTROL/installed.sha256.next"
    mv -T "$CONTROL/installed.sha256.next" "$CONTROL/installed.sha256"
    cp "$STAGED" "$INIT.lp2-next"
    chmod 755 "$INIT.lp2-next"
    [ "$(sha256sum "$INIT.lp2-next" | awk '{print $1}')" = "$approval" ] || fail 'Copied script checksum mismatch'
    mv -T "$INIT.lp2-next" "$INIT"
    ln -s ../init.d/lp2-media "$LINK.lp2-next"
    mv -T "$LINK.lp2-next" "$LINK"
    printf 'Installed LP2 autostart entry; NOT started, NOT rebooted\n'
    ;;
  uninstall)
    installed_owned
    for file in /var/volatile/tmp/lp2-media-service/watchdog.lock /var/volatile/tmp/lp2-media-service/watchdog.pid; do
        [ ! -e "$file" ] && [ ! -L "$file" ] || fail 'Stop/review M7.4 watchdog before removing init; retained evidence refused'
    done
    if /bin/sh "$INIT" status; then code=0; else code=$?; fi
    [ "$code" = 3 ] || fail 'Service running or identity unknown; manually stop/review LP2 first'
    printf 'Plan: remove only verified LP2 init/link; keep releases, runtime logs and receipt\n'
    [ "$dry" = 0 ] || exit 0
    lock; installed_owned
    rm "$LINK"
    rm "$INIT"
    printf 'LP2 autostart uninstalled; no other service touched\n'
    ;;
  *) fail 'Usage: manage_sysv.sh check | install REVIEWED_SHA256 [--dry-run] | uninstall [--dry-run]' ;;
esac
