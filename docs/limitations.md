# 技术边界与待确认现象

- 支持最多两个 RTSP/UDP 客户端，JPEG 限于 Baseline、单扫描、4:2:0、
  标准 Huffman、无 restart 的子集，不是完整 RTSP 实现或通用转码器。
- 无认证，不适合公网；未实现 RTCP、重传/NACK/FEC、TCP interleaved、H.264 和音频。
- UVC 可返回未标记错误的不完整 JPEG，当前严格丢弃。驱动 sequence gap 不全是已证实的应用丢帧。
- sendto 成功仅代表提交内核。严重丢包或乱序后，原 ffplay 会话可能延迟较大；
  已观察到重连恢复，未实现原连接快速无缝恢复。
- 两个 ffplay 窗口关闭联动尚未定位；无图形客户端独立性结果不能替代该问题的复核。
- mmap 数据复制到应用层 Frame；RTP 使用动态容器，不是零拷贝或全链路无分配。
  不保证任意负载下都不会耗尽资源。
- Watchdog 只监测进程退出，不检测画面、RTSP 或解码健康，也不自行重启 Watchdog。
  reset 与手动 start 的锁竞争、任意断电事务及所有关机顺序未全面验证。
- 发布工具依赖特定命令能力（含 mv -T）；支持 ash 不等于纯 BusyBox 所有 applet 均兼容。
- 端到端延迟没有严格的最终分布或硬实时上限，见[延迟研究](latency-research.md)。

正式与公开版本、测试通过范围及未闭合证据见[验证记录](validation.md)。
