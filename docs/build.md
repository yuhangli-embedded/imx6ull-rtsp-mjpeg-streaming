# 编译说明

## Ubuntu 原生构建

依赖 g++、CMake>=3.13、Python>=3.8、Linux V4L2 头文件、POSIX threads 和 GNU 工具。
完整离线入口还需要 FFmpeg 实际解码合成 JPEG；服务/发布测试使用支持 -T 的 GNU mv。
在未激活 Poky SDK 的终端中执行：

```bash
cmake -S . -B build/native -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLP2_BUILD_TOOLS=ON
cmake --build build/native -- -j2
ctest --test-dir build/native --output-on-failure
```

主目标为 `lp2_m5_rtsp_server`。可选目标为 `lp2_m4_rtp_receiver`、
`lp2_jpeg_rtp_check` 及对应测试。LP2_BUILD_TOOLS=OFF 会移除可选工具及两项测试，
不能用于声称全部 6 项 CTest 通过。原生测试不打开摄像头，无需在 Ubuntu 启动板端服务。

## Poky ARM 构建

指定 SDK 不包含在仓库中。禁止替换为 Ubuntu 通用 ARM 编译器。

```bash
source /opt/fsl-imx-x11/4.1.15-2.1.0/environment-setup-cortexa7hf-neon-poky-linux-gnueabi
cmake -S . -B build/poky-review \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/imx6ull-poky.cmake" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DLP2_BUILD_TOOLS=OFF
cmake --build build/poky-review --target lp2_m5_rtsp_server -- -j2
file build/poky-review/m5_rtsp_server/lp2_m5_rtsp_server
```

目标 ABI：ARM ELF32 little-endian、EABI5 hard-float、glibc 2.23，
解释器为 /lib/ld-linux-armhf.so.3。不能仅凭 file 输出 ARM 就认定兼容。
不要在主机上执行 ARM 测试。

自动交叉编译入口：

```bash
bash tools/validate_poky.sh
```

脚本按白名单生成独立临时副本，在全新目录构建，检查编译器来源、ELF、VFP 调用约定、
动态依赖、RPATH/RUNPATH 和逐库符号版本，拒绝高于 glibc 2.23 的要求。
临时目录保留 gate.log、sdk.json、SHA256SUMS、abi.json 和 readelf 输出，不自动部署。
静态 SDK 兼容检查不能替代板端运行验收。

## 测试和发布包入口

```bash
bash tools/validate_ubuntu.sh
bash tools/validate_huffman_revision.sh
```

前者执行原生完整离线验证；后者依次执行原生验证、ABI 检查器测试及独立 Poky 构建。
原生阶段要求未激活 SDK 的终端。合成样本已提供，无需 Windows 生成步骤。
详见[测试说明](testing.md)和[样本来源](../tests/fixtures/README.md)。

需要构建发布包时，另行执行：

```bash
bash scripts/release/build_release.sh public-review-r1
```

该工具自行加载 SDK，拒绝覆盖同名版本，生成的新包不自动激活。
正式版本、公开版本的结果及哈希见[验证记录](validation.md)，安装流程见[部署说明](deployment.md)。
