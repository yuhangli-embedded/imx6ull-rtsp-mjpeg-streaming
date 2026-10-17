cmake_minimum_required(VERSION 3.10)
project(lp2_m4_rtp_jpeg_native LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(LP2_CHECK "${CMAKE_CURRENT_SOURCE_DIR}/../m4_rtp_jpeg_check")
set(LP2_FILE "${CMAKE_CURRENT_SOURCE_DIR}/../m4_mjpeg_filesink")
set(LP2_M3 "${CMAKE_CURRENT_SOURCE_DIR}/../m3_frame_pipeline")
add_library(lp2_rtp_jpeg_core STATIC
    src/rtp_jpeg.cpp
    ${LP2_CHECK}/src/jpeg_rtp_inspector.cpp
    ${LP2_CHECK}/src/rfc2435_huffman.cpp)
target_include_directories(lp2_rtp_jpeg_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include ${LP2_CHECK}/include)
target_compile_options(lp2_rtp_jpeg_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(lp2_m4_rtp_receiver
    src/receiver_main.cpp ${LP2_FILE}/src/file_sink.cpp
    ${LP2_FILE}/src/jpeg_validator.cpp)
target_include_directories(lp2_m4_rtp_receiver PRIVATE
    ${LP2_FILE}/include ${LP2_M3}/include)
target_link_libraries(lp2_m4_rtp_receiver PRIVATE lp2_rtp_jpeg_core)
target_compile_options(lp2_m4_rtp_receiver PRIVATE -Wall -Wextra -Wpedantic)

option(BUILD_TESTING "Build offline tests" ON)
if(BUILD_TESTING)
enable_testing()
if(NOT DEFINED LP2_JPEG_FIXTURE)
    set(LP2_JPEG_FIXTURE "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/synthetic_720p.jpg")
endif()
add_executable(lp2_rtp_jpeg_tests tests/rtp_jpeg_tests.cpp)
target_link_libraries(lp2_rtp_jpeg_tests PRIVATE lp2_rtp_jpeg_core)
target_compile_options(lp2_rtp_jpeg_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME lp2_rtp_jpeg_tests COMMAND lp2_rtp_jpeg_tests
    "${LP2_JPEG_FIXTURE}")
endif()
