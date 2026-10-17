cmake_minimum_required(VERSION 3.10)
project(lp2_m5_rtsp_server LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)

set(LP2_M3 "${CMAKE_CURRENT_SOURCE_DIR}/../m3_frame_pipeline")
set(LP2_M4 "${CMAKE_CURRENT_SOURCE_DIR}/../m4_mjpeg_filesink")
set(LP2_RTP "${CMAKE_CURRENT_SOURCE_DIR}/../m4_rtp_jpeg")
set(LP2_CHECK "${CMAKE_CURRENT_SOURCE_DIR}/../m4_rtp_jpeg_check")

add_executable(lp2_m5_rtsp_server
    src/main.cpp
    src/fanout_frame_pool.cpp
    src/rtsp_client_session.cpp
    src/rtsp_protocol.cpp
    src/rtsp_server.cpp
    ${LP2_M3}/src/v4l2_capture.cpp
    ${LP2_M3}/src/frame_pool.cpp
    ${LP2_M3}/src/bounded_frame_queue.cpp
    ${LP2_M4}/src/jpeg_validator.cpp
    ${LP2_RTP}/src/rtp_jpeg.cpp
    ${LP2_RTP}/src/rtp_sink.cpp
    ${LP2_CHECK}/src/jpeg_rtp_inspector.cpp
    ${LP2_CHECK}/src/rfc2435_huffman.cpp
)
target_include_directories(lp2_m5_rtsp_server PRIVATE
    include ${LP2_M3}/include ${LP2_M4}/include
    ${LP2_RTP}/include ${LP2_CHECK}/include)
target_compile_options(lp2_m5_rtsp_server PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(lp2_m5_rtsp_server PRIVATE Threads::Threads pthread)

option(BUILD_TESTING "Build offline tests" ON)
if(BUILD_TESTING)
enable_testing()
if(NOT DEFINED LP2_JPEG_FIXTURE)
    set(LP2_JPEG_FIXTURE "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/synthetic_720p.jpg")
endif()
add_executable(lp2_m5_rtsp_protocol_tests
    tests/rtsp_protocol_tests.cpp src/rtsp_protocol.cpp)
target_include_directories(lp2_m5_rtsp_protocol_tests PRIVATE include)
target_compile_options(lp2_m5_rtsp_protocol_tests PRIVATE
    -Wall -Wextra -Wpedantic)
add_test(NAME lp2_m5_rtsp_protocol_tests COMMAND lp2_m5_rtsp_protocol_tests)

add_executable(lp2_m5_rtsp_rtp_tests
    tests/rtsp_rtp_tests.cpp
    ${LP2_RTP}/src/rtp_jpeg.cpp
    ${LP2_CHECK}/src/jpeg_rtp_inspector.cpp
    ${LP2_CHECK}/src/rfc2435_huffman.cpp)
target_include_directories(lp2_m5_rtsp_rtp_tests PRIVATE
    ${LP2_RTP}/include ${LP2_CHECK}/include)
target_compile_options(lp2_m5_rtsp_rtp_tests PRIVATE
    -Wall -Wextra -Wpedantic)
add_test(NAME lp2_m5_rtsp_rtp_tests COMMAND lp2_m5_rtsp_rtp_tests
    "${LP2_JPEG_FIXTURE}")

add_executable(lp2_m5_fanout_frame_pool_tests
    tests/fanout_frame_pool_tests.cpp
    src/fanout_frame_pool.cpp
    ${LP2_M3}/src/frame_pool.cpp
    ${LP2_M3}/src/bounded_frame_queue.cpp)
target_include_directories(lp2_m5_fanout_frame_pool_tests PRIVATE
    include ${LP2_M3}/include)
target_link_libraries(lp2_m5_fanout_frame_pool_tests PRIVATE
    Threads::Threads pthread)
target_compile_options(lp2_m5_fanout_frame_pool_tests PRIVATE
    -Wall -Wextra -Wpedantic)
add_test(NAME lp2_m5_fanout_frame_pool_tests
    COMMAND lp2_m5_fanout_frame_pool_tests)

add_executable(lp2_m5_slow_client_session_tests
    tests/slow_client_session_tests.cpp
    src/rtsp_client_session.cpp
    src/fanout_frame_pool.cpp
    ${LP2_M3}/src/frame_pool.cpp
    ${LP2_M3}/src/bounded_frame_queue.cpp)
target_include_directories(lp2_m5_slow_client_session_tests PRIVATE
    include ${LP2_M3}/include ${LP2_M4}/include ${LP2_RTP}/include)
target_link_libraries(lp2_m5_slow_client_session_tests PRIVATE
    Threads::Threads pthread)
target_compile_options(lp2_m5_slow_client_session_tests PRIVATE
    -Wall -Wextra -Wpedantic)
add_test(NAME lp2_m5_slow_client_session_tests
    COMMAND lp2_m5_slow_client_session_tests)
endif()
