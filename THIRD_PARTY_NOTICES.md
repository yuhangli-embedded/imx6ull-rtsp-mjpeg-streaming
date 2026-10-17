# Third-party sources and license scope

## Project-authored material

[LICENSE](LICENSE) applies to the project-authored C++ implementation, scripts,
tests and documentation to the extent owned by the project author. The
maintainer has confirmed publication rights and no institutional or employer
prohibition. The neutral copyright credit identifies the project author without
inventing a personal name or contributor history.

MIT does **not** replace the historical terms for the RFC-derived parameter
material identified below. Distribute this notice and its linked license text
with the source, including downstream copies containing that material.

## RFC 2435 Appendix B parameters

Affected file: `m4_rtp_jpeg_check/src/jpeg_standard_codebooks.hpp`.

The grouped numeric symbols represent default JPEG interoperability parameters,
transcribed from Appendix B of RFC 2435, October 1998. The header also declares
a small project-authored C++ data structure. For clarity, RFC-derived parameter
material is treated separately from project-authored implementation; no
public-domain or blanket MIT claim is made for those parameters.

[LICENSES/RFC2435-notice.txt](LICENSES/RFC2435-notice.txt) preserves the original
copyright notice and complete permission paragraph required by the RFC's
historical statement. Retain that text, this attribution and the parameter-file
reference when redistributing the affected material. The RFC document itself
is not bundled or presented as a modified specification.

### Historical authorization, not retroactive Revised BSD

- [RFC 2435, Full Copyright Statement](https://www.rfc-editor.org/rfc/rfc2435.html):
  the publication-specific permission is the primary basis for the parameter
  representation used to implement RTP/JPEG, with its notice condition preserved.
- [RFC 2026, sections 10.3.1 and 10.4(C)](https://www.rfc-editor.org/rfc/rfc2026.html):
  the copyright policy effective in 1998.
- [IETF Trust copyright FAQ, sections 1.3 and 2.5](https://trustee.ietf.org/documents/trust-legal-provisions/copyright-policy-and-tlp-faq/):
  dates the policy regimes and expressly addresses reuse/modification of code
  components before March 2005.
- [Original 2008 Trust Legal Provisions, section 2(b)-(d)](https://trustee.ietf.org/wp-content/uploads/IETF-TLP-1.pdf):
  pre-existing documents retain their publication-era terms.
- [Current corrected TLP, section 5(c)](https://trustee.ietf.org/documents/trust-legal-provisions/tlp-5/):
  does not supply evidence of a new rights grant for all older material.

This review relies on the historical permission with retained conditions, not
on retroactive application of current Revised BSD text or a waiver of notices.
The combination is MIT project code **plus separately retained RFC terms**,
not a relicensing of the entire RFC under MIT. It is a scoped source-distribution
assessment, not legal certification or a patent/trademark clearance.

## Rewritten implementation

`m4_rtp_jpeg_check/src/rfc2435_huffman.cpp` contains the newly designed
canonical-codebook matcher and bounded DHT serializer covered by the project MIT
license. It does not contain the old untraceable implementation or the RFC's
example C routines. Its API was kept compatible. See
[replacement record](docs/huffman-replacement.md); no isolated clean-room
history is claimed.

## Synthetic JPEG and external tools

The only included image is a numeric geometric pattern; no camera photo or
external image input was used. [Fixture provenance](tests/fixtures/README.md)
records its generator/hash. The Windows platform encoder generated the JPEG;
no encoder implementation or DLL is redistributed and no rights in that encoder
are claimed. Project-authored fixture/generator material follows the project
license, not a license to the platform software.

[RFC 3550](https://www.rfc-editor.org/rfc/rfc3550.html) is a protocol reference,
not a bundled document. V4L2/POSIX/C++ headers, FFmpeg/ffplay, GNU tools, Python,
CMake and the Poky SDK are external prerequisites, not vendored implementations.
The board pipeline does not link FFmpeg libraries. No third-party logo or
endorsement is claimed.

## Review result

The previously identified RFC-parameter notice blocker is addressed through
the historical grant and retained notice. This does not guarantee that every
future contribution or dependency has the same license, or that tests establish
legal compliance. Keep scope and notices intact when changing or distributing
the repository.
