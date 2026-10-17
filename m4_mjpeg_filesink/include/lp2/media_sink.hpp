#pragma once

#include "lp2/frame.hpp"

namespace lp2 {

class IMediaSink {
public:
    virtual ~IMediaSink() {}
    virtual bool consume(const Frame& frame) = 0;
};

}  // namespace lp2
