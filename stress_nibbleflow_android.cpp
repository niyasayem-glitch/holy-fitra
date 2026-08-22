#include "nibbleflow_android.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <limits>

static uint32_t next_u32(uint32_t &state) {
    state = state * 1664525u + 1013904223u;
    return state;
}

int main() {
    uint8_t packed[256] = {0};
    float scales[256] = {1.0f};
    float bias[256] = {0.0f};
    float input[256] = {0.0f};
    float output[256] = {0.0f};
    uint32_t state = 0x8a31c7d1u;
    size_t valid = 0;
    for (size_t iteration = 0; iteration < 100000; ++iteration) {
        for (size_t index = 0; index < 256; ++index) {
            scales[index] = 1.0f;
            bias[index] = 0.0f;
        }
        if ((iteration % 97u) == 0u) scales[0] = std::numeric_limits<float>::quiet_NaN();
        if ((iteration % 89u) == 0u) bias[0] = std::numeric_limits<float>::infinity();
        hf_nibbleflow_model model{
            packed, next_u32(state) % 257u,
            scales, next_u32(state) % 257u,
            bias, next_u32(state) % 257u,
            static_cast<int32_t>(next_u32(state) % 70u) - 2,
            static_cast<int32_t>(next_u32(state) % 70u) - 2,
            static_cast<int32_t>(next_u32(state) % 20u) - 2,
            next_u32(state) % 3u == 0u ? hf_nibbleflow_runtime_abi() : next_u32(state),
        };
        const hf_status status = hf_nibbleflow_validate_model(&model);
        if (status == HF_OK) {
            ++valid;
            assert(model.in_dim >= 0 && model.in_dim <= 256);
            assert(model.out_dim >= 0 && model.out_dim <= 256);
            (void)hf_nibbleflow_matvec(&model, input, static_cast<size_t>(model.in_dim), output, static_cast<size_t>(model.out_dim));
        }
    }
    assert(valid > 0);
    std::printf("nibbleflow_fuzz_iterations=100000 valid=%zu\n", valid);
    return 0;
}
