#!/bin/sh
# LP2-M7.4-INSTALLER-V1. Does not overwrite init, current or rc links.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
ROOT=/opt/lp2-media
WD=$ROOT/service-tools/lp2-watchdog
CONTROL=$ROOT/service-management
RECEIPT=$CONTROL/watchdog.sha256
STAGED=$ROOT/service-staging/lp2-watchdog
RUNTIME=/var/volatile/tmp/lp2-media-service
runtime_locked=0
action=${1:-check}
approval=${2:-}
dry=0
for arg in "$@"; do [ "$arg" != --dry-run ] || dry=1; done
fail() { printf 'LP2 WD INSTALL ERROR: %s\n' "$*" >&2; exit 1; }
hash_ok() { [ "${#1}" = 64 ] && ! printf '%s' "$1" | grep -q '[^0-9a-f]'; }
owned() {
    [ "$(id -u)" = 0 ] && [ -d "$ROOT" ] && [ ! -L "$ROOT" ] &&
    [ "$(stat -c '%u' "$ROOT")" = 0 ] && [ -f "$ROOT/.lp2-owned" ] &&
    [ ! -L "$ROOT/.lp2-owned" ] && [ "$(cat "$ROOT/.lp2-owned")" = LP2-M7-RELEASE-V1 ] || fail 'Unknown release root'
    [ -d "$CONTROL" ] && [ ! -L "$CONTROL" ] && [ "$(stat -c '%u:%a' "$CONTROL")" = 0:700 ] &&
    [ -f "$CONTROL/.lp2-owned" ] && [ ! -L "$CONTROL/.lp2-owned" ] &&
    [ "$(cat "$CONTROL/.lp2-owned")" = LP2-M7.3-INSTALL-V1 ] || fail 'M7.3 management ownership missing'
    if [ -e "$ROOT/service-tools" ] || [ -L "$ROOT/service-tools" ]; then
        [ -d "$ROOT/service-tools" ] && [ ! -L "$ROOT/service-tools" ] &&
        [ "$(stat -c '%u:%a' "$ROOT/service-tools")" = 0:755 ] &&
        [ -f "$ROOT/service-tools/.lp2-owned" ] && [ ! -L "$ROOT/service-tools/.lp2-owned" ] &&
        [ "$(cat "$ROOT/service-tools/.lp2-owned")" = LP2-M7.4-TOOLS-V1 ] || fail 'Unknown service-tools directory'
    fi
    for file in "$WD" "$WD.next" "$RECEIPT" "$RECEIPT.next"; do
        [ ! -L "$file" ] && { [ ! -e "$file" ] || [ -f "$file" ]; } || fail 'Unsafe watchdog file type'
    done
}
installed() {
    [ -f "$WD" ] && [ -f "$RECEIPT" ] || fail 'Incomplete watchdog installation'
    wh=$(cat "$RECEIPT")
    hash_ok "$wh" && [ "$wh" = "$(sha256sum "$WD" | awk '{print $1}')" ] || fail 'Watchdog receipt mismatch'
}
quiescent() {
    if /bin/sh /etc/init.d/lp2-media status; then rc=0; else rc=$?; fi
    [ "$rc" = 3 ] || fail 'Stop LP2 with old init first; unknown/running server refused'
    for file in "$RUNTIME/watchdog.lock" "$RUNTIME/watchdog.pid"; do
        [ ! -e "$file" ] && [ ! -L "$file" ] || fail 'Watchdog/action evidence remains; inspect, do not force remove'
    done
    [ "$runtime_locked" = 1 ] || { [ ! -e "$RUNTIME/action.lock" ] && [ ! -L "$RUNTIME/action.lock" ]; } || fail 'Service action lock remains'
}
lock() {
    [ -d "$RUNTIME" ] && [ ! -L "$RUNTIME" ] && [ "$(stat -c '%u:%a' "$RUNTIME")" = 0:700 ] &&
    [ -f "$RUNTIME/.lp2-owned" ] && [ ! -L "$RUNTIME/.lp2-owned" ] &&
    [ "$(cat "$RUNTIME/.lp2-owned")" = LP2-M7.3-RUNTIME-V1 ] || fail 'Prepare owned runtime with old service stop first'
    umask 077
    mkdir "$CONTROL/manage.lock" || fail 'Management lock exists'
    trap 'rmdir "$CONTROL/manage.lock"' EXIT
    mkdir "$RUNTIME/action.lock" || fail 'Concurrent service action or leftover lock'
    runtime_locked=1
    trap 'rmdir "$RUNTIME/action.lock"; rmdir "$CONTROL/manage.lock"' EXIT
}
owned
case "$action" in
 check)
    if [ -e "$WD" ] || [ -e "$RECEIPT" ]; then installed; fi
    printf 'Read-only LP2 watchdog installation ownership check complete\n' ;;
 install)
    [ -d "$ROOT/service-staging" ] && [ ! -L "$ROOT/service-staging" ] &&
    [ -f "$STAGED" ] && [ ! -L "$STAGED" ] || fail 'Safe staged watchdog required'
    hash_ok "$approval" && [ "$approval" = "$(sha256sum "$STAGED" | awk '{print $1}')" ] || fail 'Reviewed SHA required'
    grep -q '^# LP2-M7.4-WATCHDOG-V1$' "$STAGED" || fail 'Wrong helper marker'
    /bin/sh -n "$STAGED" || fail 'Invalid helper syntax'
    if [ -e "$WD" ] || [ -e "$RECEIPT" ]; then
        installed; [ "$wh" = "$approval" ] || fail 'Different helper installed; explicit uninstall/rollback required'
        printf 'Exact helper already installed\n'; exit 0
    fi
    [ ! -e "$WD.next" ] && [ ! -e "$RECEIPT.next" ] || fail 'Stale installation transaction'
    quiescent
    printf 'Plan: install approved helper/receipt only; no init overwrite, no start\n'
    [ "$dry" = 0 ] || exit 0
    umask 077
    lock
    owned; quiescent
    if [ ! -d "$ROOT/service-tools" ]; then
        mkdir "$ROOT/service-tools"
        printf '%s\n' LP2-M7.4-TOOLS-V1 > "$ROOT/service-tools/.lp2-owned"
        chmod 755 "$ROOT/service-tools"
    fi
    cp "$STAGED" "$WD.next"; chmod 755 "$WD.next"
    [ "$(sha256sum "$WD.next" | awk '{print $1}')" = "$approval" ] || fail 'Copy hash mismatch'
    printf '%s\n' "$approval" > "$RECEIPT.next"
    mv -T "$WD.next" "$WD"
    mv -T "$RECEIPT.next" "$RECEIPT"
    printf 'Helper installed; init unchanged, not started\n' ;;
 uninstall)
    installed; quiescent
    printf 'Plan: remove verified helper/receipt only; keep recovery state and logs\n'
    [ "$dry" = 0 ] || exit 0
    lock
    owned; installed; quiescent
    rm "$WD" "$RECEIPT" ;;
 *) fail 'Usage: manage_watchdog.sh check | install SHA [--dry-run] | uninstall [--dry-run]' ;;
esac
