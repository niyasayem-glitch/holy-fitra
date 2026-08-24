#include "holy_fitra_streamed_neon.h"

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

static int valid_shape(int32_t rows, int32_t columns, size_t *weight_elements) {
    if (rows <= 0 || columns <= 0 || rows > HF_STREAMED_F32_MAX_ROWS || columns > HF_STREAMED_F32_MAX_COLUMNS) return 0;
    if ((size_t)rows > (size_t)-1 / (size_t)columns) return 0;
    *weight_elements = (size_t)rows * (size_t)columns;
    return 1;
}

static int finite_float(float value) {
    union { float value; uint32_t bits; } representation = { value };
    return (representation.bits & 0x7f800000u) != 0x7f800000u;
}

static int finite_values(const float *values, size_t count) {
    for (size_t index = 0; index < count; ++index) {
        if (!finite_float(values[index])) return 0;
    }
    return 1;
}

static void streamed_f32_block_ref(const float *input, const float *weights, float *output, int32_t rows, int32_t columns) {
    for (int32_t column = 0; column < columns; ++column) {
        float total = 0.0f;
        for (int32_t row = 0; row < rows; ++row) total += input[row] * weights[(size_t)row * (size_t)columns + (size_t)column];
        output[column] = total;
    }
}

#if defined(__aarch64__)
static void streamed_f32_block_neon(const float *input, const float *weights, float *output, int32_t rows, int32_t columns) {
    int32_t column = 0;
    for (; column + 4 <= columns; column += 4) {
        float32x4_t total = vdupq_n_f32(0.0f);
        for (int32_t row = 0; row < rows; ++row) {
            const float32x4_t weight = vld1q_f32(weights + (size_t)row * (size_t)columns + (size_t)column);
            total = vmlaq_n_f32(total, weight, input[row]);
        }
        vst1q_f32(output + column, total);
    }
    for (; column < columns; ++column) {
        float total = 0.0f;
        for (int32_t row = 0; row < rows; ++row) total += input[row] * weights[(size_t)row * (size_t)columns + (size_t)column];
        output[column] = total;
    }
}
#endif

uint32_t hf_streamed_f32_block_abi(void) { return HF_STREAMED_F32_BLOCK_ABI; }

int hf_streamed_f32_block_has_neon(void) {
#if defined(__aarch64__)
    return 1;
#else
    return 0;
#endif
}

static hf_status validate_block(const float *input, size_t input_count, const float *weights, size_t weight_count, float *output, size_t output_count, int32_t rows, int32_t columns, uint32_t abi_version) {
    size_t elements = 0;
    if (abi_version != HF_STREAMED_F32_BLOCK_ABI) return HF_UNSUPPORTED_ABI;
    if (!input || !weights || !output || !valid_shape(rows, columns, &elements)) return HF_INVALID_ARGUMENT;
    if (input_count < (size_t)rows || weight_count < elements || output_count < (size_t)columns) return HF_BUFFER_TOO_SMALL;
    if (!finite_values(input, (size_t)rows) || !finite_values(weights, elements)) return HF_INVALID_ARGUMENT;
    return HF_OK;
}

hf_status hf_streamed_f32_block_matvec_scalar(const float *input, size_t input_count, const float *weights, size_t weight_count, float *output, size_t output_count, int32_t rows, int32_t columns, uint32_t abi_version) {
    const hf_status validation = validate_block(input, input_count, weights, weight_count, output, output_count, rows, columns, abi_version);
    if (validation != HF_OK) return validation;
    streamed_f32_block_ref(input, weights, output, rows, columns);
    return finite_values(output, (size_t)columns) ? HF_OK : HF_KERNEL_FAILURE;
}

hf_status hf_streamed_f32_block_matvec(const float *input, size_t input_count, const float *weights, size_t weight_count, float *output, size_t output_count, int32_t rows, int32_t columns, uint32_t abi_version) {
    const hf_status validation = validate_block(input, input_count, weights, weight_count, output, output_count, rows, columns, abi_version);
    if (validation != HF_OK) return validation;
#if defined(__aarch64__)
    streamed_f32_block_neon(input, weights, output, rows, columns);
#else
    streamed_f32_block_ref(input, weights, output, rows, columns);
#endif
    return finite_values(output, (size_t)columns) ? HF_OK : HF_KERNEL_FAILURE;
}
