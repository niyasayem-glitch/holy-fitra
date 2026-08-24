#include "holy_fitra_device_benchmark.h"

#include <cstring>

int main() {
    holyfitra::StreamedBlockBenchmarkConfig config;
    config.rows = 7;
    config.columns = 5;
    config.warmup_iterations = 1;
    config.measured_iterations = 4;
    config.thermal_sample_period = 1;
    config.continuous_thermal_sampling = false;
    const holyfitra::StreamedBlockBenchmarkResult result = holyfitra::run_holy_fitra_streamed_block_benchmark(config);
    if (!result.completed) return 1;
    if (std::strstr(result.json.c_str(), "\"schema\":\"holyfitra.streamed-block-benchmark/v1\"") == nullptr) return 2;
    if (std::strstr(result.json.c_str(), "\"correctness\":{\"max_abs_error\":") == nullptr) return 3;
    if (std::strstr(result.json.c_str(), "\"pass\":true") == nullptr) return 4;
    config.columns = 513;
    const holyfitra::StreamedBlockBenchmarkResult invalid = holyfitra::run_holy_fitra_streamed_block_benchmark(config);
    if (invalid.completed || std::strstr(invalid.json.c_str(), "\"error\":\"invalid_config\"") == nullptr) return 5;
    return 0;
}
