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

/*
 * An execution plan is intentionally separate from hf_nibbleflow_model so the
 * original model ABI stays stable. Callers that do not need a plan continue to
 * use hf_nibbleflow_matvec with the v1 model layout.
 */
#define HF_NIBBLEFLOW_EXECUTION_ABI 1u
#define HF_NIBBLEFLOW_ADAPTER_ABI 1u
#define HF_NIBBLEFLOW_CALIBRATION_ABI 1u
#define HF_NIBBLEFLOW_MAX_ADAPTER_RANK 256

typedef enum hf_nibbleflow_activation_mode {
    HF_NIBBLEFLOW_ACTIVATION_F32 = 0,
    HF_NIBBLEFLOW_ACTIVATION_STATIC_INT8 = 1
} hf_nibbleflow_activation_mode;

typedef struct hf_nibbleflow_static_calibration {
    uint32_t abi_version;
    float activation_scale;
    int32_t activation_zero_point;
    float max_abs_activation;
    float observed_clipping_fraction;
    float max_clipping_fraction;
    float observed_normalized_error;
    float max_normalized_error;
    uint64_t sample_count;
} hf_nibbleflow_static_calibration;

typedef struct hf_nibbleflow_adapter {
    const float *down;
    size_t down_count;
    const float *up;
    size_t up_count;
    int32_t rank;
    float scale;
    uint32_t abi_version;
} hf_nibbleflow_adapter;

typedef struct hf_nibbleflow_execution_plan {
    uint32_t abi_version;
    hf_nibbleflow_activation_mode activation_mode;
    const hf_nibbleflow_static_calibration *calibration;
    const hf_nibbleflow_adapter *adapter;
    int8_t *activation_scratch;
    size_t activation_scratch_count;
    float *adapter_scratch;
    size_t adapter_scratch_count;
} hf_nibbleflow_execution_plan;

uint32_t hf_nibbleflow_runtime_abi(void);
int hf_nibbleflow_has_neon(void);
hf_status hf_nibbleflow_validate_model(const hf_nibbleflow_model *model);
hf_status hf_nibbleflow_validate_static_calibration(const hf_nibbleflow_static_calibration *calibration);
hf_status hf_nibbleflow_validate_adapter(const hf_nibbleflow_model *model, const hf_nibbleflow_adapter *adapter);
hf_status hf_nibbleflow_validate_execution_plan(const hf_nibbleflow_model *model, const hf_nibbleflow_execution_plan *plan);
hf_status hf_nibbleflow_matvec(const hf_nibbleflow_model *model, const float *input, size_t input_count, float *output, size_t output_count);
/*
 * Executes a bounded FP32 batch. Rows are contiguous at the supplied strides;
 * groups of four reuse packed INT4 weights, while residual rows use the stable
 * single-row path. Execution plans are intentionally excluded from this v1
 * helper so adapter and activation-scratch semantics remain row-local.
 */
hf_status hf_nibbleflow_matvec_batch_f32(const hf_nibbleflow_model *model, const float *input, size_t row_count, size_t input_stride, float *output, size_t output_stride);
hf_status hf_nibbleflow_matvec_ex(const hf_nibbleflow_model *model, const hf_nibbleflow_execution_plan *plan, const float *input, size_t input_count, float *output, size_t output_count);
const char *hf_status_string(hf_status status);

#ifdef __cplusplus
}
#endif

#endif
