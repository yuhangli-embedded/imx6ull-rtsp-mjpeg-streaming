# JPEG Huffman 匹配与 DHT 输出

公开版本的 Huffman 组件使用独立设计的 canonical codebook 实现，正式发布版未修改。
标准参数与程序逻辑分离，来源及授权条件不因表示形式改变。

## 参数与接口

`m4_rtp_jpeg_check/src/jpeg_standard_codebooks.hpp` 按码长分组记录
RFC 2435 Appendix B 的 JPEG 默认参数，不包含其示例 C 程序逻辑。
参数保留[历史版权声明](../LICENSES/RFC2435-notice.txt)，项目实现采用 [MIT](../LICENSE)；
完整范围见[第三方声明](../THIRD_PARTY_NOTICES.md)及[授权依据](rfc2435-license-review.md)。

`rfc2435_huffman_match()` 接受 DC/AC、ID 0/1 的四张精确默认表。
调用方提供 16 字节 counts 和 symbol_count 个可读 symbol；空指针、非法选择器、
数量或内容不一致返回 false，不修改输入。

`append_rfc2435_huffman_markers()` 追加顺序为 00、10、01、11 的四个 DHT 段，
共 432 字节，保留调用方已有前缀。调用位置和公开签名保持兼容。

## 实现

初始化时由标准分组构建码字、码长、符号记录。匹配先检查直方图总数和前缀容量，
再核对 canonical 序列；输出由码字生成直方图，先形成有界的 432 字节本地数据，再统一追加。
Catalog 采用 C++11 线程安全初始化，无逐帧堆分配；目的 vector 仍可能分配内存。

原始未知实现不再用于公开分发；不宣称历史上采用了隔离式 clean-room 流程。
标准文件和原始数据来源见[来源映射](../SOURCE_MAP.json)，不据编译成功推断版权。

## 测试

保留全部已有断言，另外从平台编码器生成的合成 JPEG 独立提取 DHT，核对全部输出字节。
测试覆盖每个 counts/symbol 字节变异、空指针、错误数量、非法表号、重复 symbol、
过大/超额直方图、前缀保留和重复追加，不用实现自己的参数头生成期望结果。

完整入口为 `bash tools/validate_huffman_revision.sh`，
构建结果和正式/公开版本区别见[验证记录](validation.md)。
