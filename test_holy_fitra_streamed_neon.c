#include "holy_fitra_streamed_neon.h"

#include <math.h>
#include <stdio.h>

int main(void) {
    const float input[] = {1.0f, -2.0f, 0.5f};
    const float weights[] = {
        1.0f, 2.0f, 3.0f, 4.0f, 5.0f,
        -1.0f, 0.5f, 1.5f, -2.0f, 3.0f,
        2.0f, -1.0f, 0.0f, 1.0f, -0.5f,
    };
    const float expected[] = {4.0f, 0.5f, 0.0f, 8.5f, -1.25f};
    float output[5] = {0};
    if (hf_streamed_f32_block_abi() != HF_STREAMED_F32_BLOCK_ABI) return 1;
    if (hf_streamed_f32_block_matvec(input, 3, weights, 15, output, 5, 3, 5, HF_STREAMED_F32_BLOCK_ABI) != HF_OK) return 2;
    for (int index = 0; index < 5; ++index) if (fabsf(output[index] - expected[index]) > 1e-6f) return 3;
    if (hf_streamed_f32_block_matvec(input, 2, weights, 15, output, 5, 3, 5, HF_STREAMED_F32_BLOCK_ABI) != HF_BUFFER_TOO_SMALL) return 4;
    if (hf_streamed_f32_block_matvec(input, 3, weights, 15, output, 5, 3, 5, HF_STREAMED_F32_BLOCK_ABI + 1u) != HF_UNSUPPORTED_ABI) return 5;
    { const float invalid[] = {NAN, -2.0f, 0.5f}; if (hf_streamed_f32_block_matvec(invalid, 3, weights, 15, output, 5, 3, 5, HF_STREAMED_F32_BLOCK_ABI) != HF_INVALID_ARGUMENT) return 6; }
    if (hf_streamed_f32_block_matvec(input, 3, weights, 15, output, 5, HF_STREAMED_F32_MAX_ROWS + 1, 1, HF_STREAMED_F32_BLOCK_ABI) != HF_INVALID_ARGUMENT) return 7;
    puts("holy_fitra_streamed_neon=passed");
    return 0;
}
