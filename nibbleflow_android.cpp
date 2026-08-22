#include "nibbleflow_android.h"

#include <cmath>
#include <limits>

extern "C" void nibbleflow_int4_f32(const float *, const uint8_t *, const float *, const float *, float *, int32_t, int32_t, int32_t);

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
    for (size_t index = 0; index < scale_count; ++index) {
        if (!std::isfinite(model->scales[index])) return HF_INVALID_ARGUMENT;
    }
    if (model->bias) {
        for (size_t index = 0; index < static_cast<size_t>(model->out_dim); ++index) {
            if (!std::isfinite(model->bias[index])) return HF_INVALID_ARGUMENT;
        }
    }
    return HF_OK;
}

extern "C" hf_status hf_nibbleflow_matvec(const hf_nibbleflow_model *model, const float *input, size_t input_count, float *output, size_t output_count) {
    const hf_status validation = hf_nibbleflow_validate_model(model);
    if (validation != HF_OK) return validation;
    if (!input || !output) return HF_INVALID_ARGUMENT;
    if (input_count < static_cast<size_t>(model->in_dim) || output_count < static_cast<size_t>(model->out_dim)) return HF_BUFFER_TOO_SMALL;
    nibbleflow_int4_f32(input, model->packed, model->scales, model->bias, output, model->in_dim, model->out_dim, model->group_size);
    return HF_OK;
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
