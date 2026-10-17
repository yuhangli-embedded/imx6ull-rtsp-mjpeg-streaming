# Deployment and recovery boundaries

**Review-only instructions.** Nothing in the offline gate deploys or connects to
a board. This service is intended for a trusted isolated lab network, with no
RTSP authentication and no Internet exposure. Native tests never need sudo.

## Target prerequisites

- i.MX6ULL Linux 4.1.15/glibc 2.23-compatible Poky build; writable persistent /opt.
- SysVinit, runlevel 5, /etc/init.d and rc5.d; not systemd.
- Camera /dev/video2 supporting the profile in [run-args](../config/run-args.txt).
- start-stop-daemon, logger, readlink -f, stat -c, sha256sum and mv -T.
  BusyBox ash alone does not imply its mv supports -T; unsupported tools are refused.
- Check conflicting LP2 paths and ports; do not modify unrelated services.

## Guarded publication tools

`scripts/release/transfer_release.py VERSION` defaults to **local upload review**;
only --execute contacts the example board. It uploads but does not activate.
The example root@192.168.50.2 endpoint is laboratory configuration, not a secret.
Do not use --execute until endpoint, credentials and the entire plan are reviewed.

The board helper's actual interfaces are:

```text
board_release.sh init [--dry-run]
board_release.sh stage VERSION [--dry-run]
board_release.sh verify-staged VERSION
board_release.sh install VERSION [--dry-run]
board_release.sh verify VERSION
board_release.sh switch VERSION REVIEWED_BINARY_SHA256 [--dry-run]
board_release.sh rollback [--dry-run]
```

Data is uploaded to a separate staging version, verified before immutable release
installation, approved by exact SHA and atomically switched via current. A live
LP2 executable blocks switching. previous/approval are preserved; first install
has no previous version and cannot roll back to an imaginary target. Incomplete
transactions or unknown ownership require inspection, never forced deletion.

## SysVinit and watchdog installers

Service staging filenames are fixed to /opt/lp2-media/service-staging/lp2-media
and lp2-watchdog. Tools accept:

```text
manage_sysv.sh check
manage_sysv.sh install REVIEWED_INIT_SHA256 [--dry-run]
manage_sysv.sh uninstall [--dry-run]
manage_watchdog.sh check
manage_watchdog.sh install REVIEWED_HELPER_SHA256 [--dry-run]
manage_watchdog.sh uninstall [--dry-run]
```

Use check and every supported dry-run first. Receipts must match the actual
installed files; never change receipt contents to bypass protection. Install
creates the S91lp2-media runlevel link but does not start the process. Do not
assume a dry-run is a camera/playback gate or that sequence numbers imply readiness.

For a genuinely new installation, approve the Release first, then review/install
the init, explicitly invoke its stop to prepare the owned runtime in a stopped
state, and only then install the watchdog helper. The helper installer requires
an installed init with status=3 and an owned stopped runtime. An upgrade from an
existing service must instead follow its reviewed stop/backup/receipt-preserving
upgrade sequence; never directly overwrite /etc/init.d/lp2-media.

The helper is installed at /opt/lp2-media/service-tools/lp2-watchdog. init is
/etc/init.d/lp2-media, linked from /etc/rc5.d/S91lp2-media. Runtime identity files
are volatile, snapshots/state are persistent and bounded. Rollback needs a
previously reviewed backup plus its receipt; preserve state/diagnostic evidence.

## Lifecycle semantics

start enables desired=running; stop persistently disables recovery before stopping
the exact managed processes. PID, start ticks, executable and watchdog command
identity are checked. No killall/pkill or fuzzy name match. Default polling is 5s;
at most three attempts in a conservative 300s window, fourth failure locks until
explicit reset-recovery. start does not secretly clear a fault lock.

Watchdog does not monitor frozen frames, decoding, RTSP health or its own death.
Reset and manual start may contend on action.lock; do not remove that safety lock.
No guarantee for arbitrary power cuts or complete runlevel/shutdown ordering.
Use the [known limitations](limitations.md) and historical [validation](validation.md).
