# 测试说明

## 原生离线验证

Ubuntu 仓库根目录，未激活 Poky SDK 的终端：

```bash
bash tools/validate_ubuntu.sh
```

脚本导出白名单文件到唯一的本地临时目录，执行清单/来源映射/相对链接/Python 语法检查、
原生 CMake 构建、6 项 CTest、FFmpeg JPEG 实际解码、Shell 语法及 Python 离线回归。
需要 g++、CMake、Python、FFmpeg 和 GNU/POSIX 工具；脚本不自动安装依赖，也不跳过不支持的测试。
它不连接开发板、启动摄像头、安装服务或修改网络；临时证据保留。

6 项 CTest 分别覆盖：

1. RTSP 请求响应、SDP 和 transport 解析。
2. PT=96/PT=26、RTP 头和 marker。
3. 并发引用归还、FramePool 计数及队列淘汰。
4. 慢/快客户端隔离，使用无网络的 Sink 测试替身。
5. RTP/JPEG 扫描数据及量化表保持，分片、乱序、重复、缺片超时和边界。
6. JPEG 标记、采样及 Huffman 校验，包括独立 DHT 参照和异常输入。

协议自测不代替解码；完整入口另外执行实际 JPEG 解码。
固定样本的来源见[样本说明](../tests/fixtures/README.md)。

## 运维与跨平台测试

发布测试使用源码生成的 metadata-only ELF，无机器代码、无可执行段，永不作为 Release 运行。
校验、活跃进程拦截、原子重命名失败保护、篡改检查和回滚断言仍保留。
服务测试使用仓库内 run-args，不依赖私有发布目录。

Windows 可执行 `tools/run_portable_checks.py` 和
`tools/run_offline_regressions.py --windows-subset` 的显式子集。
它们不等价于 Linux procfs、信号及 POSIX 安装验证。
ash 测试夹具仍使用支持 -T 的外部 GNU mv，不代表纯 BusyBox applet 全部兼容。

## ARM 与实机测试

```bash
bash tools/validate_poky.sh
bash tools/validate_huffman_revision.sh
```

前者构建并静态检查 ARM，后者组合原生离线、ABI 检查器和 Poky 验证。
不在主机运行 ARM 测试，也不部署。编译环境见[构建说明](build.md)。

双客户端实机脚本 `scripts/acceptance/m9_dual_client_gate.py` 是明确启用的测试，会使用 SSH，
不会被离线入口调用。URL/host 是脚本常量，不提供虚构的 --host/--url 参数；
运行前检查实验地址、两个空闲会话名额和非交互 SSH。
必须有客户端退出后另一路继续解码的帧数证据，不能只检查进程存活；
SSH/证据不足应区分为无法判断，而不是媒体独立性失败。

已有结果、未闭合证据和版本区别见[验证记录](validation.md)。
