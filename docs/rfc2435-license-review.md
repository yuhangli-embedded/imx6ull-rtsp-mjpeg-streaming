# RFC 2435 license scope review

## Source and date

RFC2435 was published in October1998. The applicable IETF policy was RFC2026
section10, effective from October1996, not RFC3978 (2005) or RFC5378/TLP (2008).
This review distinguishes an implementation from a modified standards document.

Official sources consulted:
1. [RFC2435, Appendix B and Full Copyright Statement](https://www.rfc-editor.org/rfc/rfc2435.html).
2. [RFC2026, sections10.3.1 and10.4(C)](https://www.rfc-editor.org/rfc/rfc2026.html).
3. [Trust copyright-policy FAQ, sections1.3 and2.5](https://trustee.ietf.org/documents/trust-legal-provisions/copyright-policy-and-tlp-faq/).
4. [Original TLP, effective November10,2008, section2(b)-(d)](https://trustee.ietf.org/wp-content/uploads/IETF-TLP-1.pdf).
5. [Corrected TLP, sections4 and5](https://trustee.ietf.org/documents/trust-legal-provisions/tlp-5/).

The original TLP explicitly leaves pre-existing documents under their historical
publication policies. The Trust FAQ explains that code and prose were not
differentiated before March2005 and describes broad code reuse/modification
unless a no-derivatives legend was present. RFC2435 has its historical permission,
not a separate legend prohibiting the implementation use made here. Do not infer
a retroactive Revised BSD grant from current TLP language.

## Three different subjects

| Subject | Treatment in this repository |
| --- | --- |
| RFC prose and original document | Not republished as a modified standard; links provided |
| Numeric Huffman parameter representation from Appendix B | Retain historical RFC permission/notice; do not claim public domain or relicense as MIT |
| New canonical-codebook C++ matcher/serializer and other project-authored material | MIT, based on maintainer authorization, excluding third-party material |

The standard-data header is an implementation aid, not a purported replacement
RFC. The old untraceable implementation was replaced. No RFC example routines,
IJG/libjpeg or FFmpeg implementation was used for the replacement.

## Distribution decision

The implementation use is assessed under the historical permission, supported
by the Trust's explanation of pre-2005 code reuse. The mandatory notice and
complete permission paragraph from RFC2435 are retained verbatim (normalized
wrapping) in [RFC2435-notice.txt](../LICENSES/RFC2435-notice.txt). This is the
required retained portion, not a claim to reproduce the complete RFC. The
original document remains linked for its complete copyright statement.

The affected header references that notice. The root
[third-party notices](../THIRD_PARTY_NOTICES.md) identify file, source, scope and
redistribution requirements. Keep both files in source distributions and with
downstream distributions containing the parameter material.

MIT applies only to rights the project author can grant. Its notice-preservation
condition is compatible with keeping these additional, separately identified
historical terms; it does not remove them or grant permission to edit the RFC
document itself. This is a combined distribution, not a claim that the entire
repository has a single MIT-only or Revised-BSD-only license.

On these stated facts, no material unresolved RFC copyright blocker is identified
for the proposed scoped distribution. This is not a legal warranty, patent
clearance, assessment of future dependencies, or approval to discard notices.
It is not an assertion that publicly accessible numerical parameters are always
outside copyright protection.

## Build evidence is independent

The maintainer reports the replacement passed native162 tests, ABI-checker9
tests and Poky/static SDK ABI checks. No build was repeated in this review.
The new ARM SHA-256 supplied by the maintainer is
`8b631abafc478e21e23e755d2676f5061bde8292df16c5bc552c4e27e3e84f46`.
It is recorded in the checklist without borrowing M7.2's value. The ARM binary
and raw hash evidence are not bundled or independently inspected in this review.
