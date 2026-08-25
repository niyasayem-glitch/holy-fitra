typedef signed char int8_t;
typedef int int32_t;
typedef unsigned char uint8_t;
typedef unsigned long size_t;

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

#define NIBBLEFLOW_TILE_OUT 4

static inline int8_t sign_extend_nibble(uint8_t nibble) {
    nibble &= 0x0Fu;
    return (int8_t)(nibble < 8u ? nibble : (int)nibble - 16);
}

static inline size_t packed_index(int in_dim, int out_dim, int group_size, int tile, int group, int pair, int lane) {
    (void)out_dim;
    int groups = (in_dim + group_size - 1) / group_size;
    int pairs = group_size / 2;
    return (size_t)((((tile * groups + group) * pairs + pair) * NIBBLEFLOW_TILE_OUT) + lane);
}

static inline size_t scale_index(int in_dim, int group_size, int tile, int group, int lane) {
    int groups = (in_dim + group_size - 1) / group_size;
    return (size_t)((tile * groups + group) * NIBBLEFLOW_TILE_OUT + lane);
}

static void nibbleflow_int4_f32_ref_scalar_range(const float *input, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size, int32_t first_output, int32_t end_output) {
    int groups = (in_dim + group_size - 1) / group_size;
    int pairs = group_size / 2;
    for (int out_index = first_output; out_index < end_output; ++out_index) {
        int tile = out_index / NIBBLEFLOW_TILE_OUT;
        int lane = out_index % NIBBLEFLOW_TILE_OUT;
        float total = 0.0f;
        for (int group = 0; group < groups; ++group) {
            float group_sum = 0.0f;
            float scale = scales[scale_index(in_dim, group_size, tile, group, lane)];
            int start = group * group_size;
            for (int pair = 0; pair < pairs; ++pair) {
                uint8_t byte = packed[packed_index(in_dim, out_dim, group_size, tile, group, pair, lane)];
                int input0 = start + pair * 2;
                group_sum += input0 < in_dim ? input[input0] * (float)sign_extend_nibble(byte) : 0.0f;
                group_sum += input0 + 1 < in_dim ? input[input0 + 1] * (float)sign_extend_nibble((uint8_t)(byte >> 4)) : 0.0f;
            }
            total += group_sum * scale;
        }
        output[out_index] = total + (bias ? bias[out_index] : 0.0f);
    }
}

void nibbleflow_int4_f32_ref(const float *input, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size) {
    const int groups = (in_dim + group_size - 1) / group_size;
    const int pairs = group_size / 2;
    const int full_tile_end = (out_dim / NIBBLEFLOW_TILE_OUT) * NIBBLEFLOW_TILE_OUT;

    // Packed weights are naturally organized as four output lanes. Reusing an
    // activation pair across the complete tile removes the fallback's repeated
    // input loads without altering layout, quantization, or scalar tail rules.
    for (int tile_start = 0; tile_start < full_tile_end; tile_start += NIBBLEFLOW_TILE_OUT) {
        const int tile = tile_start / NIBBLEFLOW_TILE_OUT;
        float total0 = 0.0f;
        float total1 = 0.0f;
        float total2 = 0.0f;
        float total3 = 0.0f;
        for (int group = 0; group < groups; ++group) {
            const int start = group * group_size;
            int valid = in_dim - start;
            if (valid > group_size) valid = group_size;
            float group0 = 0.0f;
            float group1 = 0.0f;
            float group2 = 0.0f;
            float group3 = 0.0f;
            for (int pair = 0; pair < pairs; ++pair) {
                const int input0 = pair * 2;
                if (input0 >= valid) break;
                const float x0 = input[start + input0];
                const float x1 = input0 + 1 < valid ? input[start + input0 + 1] : 0.0f;
                const size_t base = packed_index(in_dim, out_dim, group_size, tile, group, pair, 0);
                const uint8_t byte0 = packed[base];
                const uint8_t byte1 = packed[base + 1];
                const uint8_t byte2 = packed[base + 2];
                const uint8_t byte3 = packed[base + 3];
                group0 += x0 * (float)sign_extend_nibble(byte0) + x1 * (float)sign_extend_nibble((uint8_t)(byte0 >> 4));
                group1 += x0 * (float)sign_extend_nibble(byte1) + x1 * (float)sign_extend_nibble((uint8_t)(byte1 >> 4));
                group2 += x0 * (float)sign_extend_nibble(byte2) + x1 * (float)sign_extend_nibble((uint8_t)(byte2 >> 4));
                group3 += x0 * (float)sign_extend_nibble(byte3) + x1 * (float)sign_extend_nibble((uint8_t)(byte3 >> 4));
            }
            const size_t scale_base = scale_index(in_dim, group_size, tile, group, 0);
            total0 += group0 * scales[scale_base];
            total1 += group1 * scales[scale_base + 1];
            total2 += group2 * scales[scale_base + 2];
            total3 += group3 * scales[scale_base + 3];
        }
        output[tile_start] = total0 + (bias ? bias[tile_start] : 0.0f);
        output[tile_start + 1] = total1 + (bias ? bias[tile_start + 1] : 0.0f);
        output[tile_start + 2] = total2 + (bias ? bias[tile_start + 2] : 0.0f);
        output[tile_start + 3] = total3 + (bias ? bias[tile_start + 3] : 0.0f);
    }
    if (full_tile_end < out_dim) nibbleflow_int4_f32_ref_scalar_range(input, packed, scales, bias, output, in_dim, out_dim, group_size, full_tile_end, out_dim);
}

void nibbleflow_int4_f32(const float *input, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size);

void nibbleflow_int4_f32_batch4(const float *input, size_t input_stride, const uint8_t *packed, const float *scales, const float *bias, float *output, size_t output_stride, int32_t in_dim, int32_t out_dim, int32_t group_size) {
#if defined(__aarch64__)
    // Keep the established architecture-specific NEON implementation as the
    // ARM64 path until a separately measured multi-row NEON microkernel lands.
    for (int row = 0; row < 4; ++row) nibbleflow_int4_f32(input + (size_t)row * input_stride, packed, scales, bias, output + (size_t)row * output_stride, in_dim, out_dim, group_size);
#else
    const int groups = (in_dim + group_size - 1) / group_size;
    const int pairs = group_size / 2;
    const int full_tile_end = (out_dim / NIBBLEFLOW_TILE_OUT) * NIBBLEFLOW_TILE_OUT;
    for (int tile_start = 0; tile_start < full_tile_end; tile_start += NIBBLEFLOW_TILE_OUT) {
        const int tile = tile_start / NIBBLEFLOW_TILE_OUT;
        float totals[4][4] = {{0.0f, 0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f, 0.0f}};
        for (int group = 0; group < groups; ++group) {
            const int start = group * group_size;
            int valid = in_dim - start;
            if (valid > group_size) valid = group_size;
            float group_sums[4][4] = {{0.0f, 0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f, 0.0f}};
            for (int pair = 0; pair < pairs; ++pair) {
                const int input0 = pair * 2;
                if (input0 >= valid) break;
                const size_t base = packed_index(in_dim, out_dim, group_size, tile, group, pair, 0);
                const uint8_t byte0 = packed[base];
                const uint8_t byte1 = packed[base + 1];
                const uint8_t byte2 = packed[base + 2];
                const uint8_t byte3 = packed[base + 3];
                for (int row = 0; row < 4; ++row) {
                    const float *row_input = input + (size_t)row * input_stride;
                    const float x0 = row_input[start + input0];
                    const float x1 = input0 + 1 < valid ? row_input[start + input0 + 1] : 0.0f;
                    group_sums[row][0] += x0 * (float)sign_extend_nibble(byte0) + x1 * (float)sign_extend_nibble((uint8_t)(byte0 >> 4));
                    group_sums[row][1] += x0 * (float)sign_extend_nibble(byte1) + x1 * (float)sign_extend_nibble((uint8_t)(byte1 >> 4));
                    group_sums[row][2] += x0 * (float)sign_extend_nibble(byte2) + x1 * (float)sign_extend_nibble((uint8_t)(byte2 >> 4));
                    group_sums[row][3] += x0 * (float)sign_extend_nibble(byte3) + x1 * (float)sign_extend_nibble((uint8_t)(byte3 >> 4));
                }
            }
            const size_t scale_base = scale_index(in_dim, group_size, tile, group, 0);
            for (int row = 0; row < 4; ++row) {
                totals[row][0] += group_sums[row][0] * scales[scale_base];
                totals[row][1] += group_sums[row][1] * scales[scale_base + 1];
                totals[row][2] += group_sums[row][2] * scales[scale_base + 2];
                totals[row][3] += group_sums[row][3] * scales[scale_base + 3];
            }
        }
        for (int row = 0; row < 4; ++row) {
            float *row_output = output + (size_t)row * output_stride;
            row_output[tile_start] = totals[row][0] + (bias ? bias[tile_start] : 0.0f);
            row_output[tile_start + 1] = totals[row][1] + (bias ? bias[tile_start + 1] : 0.0f);
            row_output[tile_start + 2] = totals[row][2] + (bias ? bias[tile_start + 2] : 0.0f);
            row_output[tile_start + 3] = totals[row][3] + (bias ? bias[tile_start + 3] : 0.0f);
        }
    }
    if (full_tile_end < out_dim) {
        for (int row = 0; row < 4; ++row) nibbleflow_int4_f32_ref_scalar_range(input + (size_t)row * input_stride, packed, scales, bias, output + (size_t)row * output_stride, in_dim, out_dim, group_size, full_tile_end, out_dim);
    }
#endif
}

void nibbleflow_int4_i8_f32_ref(const int8_t *input, float activation_scale, int32_t activation_zero_point, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size) {
    int groups = (in_dim + group_size - 1) / group_size;
    int pairs = group_size / 2;
    for (int out_index = 0; out_index < out_dim; ++out_index) {
        int tile = out_index / NIBBLEFLOW_TILE_OUT;
        int lane = out_index % NIBBLEFLOW_TILE_OUT;
        float total = 0.0f;
        for (int group = 0; group < groups; ++group) {
            float group_sum = 0.0f;
            float scale = scales[scale_index(in_dim, group_size, tile, group, lane)];
            int start = group * group_size;
            for (int pair = 0; pair < pairs; ++pair) {
                uint8_t byte = packed[packed_index(in_dim, out_dim, group_size, tile, group, pair, lane)];
                int input0 = start + pair * 2;
                if (input0 < in_dim) group_sum += ((float)input[input0] - (float)activation_zero_point) * activation_scale * (float)sign_extend_nibble(byte);
                if (input0 + 1 < in_dim) group_sum += ((float)input[input0 + 1] - (float)activation_zero_point) * activation_scale * (float)sign_extend_nibble((uint8_t)(byte >> 4));
            }
            total += group_sum * scale;
        }
        output[out_index] = total + (bias ? bias[out_index] : 0.0f);
    }
}

#if defined(__aarch64__)
static inline int8x8_t decode_nibbles(uint8x8_t packed) {
    uint8x8_t low = vand_u8(packed, vdup_n_u8(0x0f));
    uint8x8_t high = vshr_n_u8(packed, 4);
    int8x8_t low_signed = vreinterpret_s8_u8(low);
    int8x8_t high_signed = vreinterpret_s8_u8(high);
    uint8x8_t low_ge8 = vcge_u8(low, vdup_n_u8(8));
    uint8x8_t high_ge8 = vcge_u8(high, vdup_n_u8(8));
    low_signed = vsub_s8(low_signed, vreinterpret_s8_u8(vand_u8(low_ge8, vdup_n_u8(16))));
    high_signed = vsub_s8(high_signed, vreinterpret_s8_u8(vand_u8(high_ge8, vdup_n_u8(16))));
    return vzip_s8(low_signed, high_signed).val[0];
}
#endif

void nibbleflow_int4_f32(const float *input, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size) {
#if defined(__aarch64__)
    int groups = (in_dim + group_size - 1) / group_size;
    int pairs = group_size / 2;
    int tiles = (out_dim + NIBBLEFLOW_TILE_OUT - 1) / NIBBLEFLOW_TILE_OUT;
    for (int tile = 0; tile < tiles; ++tile) {
        float32x4_t accum = vdupq_n_f32(0.0f);
        for (int group = 0; group < groups; ++group) {
            int start = group * group_size;
            int valid = in_dim - start;
            if (valid > group_size) valid = group_size;
            float32x4_t group_acc = vdupq_n_f32(0.0f);
            for (int pair = 0; pair < pairs; ++pair) {
                int input0 = pair * 2;
                if (input0 >= valid) break;
                uint8_t bytes[4];
                for (int lane = 0; lane < 4; ++lane) bytes[lane] = packed[packed_index(in_dim, out_dim, group_size, tile, group, pair, lane)];
                int8_t q[8];
                for (int lane = 0; lane < 4; ++lane) {
                    q[lane * 2] = sign_extend_nibble(bytes[lane]);
                    q[lane * 2 + 1] = sign_extend_nibble((uint8_t)(bytes[lane] >> 4));
                }
                float32x4_t x0 = {0, 0, 0, 0};
                float32x4_t x1 = {0, 0, 0, 0};
                if (input0 < valid) x0 = vdupq_n_f32(input[start + input0]);
                if (input0 + 1 < valid) x1 = vdupq_n_f32(input[start + input0 + 1]);
                float32x4_t q0 = {(float)q[0], (float)q[2], (float)q[4], (float)q[6]};
                float32x4_t q1 = {(float)q[1], (float)q[3], (float)q[5], (float)q[7]};
                group_acc = vmlaq_f32(group_acc, x0, q0);
                group_acc = vmlaq_f32(group_acc, x1, q1);
            }
            float32x4_t scale = {scales[scale_index(in_dim, group_size, tile, group, 0)], scales[scale_index(in_dim, group_size, tile, group, 1)], scales[scale_index(in_dim, group_size, tile, group, 2)], scales[scale_index(in_dim, group_size, tile, group, 3)]};
            accum = vmlaq_f32(accum, group_acc, scale);
        }
        float32x4_t add = {0, 0, 0, 0};
        for (int lane = 0; lane < 4; ++lane) {
            int out_index = tile * 4 + lane;
            if (out_index < out_dim) add[lane] = bias ? bias[out_index] : 0.0f;
        }
        accum = vaddq_f32(accum, add);
        for (int lane = 0; lane < 4; ++lane) {
            int out_index = tile * 4 + lane;
            if (out_index < out_dim) output[out_index] = accum[lane];
        }
    }
#else
    nibbleflow_int4_f32_ref(input, packed, scales, bias, output, in_dim, out_dim, group_size);
#endif
}

void nibbleflow_int4_i8_f32(const int8_t *input, float activation_scale, int32_t activation_zero_point, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size) {
#if defined(__aarch64__)
    int groups = (in_dim + group_size - 1) / group_size;
    int pairs = group_size / 2;
    int tiles = (out_dim + NIBBLEFLOW_TILE_OUT - 1) / NIBBLEFLOW_TILE_OUT;
    for (int tile = 0; tile < tiles; ++tile) {
        float32x4_t accum = vdupq_n_f32(0.0f);
        for (int group = 0; group < groups; ++group) {
            int start = group * group_size;
            int valid = in_dim - start;
            if (valid > group_size) valid = group_size;
            float32x4_t group_acc = vdupq_n_f32(0.0f);
            for (int pair = 0; pair < pairs; ++pair) {
                int input0 = pair * 2;
                if (input0 >= valid) break;
                uint8_t bytes[4];
                for (int lane = 0; lane < 4; ++lane) bytes[lane] = packed[packed_index(in_dim, out_dim, group_size, tile, group, pair, lane)];
                float32x4_t x0 = vdupq_n_f32(((float)input[start + input0] - (float)activation_zero_point) * activation_scale);
                float32x4_t x1 = vdupq_n_f32(0.0f);
                if (input0 + 1 < valid) x1 = vdupq_n_f32(((float)input[start + input0 + 1] - (float)activation_zero_point) * activation_scale);
                float32x4_t q0 = {(float)sign_extend_nibble(bytes[0]), (float)sign_extend_nibble(bytes[1]), (float)sign_extend_nibble(bytes[2]), (float)sign_extend_nibble(bytes[3])};
                float32x4_t q1 = {(float)sign_extend_nibble((uint8_t)(bytes[0] >> 4)), (float)sign_extend_nibble((uint8_t)(bytes[1] >> 4)), (float)sign_extend_nibble((uint8_t)(bytes[2] >> 4)), (float)sign_extend_nibble((uint8_t)(bytes[3] >> 4))};
                group_acc = vmlaq_f32(group_acc, x0, q0);
                group_acc = vmlaq_f32(group_acc, x1, q1);
            }
            float32x4_t scale = {scales[scale_index(in_dim, group_size, tile, group, 0)], scales[scale_index(in_dim, group_size, tile, group, 1)], scales[scale_index(in_dim, group_size, tile, group, 2)], scales[scale_index(in_dim, group_size, tile, group, 3)]};
            accum = vmlaq_f32(accum, group_acc, scale);
        }
        float32x4_t add = {0, 0, 0, 0};
        for (int lane = 0; lane < 4; ++lane) {
            int out_index = tile * 4 + lane;
            if (out_index < out_dim) add[lane] = bias ? bias[out_index] : 0.0f;
        }
        accum = vaddq_f32(accum, add);
        for (int lane = 0; lane < 4; ++lane) {
            int out_index = tile * 4 + lane;
            if (out_index < out_dim) output[out_index] = accum[lane];
        }
    }
#else
    nibbleflow_int4_i8_f32_ref(input, activation_scale, activation_zero_point, packed, scales, bias, output, in_dim, out_dim, group_size);
#endif
}

int32_t nibbleflow_abi_version(void) { return 1; }
