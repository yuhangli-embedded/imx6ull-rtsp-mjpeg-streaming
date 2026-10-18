# 系统架构与帧所有权

## 采集和分发

1. V4L2 协商 MJPEG、分辨率和帧率，申请 4 个 mmap buffer，实际使用驱动返回的数量。
2. DQBUF 后从 FramePool 获取应用层缓冲，复制 bytesused，再立即 QBUF 原驱动 buffer。
3. Frame 进入容量为 4 的采集队列；满时丢弃最旧帧并归还资源。
4. Consumer 检查 size>=4、开头 FF D8、最后两个有效字节 FF D9。坏帧不进入发送路径，
   完整性丢弃与队列背压丢弃分开统计。
5. 为处于 PLAY 的会话分发引用。每个会话有容量为 2 的队列、独立 Sender、
   socket、SSRC 及 RTP 状态。队列满时 drop-oldest，只释放该会话的引用。
6. 最后一个引用释放后回到容量为 6 的 FramePool。引用授予与归还受互斥保护。

FramePool 在校验之前提供存储。分发不会再为每个客户端复制一份完整帧，
但采集阶段的 mmap→应用层复制是有意保留的安全边界。RTP 路径仍使用动态容器。
[README 架构图](../README.md)中，资源归还和控制箭头不表示媒体处理阶段。

## RTP/JPEG

发送前要求完整 JPEG 同时满足兼容性检查：8-bit Baseline、单次交错扫描、4:2:0、
标准 Huffman 表、两张 8-bit DQT、无 DRI/RST。只分片熵编码扫描数据，不切分整个 JFIF 文件。

RTP/JPEG 使用 type=1、Q=255，首包携带两张量化表，单个数据报不超过
1200 字节（包含 RTP 头），末包 marker=1。服务端 PT=26，协议回归同时覆盖 PT=96。
时间戳来自应用采集时钟并换算为 90 kHz，不是曝光完成时刻，也不能与主机时钟直接相减。

非阻塞 sendto、分片间隔和 EAGAIN 有限重试受单帧发送预算约束。
预算从准备完成后开始，不是整个媒体链路的时延上限。

## 控制与退出

RTSP TCP 处理 OPTIONS、DESCRIBE、SETUP、PLAY、TEARDOWN，媒体使用 UDP，最多两个会话。
客户端直接关闭 TCP 时也释放会话，不要求一定收到 TEARDOWN。
服务端端口对为 5004/5005、5006/5007；RTCP 端口保留，但未实现 RTCP 报告。

单个会话关闭自己的队列、等待自己的 Sender 退出并释放残余引用。
全局退出停止采集、唤醒队列、join worker 并归还资源。
采集和 Consumer 不等待客户端完成网络发送。

SysVinit 和 Watchdog 管理进程生命周期，见[部署说明](deployment.md)；
客户端互通问题及支持范围见[技术边界](limitations.md)。
