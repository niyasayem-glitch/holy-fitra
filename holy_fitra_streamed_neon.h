#ifndef HOLY_FITRA_STREAMED_NEON_H
#define HOLY_FITRA_STREAMED_NEON_H

#if defined(HOLY_FITRA_FREESTANDING)
typedef __SIZE_TYPE__ size_t;
typedef __INT32_TYPE__ int32_t;
typedef __UINT32_TYPE__ uint32_t;
typedef enum hf_status {
    HF_OK = 0,
    HF_INVALID_ARGUMENT = 1,
    HF_BUFFER_TOO_SMALL = 2,
    HF_UNSUPPORTED_ABI = 3,
    HF_OVERFLOW = 4,
    HF_KERNEL_FAILURE = 5,
    HF_CANCELLED = 6,
    HF_DEADLINE_MISSED = 7,
    HF_TIMEOUT = 8
} hf_status;
#else
#include <stddef.h>
#include <stdint.h>

#include "nibbleflow_android.h"
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define HF_STREAMED_F32_BLOCK_ABI 1u
#define HF_STREAMED_F32_MAX_ROWS 8192
#define HF_STREAMED_F32_MAX_COLUMNS 512

uint32_t hf_streamed_f32_block_abi(void);
int hf_streamed_f32_block_has_neon(void);
hf_status hf_streamed_f32_block_matvec(
    const float *input,
    size_t input_count,
    const float *weights,
    size_t weight_count,
    float *output,
    size_t output_count,
    int32_t rows,
    int32_t columns,
    uint32_t abi_version);

#ifdef __cplusplus
}
#endif

#endif
