#include "holy_fitra_ragged_kernel.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint32_t next_u32(uint32_t *state) {
    *state = *state * 1664525u + 1013904223u;
    return *state;
}

int main(void) {
    float q[256] = {0.0f};
    float k[256] = {0.0f};
    float v[256] = {0.0f};
    float output[256] = {0.0f};
    int32_t offsets[32] = {0};
    uint32_t state = 0x51f7a123u;
    size_t valid = 0;
    for (size_t iteration = 0; iteration < 100000; ++iteration) {
        for (size_t i = 0; i < 32; ++i) offsets[i] = (int32_t)(next_u32(&state) % 80u) - 4;
        if ((iteration % 97u) == 0u) q[iteration % 256u] = 0.0f / 0.0f;
        else if ((iteration % 89u) == 0u) q[iteration % 256u] = 1.0f / 0.0f;
        else q[iteration % 256u] = 0.25f;
        hf_ragged_attention_batch batch = {
            q, next_u32(&state) % 257u,
            k, next_u32(&state) % 257u,
            v, next_u32(&state) % 257u,
            output, next_u32(&state) % 257u,
            offsets, next_u32(&state) % 33u,
            (int32_t)(next_u32(&state) % 22u) - 2,
            (int32_t)(next_u32(&state) % 22u) - 2,
        };
        int accepted = hf_validate_ragged_batch(&batch);
        if (accepted) {
            ++valid;
            holy_fitra_ragged_attention_scalar(&batch);
        }
    }
    assert(valid > 0);
    printf("ragged_fuzz_iterations=100000 valid=%zu\n", valid);
    return 0;
}
