#include "nibbleflow_android.h"

#include <cmath>
#include <limits>

extern "C" void nibbleflow_int4_f32(const float *, const uint8_t *, const float *, const float *, float *, int32_t, int32_t, int32_t);
extern "C" void nibbleflow_int4_i8_f32(const int8_t *, float, int32_t, const uint8_t *, const float *, const float *, float *, int32_t, int32_t, int32_t);

static bool multiply_size(size_t left, size_t right, size_t *result) {
    if (left != 0 && right > std::numeric_limits<size_t>::max() / left) return false;
    *result = left * right;
    return true;
}

static bool finite_values(const float *values, size_t count) {
    if (!values) return false;
    for (size_t index = 0; index < count; ++index) if (!std::isfinite(values[index])) return false;
    return true;
}

static size_t expected_groups(const hf_nibbleflow_model *model) {
    const size_t in_dim = static_cast<size_t>(model->in_dim);
    const size_t group_size = static_cast<size_t>(model->group_size);
    return (in_dim + group_size - 1) / group_size;
}

static size_t expected_packed_bytes(const hf_nibbleflow_model *model) {
    const size_t tiles = (static_cast<size_t>(model->out_dim) + 3u) / 4u;
    const size_t groups = expected_groups(model);
    const size_t pairs = static_cast<size_t>(model->group_size / 2);
    if (tiles != 0 && groups > std::numeric_limits<size_t>::max() / tiles) return 0;
    const size_t tile_groups = tiles * groups;
    if (pairs != 0 && tile_groups > std::numeric_limits<size_t>::max() / pairs) return 0;
    const size_t tile_groups_pairs = tile_groups * pairs;
    if (tile_groups_pairs > std::numeric_limits<size_t>::max() / 4) return 0;
    return tile_groups_pairs * 4;
}

static size_t expected_scale_count(const hf_nibbleflow_model *model) {
    const size_t tiles = (static_cast<size_t>(model->out_dim) + 3u) / 4u;
    const size_t groups = expected_groups(model);
    if (tiles != 0 && groups > std::numeric_limits<size_t>::max() / tiles) return 0;
    const size_t tile_groups = tiles * groups;
    if (tile_groups > std::numeric_limits<size_t>::max() / 4) return 0;
    return tile_groups * 4;
}

extern "C" uint32_t hf_nibbleflow_runtime_abi(void) { return 1; }

extern "C" int hf_nibbleflow_has_neon(void) {
#if defined(__aarch64__)
    return 1;
#else
    return 0;
#endif
}

extern "C" hf_status hf_nibbleflow_validate_model(const hf_nibbleflow_model *model) {
    if (!model || !model->packed || !model->scales) return HF_INVALID_ARGUMENT;
    if (model->in_dim <= 0 || model->out_dim <= 0 || model->group_size <= 0 || (model->group_size % 2) != 0) return HF_INVALID_ARGUMENT;
    if (model->abi_version != hf_nibbleflow_runtime_abi()) return HF_UNSUPPORTED_ABI;
    const size_t packed_bytes = expected_packed_bytes(model);
    const size_t scale_count = expected_scale_count(model);
    if (packed_bytes == 0 || scale_count == 0) return HF_OVERFLOW;
    if (model->packed_bytes < packed_bytes || model->scale_count < scale_count) return HF_BUFFER_TOO_SMALL;
    if (model->bias && model->bias_count < static_cast<size_t>(model->out_dim)) return HF_BUFFER_TOO_SMALL;
    if (!finite_values(model->scales, scale_count)) return HF_INVALID_ARGUMENT;
    if (model->bias && !finite_values(model->bias, static_cast<size_t>(model->out_dim))) return HF_INVALID_ARGUMENT;
    return HF_OK;
}

extern "C" hf_status hf_nibbleflow_validate_static_calibration(const hf_nibbleflow_static_calibration *calibration) {
    if (!calibration) return HF_INVALID_ARGUMENT;
    if (calibration->abi_version != HF_NIBBLEFLOW_CALIBRATION_ABI) return HF_UNSUPPORTED_ABI;
    if (!std::isfinite(calibration->activation_scale) || calibration->activation_scale <= 0.0f) return HF_INVALID_ARGUMENT;
    if (calibration->activation_zero_point < -128 || calibration->activation_zero_point > 127) return HF_INVALID_ARGUMENT;
    if (!std::isfinite(calibration->max_abs_activation) || calibration->max_abs_activation <= 0.0f) return HF_INVALID_ARGUMENT;
    if (!std::isfinite(calibration->observed_clipping_fraction) || !std::isfinite(calibration->max_clipping_fraction) || calibration->observed_clipping_fraction < 0.0f || calibration->max_clipping_fraction < 0.0f || calibration->observed_clipping_fraction > calibration->max_clipping_fraction || calibration->max_clipping_fraction > 1.0f) return HF_INVALID_ARGUMENT;
    if (!std::isfinite(calibration->observed_normalized_error) || !std::isfinite(calibration->max_normalized_error) || calibration->observed_normalized_error < 0.0f || calibration->max_normalized_error < 0.0f || calibration->observed_normalized_error > calibration->max_normalized_error) return HF_INVALID_ARGUMENT;
    return calibration->sample_count == 0 ? HF_INVALID_ARGUMENT : HF_OK;
}

extern "C" hf_status hf_nibbleflow_validate_adapter(const hf_nibbleflow_model *model, const hf_nibbleflow_adapter *adapter) {
    const hf_status model_status = hf_nibbleflow_validate_model(model);
    if (model_status != HF_OK) return model_status;
    if (!adapter || !adapter->down || !adapter->up) return HF_INVALID_ARGUMENT;
    if (adapter->abi_version != HF_NIBBLEFLOW_ADAPTER_ABI) return HF_UNSUPPORTED_ABI;
    if (adapter->rank <= 0 || adapter->rank > HF_NIBBLEFLOW_MAX_ADAPTER_RANK || !std::isfinite(adapter->scale)) return HF_INVALID_ARGUMENT;
    size_t expected_down = 0;
    size_t expected_up = 0;
    if (!multiply_size(static_cast<size_t>(adapter->rank), static_cast<size_t>(model->in_dim), &expected_down) || !multiply_size(static_cast<size_t>(adapter->rank), static_cast<size_t>(model->out_dim), &expected_up)) return HF_OVERFLOW;
    if (adapter->down_count != expected_down || adapter->up_count != expected_up) return HF_BUFFER_TOO_SMALL;
    if (!finite_values(adapter->down, expected_down) || !finite_values(adapter->up, expected_up)) return HF_INVALID_ARGUMENT;
    return HF_OK;
}

extern "C" hf_status hf_nibbleflow_validate_execution_plan(const hf_nibbleflow_model *model, const hf_nibbleflow_execution_plan *plan) {
    const hf_status model_status = hf_nibbleflow_validate_model(model);
    if (model_status != HF_OK) return model_status;
    if (!plan) return HF_OK;
    if (plan->abi_version != HF_NIBBLEFLOW_EXECUTION_ABI) return HF_UNSUPPORTED_ABI;
    if (plan->activation_mode != HF_NIBBLEFLOW_ACTIVATION_F32 && plan->activation_mode != HF_NIBBLEFLOW_ACTIVATION_STATIC_INT8) return HF_INVALID_ARGUMENT;
    if (plan->activation_mode == HF_NIBBLEFLOW_ACTIVATION_STATIC_INT8) {
        const hf_status calibration_status = hf_nibbleflow_validate_static_calibration(plan->calibration);
        if (calibration_status != HF_OK) return calibration_status;
        if (!plan->activation_scratch || plan->activation_scratch_count < static_cast<size_t>(model->in_dim)) return HF_BUFFER_TOO_SMALL;
    } else if (plan->calibration || plan->activation_scratch || plan->activation_scratch_count != 0) {
        return HF_INVALID_ARGUMENT;
    }
    if (plan->adapter) {
        const hf_status adapter_status = hf_nibbleflow_validate_adapter(model, plan->adapter);
        if (adapter_status != HF_OK) return adapter_status;
        if (!plan->adapter_scratch || plan->adapter_scratch_count < static_cast<size_t>(plan->adapter->rank)) return HF_BUFFER_TOO_SMALL;
    } else if (plan->adapter_scratch || plan->adapter_scratch_count != 0) {
        return HF_INVALID_ARGUMENT;
    }
    return HF_OK;
}

static int8_t quantize_static_int8(float value, const hf_nibbleflow_static_calibration *calibration) {
    long quantized = std::lround(static_cast<double>(value) / static_cast<double>(calibration->activation_scale)) + calibration->activation_zero_point;
    if (quantized < -128) quantized = -128;
    if (quantized > 127) quantized = 127;
    return static_cast<int8_t>(quantized);
}

static void apply_adapter(const hf_nibbleflow_model *model, const hf_nibbleflow_adapter *adapter, const float *input, float *output, float *scratch) {
    const size_t input_count = static_cast<size_t>(model->in_dim);
    const size_t output_count = static_cast<size_t>(model->out_dim);
    const size_t rank = static_cast<size_t>(adapter->rank);
    for (size_t latent = 0; latent < rank; ++latent) {
        float total = 0.0f;
        const float *row = adapter->down + latent * input_count;
        for (size_t index = 0; index < input_count; ++index) total += row[index] * input[index];
        scratch[latent] = total;
    }
    for (size_t output_index = 0; output_index < output_count; ++output_index) {
        float total = 0.0f;
        const float *row = adapter->up + output_index * rank;
        for (size_t latent = 0; latent < rank; ++latent) total += row[latent] * scratch[latent];
        output[output_index] += adapter->scale * total;
    }
}

extern "C" hf_status hf_nibbleflow_matvec_ex(const hf_nibbleflow_model *model, const hf_nibbleflow_execution_plan *plan, const float *input, size_t input_count, float *output, size_t output_count) {
    const hf_status model_status = hf_nibbleflow_validate_model(model);
    if (model_status != HF_OK) return model_status;
    const hf_status plan_status = hf_nibbleflow_validate_execution_plan(model, plan);
    if (plan_status != HF_OK) return plan_status;
    if (!input || !output) return HF_INVALID_ARGUMENT;
    if (input_count < static_cast<size_t>(model->in_dim) || output_count < static_cast<size_t>(model->out_dim)) return HF_BUFFER_TOO_SMALL;
    if (!finite_values(input, static_cast<size_t>(model->in_dim))) return HF_INVALID_ARGUMENT;
    if (!plan || plan->activation_mode == HF_NIBBLEFLOW_ACTIVATION_F32) {
        nibbleflow_int4_f32(input, model->packed, model->scales, model->bias, output, model->in_dim, model->out_dim, model->group_size);
    } else {
        for (size_t index = 0; index < static_cast<size_t>(model->in_dim); ++index) plan->activation_scratch[index] = quantize_static_int8(input[index], plan->calibration);
        nibbleflow_int4_i8_f32(plan->activation_scratch, plan->calibration->activation_scale, plan->calibration->activation_zero_point, model->packed, model->scales, model->bias, output, model->in_dim, model->out_dim, model->group_size);
    }
    if (plan && plan->adapter) apply_adapter(model, plan->adapter, input, output, plan->adapter_scratch);
    return finite_values(output, static_cast<size_t>(model->out_dim)) ? HF_OK : HF_KERNEL_FAILURE;
}

extern "C" hf_status hf_nibbleflow_matvec(const hf_nibbleflow_model *model, const float *input, size_t input_count, float *output, size_t output_count) {
    return hf_nibbleflow_matvec_ex(model, nullptr, input, input_count, output, output_count);
}

extern "C" const char *hf_status_string(hf_status status) {
    switch (status) {
        case HF_OK: return "ok";
        case HF_INVALID_ARGUMENT: return "invalid_argument";
        case HF_BUFFER_TOO_SMALL: return "buffer_too_small";
        case HF_UNSUPPORTED_ABI: return "unsupported_abi";
        case HF_OVERFLOW: return "overflow";
        case HF_KERNEL_FAILURE: return "kernel_failure";
        case HF_CANCELLED: return "cancelled";
        case HF_DEADLINE_MISSED: return "deadline_missed";
        case HF_TIMEOUT: return "timeout";
        default: return "unknown";
    }
}
