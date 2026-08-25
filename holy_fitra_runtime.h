#ifndef HOLY_FITRA_RUNTIME_H
#define HOLY_FITRA_RUNTIME_H

#include "holy_fitra_dispatch.h"
#include "nibbleflow_android.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct hf_holyfitra_runtime hf_holyfitra_runtime;
typedef struct hf_runtime_request hf_runtime_request;

typedef struct hf_runtime_stats {
    uint64_t submitted;
    uint64_t completed;
    uint64_t cancelled;
    uint64_t deadline_missed;
    uint64_t rejected;
    uint64_t stolen;
    size_t queued;
    int has_neon;
    uint32_t abi_version;
} hf_runtime_stats;

// Host-local request accounting inspired by Taskflow's task visibility model.
// It records scheduler range outcomes, not hardware-core use or device metrics.
#define HF_RUNTIME_BATCH_RECEIPT_ABI 1u
typedef struct hf_runtime_batch_receipt {
    uint32_t abi_version;
    uint64_t row_count;
    uint64_t planned_ranges;
    uint64_t admitted_ranges;
    uint64_t completed_ranges;
    uint64_t cancelled_ranges;
    uint64_t deadline_missed_ranges;
    uint64_t failed_ranges;
    uint64_t rejected_ranges;
} hf_runtime_batch_receipt;

enum hf_runtime_core_class {
    HF_RUNTIME_CORE_ANY = 0,
    HF_RUNTIME_CORE_BIG_ONLY = 1,
    HF_RUNTIME_CORE_LITTLE_ONLY = 2,
    HF_RUNTIME_CORE_BIG_PREFERRED = 3,
    HF_RUNTIME_CORE_LITTLE_PREFERRED = 4
};

enum hf_runtime_priority {
    HF_RUNTIME_PRIORITY_BACKGROUND = 0,
    HF_RUNTIME_PRIORITY_THROUGHPUT = 1,
    HF_RUNTIME_PRIORITY_LATENCY = 2,
    HF_RUNTIME_PRIORITY_INTERACTIVE = 3
};

uint32_t hf_runtime_abi(void);
hf_holyfitra_runtime *hf_runtime_create(const hf_nibbleflow_model *model, size_t queue_capacity, int pin_threads);
void hf_runtime_destroy(hf_holyfitra_runtime *runtime);
hf_status hf_runtime_submit_matvec(hf_holyfitra_runtime *runtime, const float *input, size_t input_count, float *output, size_t output_count, int core_class, int priority, uint64_t deadline_ns, hf_runtime_request **request);
hf_status hf_runtime_submit_matvec_batch(hf_holyfitra_runtime *runtime, const float *input, size_t batch_count, size_t input_stride, float *output, size_t output_stride, int core_class, int priority, uint64_t deadline_ns, hf_runtime_request **request);
hf_status hf_runtime_wait(hf_runtime_request *request, uint64_t timeout_ms);
void hf_runtime_cancel(hf_runtime_request *request);
void hf_runtime_request_destroy(hf_runtime_request *request);
hf_status hf_runtime_get_batch_receipt(const hf_runtime_request *request, hf_runtime_batch_receipt *receipt);
void hf_runtime_set_thermal(hf_holyfitra_runtime *runtime, int thermal_state);
hf_runtime_stats hf_runtime_get_stats(const hf_holyfitra_runtime *runtime);
const char *hf_runtime_status_string(hf_status status);

#ifdef __cplusplus
}
#endif

#endif
