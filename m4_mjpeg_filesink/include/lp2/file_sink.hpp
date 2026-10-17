#pragma once

#include <cstddef>
#include <string>

#include "lp2/media_sink.hpp"

namespace lp2 {

class FileSink : public IMediaSink {
public:
    FileSink(const std::string& output_directory, std::size_t save_count);

    bool initialize();
    bool consume(const Frame& frame) override;

    std::size_t saved_files() const;
    std::size_t write_failures() const;
    std::size_t invalid_frames_delivered() const;
    const std::string& error() const;

private:
    std::string make_output_path(std::size_t index) const;

    std::string output_directory_;
    std::size_t save_count_;
    std::size_t saved_files_ = 0;
    std::size_t write_failures_ = 0;
    std::size_t invalid_frames_delivered_ = 0;
    bool initialized_ = false;
    std::string error_;
};

}  // namespace lp2
