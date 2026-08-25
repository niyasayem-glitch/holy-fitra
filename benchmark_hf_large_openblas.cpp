#include <cblas.h>

#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <vector>

namespace {

constexpr int kInDim = 1024;
constexpr int kOutDim = 1024;
constexpr int kGroupSize = 32;
constexpr int kBatch = 32;
constexpr int kMeasuredRuns = 3;

uint32_t next_word(uint32_t &state) {
    state = state * 1664525u + 1013904223u;
    return state;
}

float generated_signed(uint32_t &state, int divisor) {
    return static_cast<float>(static_cast<int>(next_word(state) % 2049u) - 1024) / static_cast<float>(divisor);
}

int signed_nibble(uint8_t value) {
    const int nibble = static_cast<int>(value & 0x0fu);
    return nibble < 8 ? nibble : nibble - 16;
}

size_t packed_index(size_t groups, size_t pairs, size_t tile, size_t group, size_t pair, size_t lane) {
    return (((tile * groups + group) * pairs + pair) * 4u) + lane;
}

size_t scale_index(size_t groups, size_t tile, size_t group, size_t lane) {
    return (tile * groups + group) * 4u + lane;
}

double milliseconds_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
}

} // namespace

int main() {
    const size_t groups = static_cast<size_t>((kInDim + kGroupSize - 1) / kGroupSize);
    const size_t tiles = static_cast<size_t>((kOutDim + 3) / 4);
    const size_t pairs = static_cast<size_t>(kGroupSize / 2);
    std::vector<uint8_t> packed(tiles * groups * pairs * 4);
    std::vector<float> scales(tiles * groups * 4);
    std::vector<float> bias(kOutDim);
    std::vector<float> input(static_cast<size_t>(kBatch) * kInDim);
    std::vector<float> dense_weights(static_cast<size_t>(kOutDim) * kInDim);
    std::vector<float> output(static_cast<size_t>(kBatch) * kOutDim, 0.0f);

    uint32_t state = 0x4f1bbcd9u;
    for (uint8_t &value : packed) value = static_cast<uint8_t>(next_word(state) & 0xffu);
    for (float &value : scales) value = static_cast<float>(static_cast<int>(next_word(state) % 15u) + 1) / 16.0f;
    for (float &value : bias) value = generated_signed(state, 32);
    for (float &value : input) value = generated_signed(state, 1024);

    for (int out_index = 0; out_index < kOutDim; ++out_index) {
        const size_t tile = static_cast<size_t>(out_index / 4);
        const size_t lane = static_cast<size_t>(out_index % 4);
        for (size_t group = 0; group < groups; ++group) {
            const float scale = scales[scale_index(groups, tile, group, lane)];
            const size_t start = group * kGroupSize;
            for (size_t pair = 0; pair < pairs; ++pair) {
                const uint8_t value = packed[packed_index(groups, pairs, tile, group, pair, lane)];
                dense_weights[static_cast<size_t>(out_index) * kInDim + start + pair * 2] = static_cast<float>(signed_nibble(value)) * scale;
                dense_weights[static_cast<size_t>(out_index) * kInDim + start + pair * 2 + 1] = static_cast<float>(signed_nibble(static_cast<uint8_t>(value >> 4))) * scale;
            }
        }
    }

    auto run_batch = [&]() {
        cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, kBatch, kOutDim, kInDim, 1.0f, input.data(), kInDim, dense_weights.data(), kInDim, 0.0f, output.data(), kOutDim);
        for (int row = 0; row < kBatch; ++row) for (int col = 0; col < kOutDim; ++col) output[static_cast<size_t>(row) * kOutDim + col] += bias[col];
    };

    run_batch(); // warm-up
    double total_ms = 0.0;
    for (int iteration = 0; iteration < kMeasuredRuns; ++iteration) {
        const auto start = std::chrono::steady_clock::now();
        run_batch();
        total_ms += milliseconds_since(start);
    }

    double sum = 0.0;
    double weighted = 0.0;
    for (size_t index = 0; index < output.size(); ++index) {
        sum += output[index];
        weighted += static_cast<double>(index + 1) * output[index];
    }
    const double average_ms = total_ms / static_cast<double>(kMeasuredRuns);
    const double operations = static_cast<double>(kBatch) * kInDim * kOutDim;
    std::cout << std::fixed << std::setprecision(6)
              << "engine=openblas_fp32_expanded_int4"
              << " in_dim=" << kInDim
              << " out_dim=" << kOutDim
              << " batch=" << kBatch
              << " macs=" << static_cast<unsigned long long>(operations)
              << " measured_runs=" << kMeasuredRuns
              << " avg_batch_ms=" << average_ms
              << " output_sum=" << sum
              << " output_weighted=" << weighted
              << "\n";
    return 0;
}
