#pragma once

#include "lp2/frame.hpp"

namespace lp2 {

struct JpegValidationResult {
    bool valid = false;
    bool too_small = false;
    bool missing_soi = false;
    bool missing_eoi = false;
};

class JpegValidator {
public:
    static JpegValidationResult validate(const Frame& frame);
};

}  // namespace lp2
