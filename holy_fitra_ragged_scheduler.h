#ifndef HOLY_FITRA_RAGGED_SCHEDULER_H
#define HOLY_FITRA_RAGGED_SCHEDULER_H

#include "holy_fitra_dispatch.h"
#include "holy_fitra_ragged_kernel.h"
#include <cstdint>
#include <memory>

namespace holyfitra {

enum class RaggedKernelKind { Scalar, Neon, Sve };

class RaggedThermalChunkController {
public:
    explicit RaggedThermalChunkController(uint64_t base_target_work = 65536);
    void update(ThermalState state);
    uint64_t target_work() const;
    ThermalState state() const;
private:
    uint64_t base_target_work_;
    uint64_t target_work_;
    ThermalState state_ = ThermalState::Normal;
    int normal_streak_ = 0;
};

struct RaggedDispatchPlan {
    RaggedKernelKind kernel = RaggedKernelKind::Scalar;
    CoreClass core_class = CoreClass::LittlePreferred;
    Priority priority = Priority::Throughput;
    uint64_t deadline_ns = 0;
    uint64_t kv_generation = 0;
    int32_t sequences_per_task = 4;
    bool adaptive_chunking = false;
    uint64_t target_work_per_task = 65536;
    bool allow_kernel_fallback = true;
};

struct RaggedGroupState;
enum class RaggedWaitStatus { Completed, Cancelled, DeadlineMissed, Failed, Timeout };

class RaggedRequest {
public:
    explicit RaggedRequest(std::shared_ptr<RaggedGroupState> state);
    ~RaggedRequest();
    RaggedRequest(const RaggedRequest &) = delete;
    RaggedRequest &operator=(const RaggedRequest &) = delete;

    RaggedWaitStatus wait(uint64_t timeout_ms = 0);
    void cancel();
    bool done() const;

private:
    std::shared_ptr<RaggedGroupState> state_;
};

RaggedKernelKind choose_ragged_kernel(bool has_sve, bool has_neon, int32_t d_model, bool thermal_critical, bool allow_fallback);
CoreClass choose_ragged_core(RaggedKernelKind kernel, Priority priority, uint64_t estimated_work, bool thermal_critical);
int32_t choose_ragged_chunk_size(const int32_t *offsets, int32_t sequence_count, int32_t start_sequence, int32_t d_model, uint64_t target_work);
std::unique_ptr<RaggedRequest> submit_ragged_attention(Scheduler &scheduler, const hf_ragged_attention_batch &batch, const RaggedDispatchPlan &plan);
const char *ragged_kernel_name(RaggedKernelKind kind);

} // namespace holyfitra

#endif
