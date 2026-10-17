set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

if(NOT DEFINED ENV{OECORE_TARGET_SYSROOT})
    message(FATAL_ERROR
        "Yocto SDK environment is not active. Source "
        "/opt/fsl-imx-x11/4.1.15-2.1.0/"
        "environment-setup-cortexa7hf-neon-poky-linux-gnueabi first."
    )
endif()

if(NOT DEFINED ENV{CXX} OR NOT "$ENV{CXX}" MATCHES "poky-linux-gnueabi-g\\+\\+")
    message(FATAL_ERROR
        "CXX is not the i.MX6ULL Poky SDK compiler. Refusing to use a host "
        "or Ubuntu arm-linux-gnueabihf-g++ compiler."
    )
endif()

if(DEFINED CMAKE_CXX_COMPILER AND
   NOT "${CMAKE_CXX_COMPILER}" MATCHES "poky-linux-gnueabi-g\\+\\+")
    message(FATAL_ERROR
        "The build directory caches a non-Poky C++ compiler. Use a fresh "
        "build directory for the i.MX6ULL SDK build."
    )
endif()

set(CMAKE_SYSROOT "$ENV{OECORE_TARGET_SYSROOT}")
set(CMAKE_FIND_ROOT_PATH "$ENV{OECORE_TARGET_SYSROOT}")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
