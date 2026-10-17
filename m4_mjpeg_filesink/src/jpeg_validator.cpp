#include "lp2/jpeg_validator.hpp"

namespace lp2 {

JpegValidationResult JpegValidator::validate(const Frame& frame)
{
    JpegValidationResult result;
    result.too_small = frame.size < 4;

    const bool has_two_bytes = frame.size >= 2 &&
        frame.size <= frame.storage.size();
    result.missing_soi = !has_two_bytes ||
        frame.storage[0] != 0xff ||
        frame.storage[1] != 0xd8;

    // The captured DS-E12 reference frame ends directly in FF D9. Keep this
    // strict: do not hide corruption by searching arbitrarily through padding.
    result.missing_eoi = !has_two_bytes ||
        frame.storage[frame.size - 2] != 0xff ||
        frame.storage[frame.size - 1] != 0xd9;

    result.valid = !result.too_small &&
        !result.missing_soi &&
        !result.missing_eoi;
    return result;
}

}  // namespace lp2
