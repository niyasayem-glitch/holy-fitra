#include "holy_fitra_ragged_kernel.h"

#include <stddef.h>
#if defined(__STDC_HOSTED__) && __STDC_HOSTED__
#include <math.h>
#else
extern float sqrtf(float);
extern float expf(float);
#endif

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

#if defined(__ARM_FEATURE_SVE)
#include <arm_sve.h>
#endif

static int hf_finite(float value) {
    return value == value && value <= 3.402823466e38F && value >= -3.402823466e38F;
}

static int hf_finite_buffer(const float *values, uint64_t count) {
    for (uint64_t index = 0; index < count; ++index) if (!hf_finite(values[index])) return 0;
    return 1;
}

static float hf_dot_scalar(const float *a, const float *b, int32_t d_model) {
    float sum = 0.0f;
    for (int32_t d = 0; d < d_model; ++d) sum += a[d] * b[d];
    return sum;
}

static void hf_zero(float *output, int32_t d_model) {
    for (int32_t d = 0; d < d_model; ++d) output[d] = 0.0f;
}

int hf_validate_ragged_batch(const hf_ragged_attention_batch *batch) {
    if (!batch || !batch->q || !batch->k || !batch->v || !batch->output || !batch->offsets || batch->sequence_count <= 0 || batch->d_model <= 0) return 0;
    const uint64_t sequence_count = (uint64_t)batch->sequence_count;
    if (batch->offsets_count < sequence_count + 1u) return 0;
    int32_t previous = batch->offsets[0];
    if (previous < 0) return 0;
    for (uint64_t sequence = 0; sequence < sequence_count; ++sequence) {
        const int32_t start = batch->offsets[sequence];
        const int32_t end = batch->offsets[sequence + 1u];
        if (start < 0 || end < start || start != previous) return 0;
        previous = end;
    }
    const uint64_t total_tokens = (uint64_t)previous;
    const uint64_t width = (uint64_t)batch->d_model;
    if (width != 0 && total_tokens > UINT64_MAX / width) return 0;
    const uint64_t required_elements = total_tokens * width;
    if (required_elements > batch->q_elements || required_elements > batch->k_elements || required_elements > batch->v_elements || required_elements > batch->output_elements) return 0;
    return hf_finite_buffer(batch->q, required_elements) && hf_finite_buffer(batch->k, required_elements) && hf_finite_buffer(batch->v, required_elements);
}

void holy_fitra_ragged_attention_scalar(const hf_ragged_attention_batch *batch) {
    if (!hf_validate_ragged_batch(batch)) return;
    const float scale = 1.0f / sqrtf((float)batch->d_model);
    for (int32_t sequence = 0; sequence < batch->sequence_count; ++sequence) {
        const int32_t start = batch->offsets[sequence];
        const int32_t end = batch->offsets[sequence + 1];
        if (start < 0 || end <= start) continue;
        for (int32_t row = start; row < end; ++row) {
            float *out = batch->output + (size_t)row * (size_t)batch->d_model;
            const float *q = batch->q + (size_t)row * (size_t)batch->d_model;
            hf_zero(out, batch->d_model);
            float max_score = 0.0f;
            float normalizer = 0.0f;
            int have_max = 0;
            for (int32_t key = start; key <= row; ++key) {
                const float score = hf_dot_scalar(q, batch->k + (size_t)key * (size_t)batch->d_model, batch->d_model) * scale;
                const float new_max = (!have_max || score > max_score) ? score : max_score;
                const float old_factor = have_max ? expf(max_score - new_max) : 0.0f;
                const float new_factor = expf(score - new_max);
                for (int32_t d = 0; d < batch->d_model; ++d) {
                    out[d] = out[d] * old_factor + batch->v[(size_t)key * (size_t)batch->d_model + (size_t)d] * new_factor;
                }
                normalizer = normalizer * old_factor + new_factor;
                max_score = new_max;
                have_max = 1;
            }
            if (normalizer > 0.0f && normalizer == normalizer) for (int32_t d = 0; d < batch->d_model; ++d) out[d] /= normalizer;
        }
    }
}

#if defined(__aarch64__)
static float hf_dot_neon(const float *a, const float *b, int32_t d_model) {
    float32x4_t sum = vdupq_n_f32(0.0f);
    int32_t d = 0;
    for (; d + 4 <= d_model; d += 4) sum = vfmaq_f32(sum, vld1q_f32(a + d), vld1q_f32(b + d));
    float result = vaddvq_f32(sum);
    for (; d < d_model; ++d) result += a[d] * b[d];
    return result;
}

void holy_fitra_ragged_attention_neon(const hf_ragged_attention_batch *batch) {
    if (!hf_validate_ragged_batch(batch)) return;
    const float scale = 1.0f / sqrtf((float)batch->d_model);
    for (int32_t sequence = 0; sequence < batch->sequence_count; ++sequence) {
        const int32_t start = batch->offsets[sequence];
        const int32_t end = batch->offsets[sequence + 1];
        if (start < 0 || end <= start) continue;
        for (int32_t row = start; row < end; ++row) {
            float *out = batch->output + (size_t)row * (size_t)batch->d_model;
            const float *q = batch->q + (size_t)row * (size_t)batch->d_model;
            hf_zero(out, batch->d_model);
            float max_score = 0.0f;
            float normalizer = 0.0f;
            int have_max = 0;
            for (int32_t key = start; key <= row; ++key) {
                const float score = hf_dot_neon(q, batch->k + (size_t)key * (size_t)batch->d_model, batch->d_model) * scale;
                const float new_max = (!have_max || score > max_score) ? score : max_score;
                const float old_factor = have_max ? expf(max_score - new_max) : 0.0f;
                const float new_factor = expf(score - new_max);
                const float32x4_t old_vec = vdupq_n_f32(old_factor);
                const float32x4_t new_vec = vdupq_n_f32(new_factor);
                int32_t d = 0;
                for (; d + 4 <= batch->d_model; d += 4) {
                    float32x4_t acc = vld1q_f32(out + d);
                    float32x4_t value = vld1q_f32(batch->v + (size_t)key * (size_t)batch->d_model + (size_t)d);
                    acc = vfmaq_f32(vmulq_f32(acc, old_vec), value, new_vec);
                    vst1q_f32(out + d, acc);
                }
                for (; d < batch->d_model; ++d) out[d] = out[d] * old_factor + batch->v[(size_t)key * (size_t)batch->d_model + (size_t)d] * new_factor;
                normalizer = normalizer * old_factor + new_factor;
                max_score = new_max;
                have_max = 1;
            }
            if (normalizer > 0.0f && normalizer == normalizer) {
                const float32x4_t inv = vdupq_n_f32(1.0f / normalizer);
                int32_t d = 0;
                for (; d + 4 <= batch->d_model; d += 4) vst1q_f32(out + d, vmulq_f32(vld1q_f32(out + d), inv));
                for (; d < batch->d_model; ++d) out[d] /= normalizer;
            }
        }
    }
}
#else
void holy_fitra_ragged_attention_neon(const hf_ragged_attention_batch *batch) {
    holy_fitra_ragged_attention_scalar(batch);
}
#endif

#if defined(__ARM_FEATURE_SVE)
void holy_fitra_ragged_attention_sve(const hf_ragged_attention_batch *batch) {
    if (!hf_validate_ragged_batch(batch)) return;
    const float scale = 1.0f / sqrtf((float)batch->d_model);
    for (int32_t sequence = 0; sequence < batch->sequence_count; ++sequence) {
        const int32_t start = batch->offsets[sequence];
        const int32_t end = batch->offsets[sequence + 1];
        if (start < 0 || end <= start) continue;
        for (int32_t row = start; row < end; ++row) {
            float *out = batch->output + (size_t)row * (size_t)batch->d_model;
            const float *q = batch->q + (size_t)row * (size_t)batch->d_model;
            hf_zero(out, batch->d_model);
            float max_score = 0.0f;
            float normalizer = 0.0f;
            int have_max = 0;
            for (int32_t key = start; key <= row; ++key) {
                const float *k = batch->k + (size_t)key * (size_t)batch->d_model;
                const float *v = batch->v + (size_t)key * (size_t)batch->d_model;
                float score = 0.0f;
                int32_t d = 0;
                while (d < batch->d_model) {
                    svbool_t pg = svwhilelt_b32((uint32_t)d, (uint32_t)batch->d_model);
                    svfloat32_t qv = svld1(pg, q + d);
                    svfloat32_t kv = svld1(pg, k + d);
                    score += svaddv(pg, svmul_x(pg, qv, kv));
                    d += (int32_t)svcntw();
                }
                score *= scale;
                const float new_max = (!have_max || score > max_score) ? score : max_score;
                const float old_factor = have_max ? expf(max_score - new_max) : 0.0f;
                const float new_factor = expf(score - new_max);
                d = 0;
                while (d < batch->d_model) {
                    svbool_t pg = svwhilelt_b32((uint32_t)d, (uint32_t)batch->d_model);
                    svfloat32_t acc = svld1(pg, out + d);
                    svfloat32_t value = svld1(pg, v + d);
                    acc = svmla_x(pg, svmul_x(pg, acc, old_factor), value, new_factor);
                    svst1(pg, out + d, acc);
                    d += (int32_t)svcntw();
                }
                normalizer = normalizer * old_factor + new_factor;
                max_score = new_max;
                have_max = 1;
            }
            if (!(normalizer > 0.0f) || normalizer != normalizer) continue;
            int32_t norm_d = 0;
            while (norm_d < batch->d_model) {
                svbool_t pg = svwhilelt_b32((uint32_t)norm_d, (uint32_t)batch->d_model);
                svst1(pg, out + norm_d, svmul_x(pg, svld1(pg, out + norm_d), 1.0f / normalizer));
                norm_d += (int32_t)svcntw();
            }
        }
    }
}
#else
void holy_fitra_ragged_attention_sve(const hf_ragged_attention_batch *batch) {
    holy_fitra_ragged_attention_scalar(batch);
}
#endif
