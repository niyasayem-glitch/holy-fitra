cmake_minimum_required(VERSION 3.22.1)
project(holyfitra_android LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(HF_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../..")

set(HF_COMMON_CXX_FLAGS -ffunction-sections -fdata-sections -fvisibility=hidden)

add_library(holyfitra_runtime SHARED
    "${HF_ROOT}/nibbleflow_kernel.c"
    "${HF_ROOT}/nibbleflow_android.cpp"
    "${HF_ROOT}/holy_fitra_dispatch.cpp"
    "${HF_ROOT}/holy_fitra_android_topology.cpp"
    "${HF_ROOT}/holy_fitra_runtime.cpp"
    "${HF_ROOT}/holy_fitra_jni.cpp"
)
target_include_directories(holyfitra_runtime PRIVATE "${HF_ROOT}")
target_compile_options(holyfitra_runtime PRIVATE ${HF_COMMON_CXX_FLAGS})
target_compile_definitions(holyfitra_runtime PRIVATE HOLY_FITRA_ANDROID_RUNTIME=1)
target_link_options(holyfitra_runtime PRIVATE -Wl,--gc-sections)

add_library(holyfitra_nibbleflow SHARED
    "${HF_ROOT}/nibbleflow_kernel.c"
    "${HF_ROOT}/nibbleflow_android.cpp"
    "${HF_ROOT}/nibbleflow_jni.cpp"
)
target_include_directories(holyfitra_nibbleflow PRIVATE "${HF_ROOT}")
target_compile_options(holyfitra_nibbleflow PRIVATE ${HF_COMMON_CXX_FLAGS})
target_link_options(holyfitra_nibbleflow PRIVATE -Wl,--gc-sections)

add_library(holyfitra_benchmark SHARED
    "${HF_ROOT}/nibbleflow_kernel.c"
    "${HF_ROOT}/holy_fitra_ragged_kernel.c"
    "${HF_ROOT}/holy_fitra_ragged_scheduler.cpp"
    "${HF_ROOT}/holy_fitra_dispatch.cpp"
    "${HF_ROOT}/holy_fitra_android_topology.cpp"
    "${HF_ROOT}/holy_fitra_device_benchmark.cpp"
    "${HF_ROOT}/holy_fitra_device_benchmark_jni.cpp"
)
target_include_directories(holyfitra_benchmark PRIVATE "${HF_ROOT}")
target_compile_options(holyfitra_benchmark PRIVATE ${HF_COMMON_CXX_FLAGS})
target_compile_definitions(holyfitra_benchmark PRIVATE HOLY_FITRA_ANDROID_RUNTIME=1)
target_link_options(holyfitra_benchmark PRIVATE -Wl,--gc-sections)

find_library(log-lib log)
if(log-lib)
    target_link_libraries(holyfitra_runtime PRIVATE ${log-lib})
    target_link_libraries(holyfitra_nibbleflow PRIVATE ${log-lib})
    target_link_libraries(holyfitra_benchmark PRIVATE ${log-lib})
endif()
