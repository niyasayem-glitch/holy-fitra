cmake_minimum_required(VERSION 3.22.1)

project(holyfitra_android LANGUAGES C CXX)

# This file is the authoritative native graph for the Android library module.
# Gradle's externalNativeBuild supplies the NDK toolchain, ANDROID_ABI, and
# ANDROID_PLATFORM. Direct Android builds must pass the same NDK toolchain.
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

option(HF_REQUIRE_ANDROID "Fail unless configured with the Android NDK toolchain" OFF)
option(HF_ENABLE_16K_PAGE_ALIGNMENT "Link ELF segments for 16 KB page-size devices" ON)
option(HF_ENABLE_ARM64_BRANCH_PROTECTION "Enable PAC/BTI branch protection for arm64-v8a" OFF)
option(HF_ENABLE_BENCHMARK "Build the Android benchmark shared library" ON)

if(HF_REQUIRE_ANDROID AND NOT ANDROID)
    message(FATAL_ERROR "Holy Fitra Android targets require the Android NDK toolchain")
endif()

if(ANDROID)
    if(NOT CMAKE_SYSTEM_NAME STREQUAL "Android")
        message(FATAL_ERROR "The Android NDK toolchain did not select the Android system")
    endif()
    if(NOT ANDROID_ABI STREQUAL "arm64-v8a")
        message(FATAL_ERROR "Holy Fitra v1 supports only arm64-v8a in this module")
    endif()
    if(DEFINED ANDROID_PLATFORM_LEVEL AND ANDROID_PLATFORM_LEVEL LESS 26)
        message(FATAL_ERROR "Holy Fitra v1 requires Android API 26 or newer")
    endif()
    message(STATUS "Holy Fitra Android/Bionic build: ABI=${ANDROID_ABI} API=${ANDROID_PLATFORM}")
else()
    message(WARNING "Configuring the Android graph on a non-Android host; this is a host graph check only")
endif()

set(HF_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../..")

set(HF_RUNTIME_SOURCES
    "${HF_ROOT}/nibbleflow_kernel.c"
    "${HF_ROOT}/holy_fitra_streamed_neon.c"
    "${HF_ROOT}/nibbleflow_android.cpp"
    "${HF_ROOT}/holy_fitra_dispatch.cpp"
    "${HF_ROOT}/holy_fitra_android_topology.cpp"
    "${HF_ROOT}/holy_fitra_runtime.cpp"
    "${HF_ROOT}/holy_fitra_jni.cpp"
)

set(HF_NIBBLEFLOW_SOURCES
    "${HF_ROOT}/nibbleflow_kernel.c"
    "${HF_ROOT}/nibbleflow_android.cpp"
    "${HF_ROOT}/nibbleflow_jni.cpp"
)

set(HF_BENCHMARK_SOURCES
    "${HF_ROOT}/nibbleflow_kernel.c"
    "${HF_ROOT}/holy_fitra_streamed_neon.c"
    "${HF_ROOT}/holy_fitra_ragged_kernel.c"
    "${HF_ROOT}/holy_fitra_ragged_scheduler.cpp"
    "${HF_ROOT}/holy_fitra_dispatch.cpp"
    "${HF_ROOT}/holy_fitra_android_topology.cpp"
    "${HF_ROOT}/holy_fitra_device_benchmark.cpp"
    "${HF_ROOT}/holy_fitra_device_benchmark_jni.cpp"
)

foreach(HF_SOURCE IN LISTS HF_RUNTIME_SOURCES HF_NIBBLEFLOW_SOURCES HF_BENCHMARK_SOURCES)
    if(NOT EXISTS "${HF_SOURCE}")
        message(FATAL_ERROR "Holy Fitra source file is missing: ${HF_SOURCE}")
    endif()
endforeach()

set(HF_COMMON_COMPILE_OPTIONS
    -ffunction-sections
    -fdata-sections
    -fstack-protector-strong
    -fvisibility=hidden
)

set(HF_COMMON_LINK_OPTIONS
    -Wl,--gc-sections
    -Wl,--no-undefined
    -Wl,-z,relro
    -Wl,-z,now
)

if(ANDROID AND HF_ENABLE_16K_PAGE_ALIGNMENT)
    # NDK r28+ emits 16 KB-aligned ELF by default. These explicit options keep
    # the contract visible and preserve compatibility with older NDK toolchains.
    list(APPEND HF_COMMON_LINK_OPTIONS
        -Wl,-z,max-page-size=16384
        -Wl,-z,common-page-size=16384
    )
endif()

if(ANDROID AND HF_ENABLE_ARM64_BRANCH_PROTECTION)
    list(APPEND HF_COMMON_COMPILE_OPTIONS -mbranch-protection=standard)
endif()

function(hf_configure_target TARGET_NAME)
    target_include_directories(${TARGET_NAME} PRIVATE "${HF_ROOT}")
    target_compile_options(${TARGET_NAME} PRIVATE
        ${HF_COMMON_COMPILE_OPTIONS}
        $<$<COMPILE_LANGUAGE:CXX>:-fexceptions>
        $<$<CONFIG:Debug>:-O1>
        $<$<CONFIG:Debug>:-g>
        $<$<CONFIG:Debug>:-fno-omit-frame-pointer>
        $<$<CONFIG:Release>:-O3>
    )
    target_compile_definitions(${TARGET_NAME} PRIVATE
        _FILE_OFFSET_BITS=64
        HOLY_FITRA_ANDROID_RUNTIME=1
    )
    target_link_options(${TARGET_NAME} PRIVATE ${HF_COMMON_LINK_OPTIONS})
    set_target_properties(${TARGET_NAME} PROPERTIES
        C_VISIBILITY_PRESET hidden
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN ON
    )
endfunction()

add_library(holyfitra_runtime SHARED ${HF_RUNTIME_SOURCES})
hf_configure_target(holyfitra_runtime)
target_compile_definitions(holyfitra_runtime PRIVATE HOLY_FITRA_RUNTIME_JNI=1)

add_library(holyfitra_nibbleflow SHARED ${HF_NIBBLEFLOW_SOURCES})
hf_configure_target(holyfitra_nibbleflow)
target_compile_definitions(holyfitra_nibbleflow PRIVATE HOLY_FITRA_NIBBLEFLOW_JNI=1)

if(HF_ENABLE_BENCHMARK)
    add_library(holyfitra_benchmark SHARED ${HF_BENCHMARK_SOURCES})
    hf_configure_target(holyfitra_benchmark)
    target_compile_definitions(holyfitra_benchmark PRIVATE HOLY_FITRA_BENCHMARK_JNI=1)
endif()

# Bionic is provided by the Android platform toolchain and must not be linked
# as a fictitious standalone library. Android's log library is an actual NDK
# system dependency and is required by the JNI-facing targets. A non-Android
# configure is retained only as a source/target graph check, so it deliberately
# does not substitute a host logging library.
if(ANDROID)
    find_library(HF_LOG_LIB log REQUIRED)
    target_link_libraries(holyfitra_runtime PRIVATE ${HF_LOG_LIB})
    target_link_libraries(holyfitra_nibbleflow PRIVATE ${HF_LOG_LIB})
    if(HF_ENABLE_BENCHMARK)
        target_link_libraries(holyfitra_benchmark PRIVATE ${HF_LOG_LIB})
    endif()
else()
    message(STATUS "Skipping Android liblog linkage during non-Android graph check")
endif()

# libc++ is selected consistently by Gradle with ANDROID_STL=c++_shared. All
# shared libraries in this module therefore use one app-level C++ runtime.
if(ANDROID AND NOT ANDROID_STL STREQUAL "c++_shared")
    message(WARNING "Expected ANDROID_STL=c++_shared because this module builds multiple shared libraries")
endif()

message(STATUS "Holy Fitra targets: holyfitra_runtime; holyfitra_nibbleflow; benchmark=${HF_ENABLE_BENCHMARK}")
