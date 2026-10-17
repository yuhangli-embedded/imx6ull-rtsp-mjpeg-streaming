cmake_minimum_required(VERSION 3.10)
project(lp2_m4_rtp_jpeg_check LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(lp2_jpeg_rtp_inspector STATIC
    src/jpeg_rtp_inspector.cpp
    src/rfc2435_huffman.cpp
)
target_include_directories(lp2_jpeg_rtp_inspector PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_compile_options(lp2_jpeg_rtp_inspector PRIVATE
    -Wall -Wextra -Wpedantic
)

add_executable(lp2_jpeg_rtp_check src/main.cpp)
target_link_libraries(lp2_jpeg_rtp_check PRIVATE lp2_jpeg_rtp_inspector)
target_compile_options(lp2_jpeg_rtp_check PRIVATE -Wall -Wextra -Wpedantic)

option(BUILD_TESTING "Build offline tests" ON)
if(BUILD_TESTING)
enable_testing()
if(NOT DEFINED LP2_JPEG_FIXTURE)
    set(LP2_JPEG_FIXTURE "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/synthetic_720p.jpg")
endif()
add_executable(lp2_jpeg_rtp_tests tests/jpeg_rtp_tests.cpp)
target_link_libraries(lp2_jpeg_rtp_tests PRIVATE lp2_jpeg_rtp_inspector)
target_compile_options(lp2_jpeg_rtp_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME lp2_jpeg_rtp_inspector COMMAND lp2_jpeg_rtp_tests
    "${LP2_JPEG_FIXTURE}")
endif()
