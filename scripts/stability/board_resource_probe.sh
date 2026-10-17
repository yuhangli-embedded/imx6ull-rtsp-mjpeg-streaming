#!/bin/sh
# Read-only BusyBox-compatible probe, delivered via SSH stdin; never installed.
# LP2_PROC_ROOT is overridden only by offline fixtures. SSH forces /proc.
set -eu
set -f
proc_root=${LP2_PROC_ROOT:-/proc}
expected_exe=${1:-/tmp/lp2_m5_rtsp_server}
requested_pid=${2:-}

fail() { printf '%s\n' "$2" >&2; exit "$1"; }
case "$expected_exe" in
    /tmp/lp2_m5_rtsp_server|/opt/lp2-media/current/bin/lp2_rtsp_server) ;;
    *) fail 22 'Only the explicit LP2 temporary or persistent executable path is allowed' ;;
esac
case "$requested_pid" in *[!0-9]*|0) fail 22 'Invalid requested PID' ;; esac
expected_real=$(readlink -f "$expected_exe" 2>/dev/null) || fail 22 'Cannot canonicalize LP2 executable; readlink -f is required'
[ -n "$expected_real" ] || fail 22 'Empty canonical LP2 executable path'
if [ "$expected_exe" = /opt/lp2-media/current/bin/lp2_rtsp_server ]; then
    case "$expected_real" in
        /opt/lp2-media/releases/*/bin/lp2_rtsp_server)
            release=${expected_real#/opt/lp2-media/releases/}
            release=${release%/bin/lp2_rtsp_server}
            case "$release" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9._-]*) fail 22 'Unsafe release target' ;; esac
            [ "${#release}" -le 64 ] || fail 22 'Unsafe release target'
            ;;
        *) fail 22 'current must resolve to an LP2 versioned release, not another project' ;;
    esac
fi

matches_exe() {
    target=$(readlink "$proc_root/$1/exe" 2>/dev/null) || return 1
    case "$target" in *' (deleted)') return 1 ;; esac
    # /tmp can be a symlink to /var/volatile/tmp on the target rootfs.
    # Compare canonical full paths, never a basename or a fuzzy process name.
    target_real=$(readlink -f "$proc_root/$1/exe" 2>/dev/null) || return 1
    [ "$target_real" = "$expected_real" ]
}

pid=
if [ -n "$requested_pid" ]; then
    matches_exe "$requested_pid" || fail 22 'Requested PID is absent or no longer LP2'
    pid=$requested_pid
else
    # Enable pathname expansion just for this proc directory enumeration.
    set +f
    for candidate_dir in "$proc_root"/[0-9]*; do
        [ -d "$candidate_dir" ] || continue
        candidate=${candidate_dir##*/}
        case "$candidate" in *[!0-9]*) continue ;; esac
        if matches_exe "$candidate"; then
            [ -z "$pid" ] || fail 21 'Multiple LP2 processes; specify --pid'
            pid=$candidate
        fi
    done
    set -f
    [ -n "$pid" ] || fail 20 'LP2 process not found by full /proc/PID/exe path'
fi

start_ticks() {
    stat_line=$(cat "$proc_root/$pid/stat" 2>/dev/null) || return 1
    # comm may contain spaces and parentheses. Strip through the last ") ".
    rest=${stat_line##*) }
    [ "$rest" != "$stat_line" ] || return 1
    printf '%s\n' "$rest" | awk 'NF >= 20 && $20 ~ /^[0-9]+$/ {print $20; ok=1} END {if (!ok) exit 1}'
}

start_before=$(start_ticks) || fail 23 'Cannot read process starttime'
metrics=$(awk '
    /^VmRSS:/ {if ($3 != "kB") bad=1; rss=$2; r=1}
    /^VmSize:/ {if ($3 != "kB") bad=1; size=$2; v=1}
    /^VmHWM:/ {if ($3 != "kB") bad=1; hwm=$2; h=1}
    /^Threads:/ {threads=$2; t=1}
    /^State:/ {state=$2; s=1}
    END {
        if (bad || !r || !v || !h || !t || !s) exit 1
        printf "%s,%s,%s,%s,%s", rss,size,hwm,threads,state
    }' "$proc_root/$pid/status" 2>/dev/null) || fail 23 'Incomplete or unreadable /proc/PID/status'

[ -r "$proc_root/$pid/fd" ] && [ -x "$proc_root/$pid/fd" ] || fail 23 'Cannot read process fd directory'
fd_count=0
set +f
for entry in "$proc_root/$pid/fd"/*; do
    if [ -e "$entry" ] || [ -L "$entry" ]; then fd_count=$((fd_count + 1)); fi
done
set -f
start_after=$(start_ticks) || fail 24 'Process vanished during sample'
[ "$start_before" = "$start_after" ] && matches_exe "$pid" || fail 24 'Process identity changed during sample'

# Fixed single-line protocol; Ubuntu validates all fields before writing CSV.
printf '%s,%s,%s,%s\n' "$pid" "$start_before" "$fd_count" "$metrics"
