#!/bin/sh
# BusyBox-compatible, fixed LP2 scope. Run via SSH stdin only after review.
# No kill, service, network, camera or init-script operations.
set -eu
ROOT=/opt/lp2-media
PROC=/proc
OWNER=LP2-M7-RELEASE-V1
action=${1:-help}
ver=${2:-}
approval=${3:-}
dry=0
for arg in "$@"; do [ "$arg" != --dry-run ] || dry=1; done
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
version_ok() {
    case "$1" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9._-]*) return 1 ;; esac
    [ "${#1}" -le 64 ]
}
hash_ok() { [ "${#1}" = 64 ] && ! printf '%s' "$1" | grep -q '[^0-9a-f]'; }
note() { printf '%s\n' "$*"; }
check_tools() {
    for cmd in readlink sha256sum awk grep sed find wc od tr cp chmod mkdir rmdir ln mv cat dirname sync; do
        command -v "$cmd" >/dev/null 2>&1 || fail "Required tool missing: $cmd"
    done
    # Atomic symlink replacement MUST NOT follow the destination directory.
    mv --help 2>&1 | grep -q '\-T' || fail 'mv -T required; refusing unsafe mv fallback'
    [ "$(readlink -f "$(dirname "$ROOT")")" = "$(dirname "$ROOT")" ] || fail 'Parent path must be canonical'
}
owned() {
    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] || fail 'LP2 root absent or a symlink; run init after review'
    [ -f "$ROOT/.lp2-owned" ] && [ ! -L "$ROOT/.lp2-owned" ] || fail 'Unowned existing directory; never take it over'
    [ "$(cat "$ROOT/.lp2-owned")" = "$OWNER" ] || fail 'Ownership marker mismatch'
    for sub in releases staging verified; do
        [ -d "$ROOT/$sub" ] && [ ! -L "$ROOT/$sub" ] || fail "Unsafe/missing $sub directory"
    done
    for name in previous; do
        [ ! -L "$ROOT/$name" ] || fail "Unsafe $name symlink"
        [ ! -e "$ROOT/$name" ] || [ -f "$ROOT/$name" ] || fail "Unsafe $name type"
    done
}
lock() {
    [ "$dry" = 1 ] && return
    mkdir "$ROOT/.release-lock" 2>/dev/null || fail 'Operation locked; inspect owner before manual recovery'
    trap 'rmdir "$ROOT/.release-lock"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
}
field() { sed -n "s/^$2=//p" "$1/manifest"; }
verify_dir() {
    dir=$1
    [ -d "$dir" ] && [ ! -L "$dir" ] && [ -d "$dir/bin" ] && [ ! -L "$dir/bin" ] || fail 'Unsafe package directory'
    [ -z "$(find "$dir" -type l -print)" ] || fail 'Package symlinks forbidden'
    [ "$(find "$dir" -type f | wc -l | tr -d ' ')" = 7 ] || fail 'Unexpected/missing package files'
    [ "$(find "$dir" -type d | wc -l | tr -d ' ')" = 2 ] || fail 'Unexpected package directories'
    [ "$(find "$dir" -print | wc -l | tr -d ' ')" = 9 ] || fail 'Unexpected package entries'
    for file in bin/lp2_rtsp_server manifest run-args.txt build-info.txt source-sha256.json elf.json SHA256SUMS; do
        [ -f "$dir/$file" ] || fail "Missing file $file"
    done
    # Validate names BEFORE sha256sum -c: malicious sums must not read outside LP2.
    awk '
      BEGIN {split("bin/lp2_rtsp_server manifest run-args.txt build-info.txt source-sha256.json elf.json", a," "); for(i=1;i<=6;i++) allow[a[i]]=1}
      NF!=2 || length($1)!=64 || $1 ~ /[^0-9a-f]/ || !allow[$2] || seen[$2]++ {bad=1}
      END {if(NR!=6 || bad) exit 1}' "$dir/SHA256SUMS" || fail 'Unsafe checksum index'
    (cd "$dir" && sha256sum -c SHA256SUMS) || fail 'Checksum mismatch'
    [ "$(wc -l < "$dir/manifest" | tr -d ' ')" = 7 ] || fail 'Bad manifest field count'
    [ "$(field "$dir" format)" = lp2-release-v1 ] && [ "$(field "$dir" version)" = "$ver" ] || fail 'Manifest format/version mismatch'
    [ "$(field "$dir" origin)" = fresh-poky-release-build ] || fail 'Not a fresh Poky release'
    [ "$(field "$dir" baseline_sha256)" = c1d0c7b0518cf21af091834c5cff400bbf538682b9560c02cce6932c2d9ba04e ] || fail 'Baseline mismatch'
    [ "$(field "$dir" hardware_gate)" = PENDING ] || fail 'Manifest may not claim an unobserved board Gate'
    case "$(field "$dir" baseline_hash_equal)" in yes|no) ;; *) fail 'Bad baseline comparison' ;; esac
    actual=$(sha256sum "$dir/bin/lp2_rtsp_server" | awk '{print $1}')
    [ "$(field "$dir" binary_sha256)" = "$actual" ] || fail 'Manifest binary hash mismatch'
    magic=$(od -An -tx1 -N7 "$dir/bin/lp2_rtsp_server" | tr -d ' \n')
    machine=$(od -An -tx1 -j18 -N2 "$dir/bin/lp2_rtsp_server" | tr -d ' \n')
    [ "$magic" = 7f454c46010101 ] && [ "$machine" = 2800 ] || fail 'Not little-endian ARM ELF32'
    [ "$(cat "$dir/run-args.txt")" = '--device /dev/video2 --width 1280 --height 720 --fps 30 --rtsp-port 8554 --path /live --max-clients 2 --slow-client-id 0 --slow-client-delay-ms 0 --udp-gap-us 10 --udp-frame-budget-ms 100 --frames 0' ] || fail 'Runtime arguments differ from frozen normal configuration'
}
process_identity() {
    # /proc/PID/stat: comm can contain spaces and parentheses. Remove through
    # its LAST ") "; remainder starts at original field 3 (state), so
    # remainder fields 7 and 20 are original fields 9 (flags) and 22 (starttime).
    stat_line=$(cat "$1/stat") || return 1
    stat_pid=${stat_line%% *}
    [ "$stat_pid" = "${1##*/}" ] || return 1
    case "$stat_line" in "$stat_pid ("*") "*) ;; *) return 1 ;; esac
    stat_rest=${stat_line##*) }
    [ "$stat_rest" != "$stat_line" ] || return 1
    printf '%s\n' "$stat_rest" | awk '
        NF >= 20 && $1 ~ /^[RSDTtZXxKWPI]$/ && $7 ~ /^[0-9]+$/ &&
        $7 <= 4294967295 && $20 ~ /^[0-9]+$/ {
            # Avoid signed 32-bit shell arithmetic on the Cortex-A7 rootfs.
            # PF_KTHREAD = 0x00200000; division/modulo examines exactly this bit.
            printf "%s %d\n", $20, int($7 / 2097152) % 2; ok=1
        }
        END {if (!ok || NR != 1) exit 1}'
}
idle_required() {
    # Full exe paths, never names. Also reject running staged/manual-gate images.
    [ -d "$PROC" ] && [ -r "$PROC" ] && [ -x "$PROC" ] || fail 'Cannot inspect processes'
    # Enumerate PID directories, not exe links: a failed -L must never silently
    # hide an inaccessible user process. Any exit/reuse race fails closed.
    for process_dir in "$PROC"/[0-9]*; do
        pid=${process_dir##*/}
        case "$pid" in ''|*[!0-9]*) continue ;; esac
        before=$(process_identity "$process_dir") || fail "Cannot inspect process stat: PID=$pid (unreadable or exited); retry after review"
        if [ "${before##* }" = 1 ]; then
            after=$(process_identity "$process_dir") || fail "Kernel process disappeared or became unreadable: PID=$pid; retry after review"
            [ "$before" = "$after" ] || fail "Process identity changed: PID=$pid (reuse/race); refusing switch"
            # Only a positively identified, stable PF_KTHREAD skips exe.
            continue
        fi
        target=$(readlink "$process_dir/exe") || fail "Cannot inspect user process executable: PID=$pid (unreadable or exited); refusing switch"
        case "$target" in /*) ;; *) fail "Invalid user executable path: PID=$pid; refusing switch" ;; esac
        after=$(process_identity "$process_dir") || fail "User process disappeared or became unreadable: PID=$pid; refusing switch"
        [ "$before" = "$after" ] || fail "Process identity changed: PID=$pid (reuse/race); refusing switch"
        case "$target" in
            "$ROOT"/*|/tmp/lp2_m5_rtsp_server|/var/volatile/tmp/lp2_m5_rtsp_server|/tmp/lp2_m5_rtsp_server\ \(deleted\)|/var/volatile/tmp/lp2_m5_rtsp_server\ \(deleted\))
                fail 'LP2 process still running; manually stop and review final accounting first' ;;
        esac
    done
}
current_version() {
    old=
    if [ -L "$ROOT/current" ]; then
        link=$(readlink "$ROOT/current") || fail 'Cannot inspect current'
        case "$link" in releases/*) old=${link#releases/} ;; *) fail 'Unknown current target' ;; esac
        version_ok "$old" || fail 'Unsafe current version'
        saved_ver=$ver; ver=$old; verify_dir "$ROOT/releases/$old"; ver=$saved_ver
        [ -f "$ROOT/verified/$old" ] && [ ! -L "$ROOT/verified/$old" ] || fail 'Current lacks approval receipt'
        [ "$(cat "$ROOT/verified/$old")" = "$(field "$ROOT/releases/$old" binary_sha256)" ] || fail 'Current approval mismatch'
    elif [ -e "$ROOT/current" ]; then
        fail 'current is not a managed symlink'
    fi
}
switch_to() {
    verify_dir "$ROOT/releases/$ver"
    hash_ok "$approval" && [ "$approval" = "$actual" ] || fail 'Exact operator VERIFIED SHA-256 required (after manual board Gate)'
    idle_required
    current_version
    [ "$old" != "$ver" ] || fail 'Already current; no switch needed'
    # A failure before mv leaves old current intact. Temporary files are NEVER
    # overwritten, and remain for manual inspection on unexpected failures.
    for path in "$ROOT/.current.next" "$ROOT/.previous.next" "$ROOT/verified/$ver.next"; do
        [ ! -e "$path" ] && [ ! -L "$path" ] || fail "Stale transaction: $path"
    done
    [ ! -L "$ROOT/verified/$ver" ] || fail 'Unsafe approval receipt'
    [ ! -e "$ROOT/verified/$ver" ] || [ -f "$ROOT/verified/$ver" ] || fail 'Unsafe approval type'
    note "Switch current: ${old:-none} -> $ver; no process is started"
    [ "$dry" = 0 ] || return 0
    printf '%s\n' "$approval" > "$ROOT/verified/$ver.next"
    mv -T "$ROOT/verified/$ver.next" "$ROOT/verified/$ver"
    printf '%s\n' "$old" > "$ROOT/.previous.next"
    mv -T "$ROOT/.previous.next" "$ROOT/previous"
    sync
    ln -s "releases/$ver" "$ROOT/.current.next"
    mv -T "$ROOT/.current.next" "$ROOT/current"
    sync
}
check_tools
case "$action" in
    init)
        if [ -e "$ROOT" ] || [ -L "$ROOT" ]; then owned; note 'Existing LP2-owned layout verified'; exit 0; fi
        note "Create isolated $ROOT; no service/init changes"
        [ "$dry" = 0 ] || exit 0
        umask 077
        mkdir "$ROOT"
        printf '%s\n' "$OWNER" > "$ROOT/.lp2-owned"
        mkdir "$ROOT/releases" "$ROOT/staging" "$ROOT/verified"
        ;;
    stage|verify-staged|install|verify|switch|rollback)
        owned; lock
        if [ "$action" = rollback ]; then
            [ -f "$ROOT/previous" ] || fail 'No previous version; first install has no rollback target'
            ver=$(cat "$ROOT/previous"); version_ok "$ver" || fail 'Unsafe/empty previous version'
            [ -f "$ROOT/verified/$ver" ] && [ ! -L "$ROOT/verified/$ver" ] || fail 'Previous approval missing'
            approval=$(cat "$ROOT/verified/$ver")
            switch_to
            exit 0
        fi
        version_ok "$ver" || fail 'Invalid version'
        case "$action" in
            stage)
                [ ! -e "$ROOT/staging/$ver" ] && [ ! -L "$ROOT/staging/$ver" ] || fail 'Staging version already exists'
                note "Create empty upload staging: $ROOT/staging/$ver"
                [ "$dry" = 1 ] || mkdir "$ROOT/staging/$ver"
                ;;
            verify-staged) verify_dir "$ROOT/staging/$ver" ;;
            verify) verify_dir "$ROOT/releases/$ver" ;;
            install)
                verify_dir "$ROOT/staging/$ver"
                [ ! -e "$ROOT/releases/$ver" ] && [ ! -L "$ROOT/releases/$ver" ] || fail 'Immutable version already exists'
                tmp="$ROOT/releases/.install-$ver"
                [ ! -e "$tmp" ] && [ ! -L "$tmp" ] || fail 'Incomplete previous install; review manually'
                note "Install verified immutable version $ver (does NOT activate)"
                [ "$dry" = 0 ] || exit 0
                mkdir "$tmp" "$tmp/bin"
                for file in manifest run-args.txt build-info.txt source-sha256.json elf.json SHA256SUMS; do cp "$ROOT/staging/$ver/$file" "$tmp/$file"; done
                cp "$ROOT/staging/$ver/bin/lp2_rtsp_server" "$tmp/bin/lp2_rtsp_server"
                chmod 755 "$tmp/bin/lp2_rtsp_server"
                verify_dir "$tmp"
                sync
                mv -T "$tmp" "$ROOT/releases/$ver"
                sync
                ;;
            switch) switch_to ;;
        esac
        ;;
    *) fail 'Usage: init | stage VERSION | verify-staged VERSION | install VERSION | verify VERSION | switch VERSION VERIFIED_SHA256 | rollback; optional --dry-run' ;;
esac
