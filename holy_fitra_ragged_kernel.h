#ifndef HOLY_FITRA_RAGGED_KERNEL_H
#define HOLY_FITRA_RAGGED_KERNEL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct hf_ragged_attention_batch {
    const float *q;
    uint64_t q_elements;
    const float *k;
    uint64_t k_elements;
    const float *v;
    uint64_t v_elements;
    float *output;
    uint64_t output_elements;
    const int32_t *offsets;
    uint64_t offsets_count;
    int32_t sequence_count;
    int32_t d_model;
} hf_ragged_attention_batch;

/*
 * All element counts are capacities, not logical lengths. Kernels reject null
 * pointers, invalid offsets, and any checked token*d_model extent that exceeds
 * a capacity before doing pointer arithmetic. Callers must keep buffers alive
 * until the corresponding scheduler request reaches a terminal state.
 */

int hf_validate_ragged_batch(const hf_ragged_attention_batch *batch);
void holy_fitra_ragged_attention_scalar(const hf_ragged_attention_batch *batch);
void holy_fitra_ragged_attention_neon(const hf_ragged_attention_batch *batch);
void holy_fitra_ragged_attention_sve(const hf_ragged_attention_batch *batch);

#ifdef __cplusplus
}
#endif

#endif
