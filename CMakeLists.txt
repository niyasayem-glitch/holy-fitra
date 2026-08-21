cmake_minimum_required(VERSION 3.22.1)
project(holyfitra_runtime LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(holyfitra_runtime SHARED
    nibbleflow_kernel.c
    nibbleflow_android.cpp
    holy_fitra_dispatch.cpp
    holy_fitra_android_topology.cpp
    holy_fitra_runtime.cpp
    holy_fitra_jni.cpp
)

target_include_directories(holyfitra_runtime PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(holyfitra_runtime PRIVATE
    -O3
    -ffunction-sections
    -fdata-sections
    -fvisibility=hidden
)
target_compile_definitions(holyfitra_runtime PRIVATE HOLY_FITRA_ANDROID_RUNTIME=1)
target_link_options(holyfitra_runtime PRIVATE -Wl,--gc-sections)

find_library(log-lib log)
if(log-lib)
    target_link_libraries(holyfitra_runtime PRIVATE ${log-lib})
endif()
