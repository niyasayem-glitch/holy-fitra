#include "holy_fitra_runtime.h"

#include <chrono>
#include <cstdio>
#include <iomanip>
#include <iostream>
#include <vector>

namespace {

constexpr int kInDim = 1024;
constexpr int kOutDim = 1024;
constexpr int kGroupSize = 32;
constexpr size_t kBatch = 32;
constexpr int kMeasuredRuns = 3;

uint32_t next_word(uint32_t &state) {
    state = state * 1664525u + 1013904223u;
    return state;
}

float generated_signed(uint32_t &state, int divisor) {
    return static_cast<float>(static_cast<int>(next_word(state) % 2049u) - 1024) / static_cast<float>(divisor);
}

double milliseconds_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
}

struct Checksums {
    double sum = 0.0;
    double weighted = 0.0;
};

Checksums checksums_for(const std::vector<float> &output) {
    Checksums result;
    for (size_t index = 0; index < output.size(); ++index) {
        result.sum += output[index];
        result.weighted += static_cast<double>(index + 1) * output[index];
    }
    return result;
}

} // namespace

int main() {
    const size_t groups = static_cast<size_t>((kInDim + kGroupSize - 1) / kGroupSize);
    const size_t tiles = static_cast<size_t>((kOutDim + 3) / 4);
    const size_t pairs = static_cast<size_t>(kGroupSize / 2);
    std::vector<uint8_t> packed(tiles * groups * pairs * 4);
    std::vector<float> scales(tiles * groups * 4);
    std::vector<float> bias(kOutDim);
    std::vector<float> input(kBatch * kInDim);
    std::vector<float> output(kBatch * kOutDim, 0.0f);

    uint32_t state = 0x4f1bbcd9u;
    for (uint8_t &value : packed) value = static_cast<uint8_t>(next_word(state) & 0xffu);
    for (float &value : scales) value = static_cast<float>(static_cast<int>(next_word(state) % 15u) + 1) / 16.0f;
    for (float &value : bias) value = generated_signed(state, 32);
    for (float &value : input) value = generated_signed(state, 1024);

    hf_nibbleflow_model model{packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(), kInDim, kOutDim, kGroupSize, hf_nibbleflow_runtime_abi()};
    hf_holyfitra_runtime *runtime = hf_runtime_create(&model, 64, 0);
    if (!runtime) return 1;

    auto run_batch = [&]() -> hf_status {
        hf_runtime_request *request = nullptr;
        const hf_status submit = hf_runtime_submit_matvec_batch(runtime, input.data(), kBatch, kInDim, output.data(), kOutDim, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &request);
        if (submit != HF_OK) return submit;
        const hf_status result = hf_runtime_wait(request, 30000);
        hf_runtime_request_destroy(request);
        return result;
    };

    if (run_batch() != HF_OK) return 2; // warm-up
    double total_ms = 0.0;
    for (int iteration = 0; iteration < kMeasuredRuns; ++iteration) {
        const auto start = std::chrono::steady_clock::now();
        if (run_batch() != HF_OK) return 3;
        total_ms += milliseconds_since(start);
    }

    hf_runtime_request *receipt_request = nullptr;
    if (hf_runtime_submit_matvec_batch(runtime, input.data(), kBatch, kInDim, output.data(), kOutDim, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &receipt_request) != HF_OK) return 4;
    if (hf_runtime_wait(receipt_request, 30000) != HF_OK) return 5;
    hf_runtime_batch_receipt receipt{};
    if (hf_runtime_get_batch_receipt(receipt_request, &receipt) != HF_OK) return 6;
    hf_runtime_request_destroy(receipt_request);

    const Checksums checksums = checksums_for(output);
    const double average_ms = total_ms / static_cast<double>(kMeasuredRuns);
    const double operations = static_cast<double>(kBatch) * kInDim * kOutDim;
    std::cout << std::fixed << std::setprecision(6)
              << "engine=hf_native_int4"
              << " in_dim=" << kInDim
              << " out_dim=" << kOutDim
              << " batch=" << kBatch
              << " macs=" << static_cast<unsigned long long>(operations)
              << " measured_runs=" << kMeasuredRuns
              << " avg_batch_ms=" << average_ms
              << " output_sum=" << checksums.sum
              << " output_weighted=" << checksums.weighted
              << " planned_ranges=" << receipt.planned_ranges
              << " admitted_ranges=" << receipt.admitted_ranges
              << " completed_ranges=" << receipt.completed_ranges
              << "\n";
    hf_runtime_destroy(runtime);
    return 0;
}
