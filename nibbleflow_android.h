#ifndef HOLY_FITRA_NIBBLEFLOW_ANDROID_H
#define HOLY_FITRA_NIBBLEFLOW_ANDROID_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

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

typedef struct hf_nibbleflow_model {
    const uint8_t *packed;
    size_t packed_bytes;
    const float *scales;
    size_t scale_count;
    const float *bias;
    size_t bias_count;
    int32_t in_dim;
    int32_t out_dim;
    int32_t group_size;
    uint32_t abi_version;
} hf_nibbleflow_model;

uint32_t hf_nibbleflow_runtime_abi(void);
int hf_nibbleflow_has_neon(void);
hf_status hf_nibbleflow_validate_model(const hf_nibbleflow_model *model);
hf_status hf_nibbleflow_matvec(const hf_nibbleflow_model *model, const float *input, size_t input_count, float *output, size_t output_count);
const char *hf_status_string(hf_status status);

#ifdef __cplusplus
}
#endif

#endif
