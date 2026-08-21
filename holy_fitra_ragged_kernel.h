#ifndef HOLY_FITRA_RAGGED_KERNEL_H
#define HOLY_FITRA_RAGGED_KERNEL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct hf_ragged_attention_batch {
    const float *q;
    const float *k;
    const float *v;
    float *output;
    const int32_t *offsets;
    int32_t sequence_count;
    int32_t d_model;
} hf_ragged_attention_batch;

void holy_fitra_ragged_attention_scalar(const hf_ragged_attention_batch *batch);
void holy_fitra_ragged_attention_neon(const hf_ragged_attention_batch *batch);
void holy_fitra_ragged_attention_sve(const hf_ragged_attention_batch *batch);

#ifdef __cplusplus
}
#endif

#endif
