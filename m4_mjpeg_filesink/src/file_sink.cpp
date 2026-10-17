#include "lp2/file_sink.hpp"
#include "lp2/jpeg_validator.hpp"

#include <cerrno>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>

#include <sys/stat.h>
#include <sys/types.h>

namespace lp2 {
namespace {

int create_directory(const char* path)
{
#if defined(_WIN32)
    return mkdir(path);
#else
    return mkdir(path, 0755);
#endif
}

}  // namespace

FileSink::FileSink(
    const std::string& output_directory,
    std::size_t save_count
)
    : output_directory_(output_directory),
      save_count_(save_count)
{
}

bool FileSink::initialize()
{
    if (output_directory_.empty()) {
        error_ = "Output directory must not be empty";
        return false;
    }

    struct stat status {};
    if (stat(output_directory_.c_str(), &status) == 0) {
        if (!S_ISDIR(status.st_mode)) {
            error_ = "Output path exists but is not a directory";
            return false;
        }
    } else {
        if (errno != ENOENT ||
            create_directory(output_directory_.c_str()) != 0) {
            std::ostringstream message;
            message << "Cannot create output directory: "
                    << std::strerror(errno);
            error_ = message.str();
            return false;
        }
    }

    initialized_ = true;
    return true;
}

bool FileSink::consume(const Frame& frame)
{
    if (!JpegValidator::validate(frame).valid) {
        ++invalid_frames_delivered_;
        error_ = "Invalid JPEG delivered to FileSink";
        return false;
    }
    if (!initialized_) {
        error_ = "FileSink is not initialized";
        ++write_failures_;
        return false;
    }
    if (saved_files_ >= save_count_) {
        return true;
    }

    const std::string path = make_output_path(saved_files_ + 1);
    std::ofstream output(path.c_str(), std::ios::binary | std::ios::trunc);
    if (!output) {
        error_ = "Cannot open output file: " + path;
        ++write_failures_;
        return false;
    }

    output.write(
        reinterpret_cast<const char*>(frame.storage.data()),
        static_cast<std::streamsize>(frame.size)
    );
    output.close();
    if (!output) {
        error_ = "Cannot write complete JPEG file: " + path;
        ++write_failures_;
        return false;
    }

    ++saved_files_;
    return true;
}

std::size_t FileSink::saved_files() const
{
    return saved_files_;
}

std::size_t FileSink::write_failures() const
{
    return write_failures_;
}

std::size_t FileSink::invalid_frames_delivered() const
{
    return invalid_frames_delivered_;
}

const std::string& FileSink::error() const
{
    return error_;
}

std::string FileSink::make_output_path(std::size_t index) const
{
    std::ostringstream path;
    path << output_directory_;
    if (output_directory_[output_directory_.size() - 1] != '/') {
        path << '/';
    }
    path << "frame_" << std::setw(6) << std::setfill('0')
         << index << ".jpg";
    return path.str();
}

}  // namespace lp2
