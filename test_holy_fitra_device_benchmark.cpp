#include "holy_fitra_device_benchmark.h"

#include <cassert>
#include <iostream>
#include <string>

int main() {
    holyfitra::DeviceBenchmarkConfig config;
    config.d_model = 8;
    config.sequence_count = 4;
    config.min_length = 2;
    config.max_length = 7;
    config.sequences_per_task = 2;
    config.warmup_iterations = 2;
    config.measured_iterations = 8;
    config.seed = 77;
    config.pin_threads = false;
    config.thermal_sample_period = 1;
    const auto result = holyfitra::run_holy_fitra_device_benchmark(config);
    assert(result.completed);
    assert(result.json.find("\"latency_ms\"") != std::string::npos);
    assert(result.json.find("\"p50\"") != std::string::npos);
    assert(result.json.find("\"throughput_tokens_per_second\"") != std::string::npos);
    assert(result.json.find("nan") == std::string::npos);
    assert(result.json.find("\"scheduler\"") != std::string::npos);
    std::cout << result.json << "\n";
    return 0;
}
