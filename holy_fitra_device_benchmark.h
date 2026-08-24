#ifndef HOLY_FITRA_DEVICE_BENCHMARK_H
#define HOLY_FITRA_DEVICE_BENCHMARK_H

#include <cstdint>
#include <string>

namespace holyfitra {

struct DeviceBenchmarkConfig {
    int32_t d_model = 64;
    int32_t sequence_count = 16;
    int32_t min_length = 16;
    int32_t max_length = 128;
    int32_t sequences_per_task = 2;
    int32_t warmup_iterations = 10;
    int32_t measured_iterations = 100;
    int32_t thermal_sample_period = 1;
    uint64_t seed = 12345;
    bool pin_threads = true;
    bool continuous_thermal_sampling = true;
};

struct DeviceBenchmarkResult {
    bool completed = false;
    std::string json;
};

struct StreamedBlockBenchmarkConfig {
    int32_t rows = 64;
    int32_t columns = 64;
    int32_t warmup_iterations = 20;
    int32_t measured_iterations = 200;
    int32_t thermal_sample_period = 1;
    uint64_t seed = 12345;
    bool continuous_thermal_sampling = true;
};

struct StreamedBlockBenchmarkResult {
    bool completed = false;
    std::string json;
};

DeviceBenchmarkResult run_holy_fitra_device_benchmark(const DeviceBenchmarkConfig &config);
StreamedBlockBenchmarkResult run_holy_fitra_streamed_block_benchmark(const StreamedBlockBenchmarkConfig &config);

} // namespace holyfitra

#endif
