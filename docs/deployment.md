# 部署与服务管理

仅用于可信、隔离的实验网络：RTSP 无认证，不应暴露到公网。
以下是工具接口说明，不表示运行离线测试时会部署服务；原生测试不需要 sudo。

## 板端前提

- 与 Linux 4.1.15/glibc 2.23 兼容的 Poky 构建，持久化、可写的 /opt。
- SysVinit，runlevel 5，/etc/init.d 和 /etc/rc5.d，不使用 systemd。
- /dev/video2 支持[运行参数](../config/run-args.txt)中的格式。
- start-stop-daemon、logger、readlink -f、stat -c、sha256sum、mv -T。
  BusyBox ash 可用并不代表其 mv 支持 -T。
- 预先检查摄像头、端口及 LP2 专属目录冲突，不修改其他项目或系统服务。

## 发布工具

`scripts/release/transfer_release.py VERSION` 默认只给出上传审核计划，
仅 --execute 才连接示例板端，上传后不激活。示例 root@192.168.50.2 须按实际环境检查。

```text
board_release.sh init [--dry-run]
board_release.sh stage VERSION [--dry-run]
board_release.sh verify-staged VERSION
board_release.sh install VERSION [--dry-run]
board_release.sh verify VERSION
board_release.sh switch VERSION REVIEWED_BINARY_SHA256 [--dry-run]
board_release.sh rollback [--dry-run]
```

先进入独立暂存版本，校验后安装到不可覆盖的 release 目录，再按审核过的 SHA 切换 current。
运行中的 LP2 executable 会阻止切换。previous 和 approval 记录保留；首次安装没有可虚构的回滚版本。
未知归属、未完成事务或不确定残留不得强行删除。

## SysVinit 与 Watchdog

暂存文件为 /opt/lp2-media/service-staging/lp2-media 和 lp2-watchdog。

```text
manage_sysv.sh check
manage_sysv.sh install REVIEWED_INIT_SHA256 [--dry-run]
manage_sysv.sh uninstall [--dry-run]
manage_watchdog.sh check
manage_watchdog.sh install REVIEWED_HELPER_SHA256 [--dry-run]
manage_watchdog.sh uninstall [--dry-run]
```

先 check，再执行工具支持的 dry-run。凭据必须与安装文件匹配，不得修改凭据绕过保护。
init 安装到 /etc/init.d/lp2-media，链接为 /etc/rc5.d/S91lp2-media；安装本身不启动进程。
helper 安装到 /opt/lp2-media/service-tools/lp2-watchdog。

全新安装时，先审核发布版本，再安装 init，明确执行 stop 以准备受管理的停止状态，
最后安装 helper；helper 安装要求 init 已安装、status=3 且 runtime 归属正确。
已有服务升级必须先审核 stop、备份、卸载/安装凭据和回滚顺序，不能直接覆盖 init。

## 生命周期与故障恢复

start 设置 desired=running；stop 先持久化禁用恢复，再停止身份核验通过的进程。
身份检查包含 PID、start ticks、executable 和 Watchdog 命令，不使用模糊名称或 killall/pkill。
默认 5 秒检查一次，300 秒窗口最多 3 次自动恢复；第四次故障锁定，需明确 reset-recovery。
普通 start 不清除故障锁定。

运行身份文件位于 volatile 目录，诊断快照和恢复状态持久化且有大小限制。
回滚需已有审核备份及凭据，不丢弃恢复状态或诊断证据。
reset 与手动 start 可能竞争 action.lock，不得强删安全锁。
Watchdog 不监测画面冻结，也不负责自身死亡后的重启；任意断电及所有关机顺序未作全面保证。
