typedef unsigned char uint8_t;
typedef signed char int8_t;
typedef int int32_t;
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

void nibbleflow_int4_f32_ref(const float *input, const uint8_t *packed, const float *scales, const float *bias, float *output, int32_t in_dim, int32_t out_dim, int32_t group_size) {
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
                group_sum += input0 < in_dim ? input[input0] * (float)sign_extend_nibble(byte) : 0.0f;
                group_sum += input0 + 1 < in_dim ? input[input0 + 1] * (float)sign_extend_nibble((uint8_t)(byte >> 4)) : 0.0f;
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

int32_t nibbleflow_abi_version(void) { return 1; }
