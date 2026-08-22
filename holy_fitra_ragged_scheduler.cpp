#include "holy_fitra_ragged_scheduler.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <vector>

namespace holyfitra {

struct RaggedGroupState {
    mutable std::mutex mutex;
    std::condition_variable condition;
    std::shared_ptr<CancellationToken> cancellation = std::make_shared<CancellationToken>();
    size_t remaining = 0;
    bool cancelled = false;
    bool deadline_missed = false;
    bool failed = false;

    void finish(TaskResult result) {
        std::lock_guard<std::mutex> lock(mutex);
        if (result == TaskResult::Cancelled) cancelled = true;
        if (result == TaskResult::DeadlineMissed) deadline_missed = true;
        if (result == TaskResult::Failed) failed = true;
        if (remaining > 0) --remaining;
        condition.notify_all();
    }

    void cancel() { cancellation->cancel(); }
};

RaggedThermalChunkController::RaggedThermalChunkController(uint64_t base_target_work)
    : base_target_work_(std::max<uint64_t>(4096, base_target_work)), target_work_(std::max<uint64_t>(4096, base_target_work)) {}

void RaggedThermalChunkController::update(ThermalState state) {
    state_ = state;
    if (state == ThermalState::Critical) {
        target_work_ = std::max<uint64_t>(4096, base_target_work_ / 4);
        normal_streak_ = 0;
    } else if (state == ThermalState::Hot) {
        target_work_ = std::max<uint64_t>(4096, base_target_work_ / 2);
        normal_streak_ = 0;
    } else if (state == ThermalState::Warm) {
        target_work_ = std::max<uint64_t>(4096, (base_target_work_ * 3) / 4);
        normal_streak_ = 0;
    } else {
        ++normal_streak_;
        if (normal_streak_ >= 3) {
            target_work_ = std::min<uint64_t>(base_target_work_, target_work_ + std::max<uint64_t>(4096, base_target_work_ / 8));
            normal_streak_ = 0;
        }
    }
}

uint64_t RaggedThermalChunkController::target_work() const { return target_work_; }
ThermalState RaggedThermalChunkController::state() const { return state_; }

RaggedRequest::RaggedRequest(std::shared_ptr<RaggedGroupState> state) : state_(std::move(state)) {}
RaggedRequest::~RaggedRequest() {
    cancel();
    wait(0);
}

RaggedWaitStatus RaggedRequest::wait(uint64_t timeout_ms) {
    if (!state_) return RaggedWaitStatus::Failed;
    std::unique_lock<std::mutex> lock(state_->mutex);
    const auto done = [this] { return state_->remaining == 0; };
    if (timeout_ms == 0) state_->condition.wait(lock, done);
    else if (!state_->condition.wait_for(lock, std::chrono::milliseconds(timeout_ms), done)) return RaggedWaitStatus::Timeout;
    if (state_->failed) return RaggedWaitStatus::Failed;
    if (state_->deadline_missed) return RaggedWaitStatus::DeadlineMissed;
    if (state_->cancelled) return RaggedWaitStatus::Cancelled;
    return RaggedWaitStatus::Completed;
}

void RaggedRequest::cancel() { if (state_) state_->cancel(); }
bool RaggedRequest::done() const {
    if (!state_) return true;
    std::lock_guard<std::mutex> lock(state_->mutex);
    return state_->remaining == 0;
}

RaggedKernelKind choose_ragged_kernel(bool has_sve, bool has_neon, int32_t d_model, bool thermal_critical, bool allow_fallback) {
    if (d_model <= 0) return RaggedKernelKind::Scalar;
    if (!thermal_critical && has_sve && d_model % 4 == 0) return RaggedKernelKind::Sve;
    if (has_neon && d_model % 4 == 0) return RaggedKernelKind::Neon;
    if (allow_fallback) return RaggedKernelKind::Scalar;
    return has_sve ? RaggedKernelKind::Sve : (has_neon ? RaggedKernelKind::Neon : RaggedKernelKind::Scalar);
}

CoreClass choose_ragged_core(RaggedKernelKind kernel, Priority priority, uint64_t estimated_work, bool thermal_critical) {
    if (thermal_critical) return CoreClass::LittlePreferred;
    if (priority == Priority::Interactive || kernel == RaggedKernelKind::Sve || estimated_work >= 65536) return CoreClass::BigPreferred;
    if (kernel == RaggedKernelKind::Neon && estimated_work >= 16384) return CoreClass::BigPreferred;
    return CoreClass::LittlePreferred;
}

int32_t choose_ragged_chunk_size(const int32_t *offsets, int32_t sequence_count, int32_t start_sequence, int32_t d_model, uint64_t target_work) {
    if (!offsets || sequence_count <= 0 || start_sequence < 0 || start_sequence >= sequence_count || d_model <= 0) return 1;
    if (target_work == 0) target_work = 1;
    uint64_t accumulated = 0;
    int32_t count = 0;
    for (int32_t sequence = start_sequence; sequence < sequence_count; ++sequence) {
        const int64_t length = static_cast<int64_t>(offsets[sequence + 1]) - static_cast<int64_t>(offsets[sequence]);
        if (length <= 0) break;
        const uint64_t length_u = static_cast<uint64_t>(length);
        const uint64_t width_u = static_cast<uint64_t>(d_model);
        if (length_u != 0 && length_u > UINT64_MAX / length_u) return std::max<int32_t>(1, count);
        const uint64_t square = length_u * length_u;
        if (width_u != 0 && square > UINT64_MAX / width_u) return std::max<int32_t>(1, count);
        const uint64_t work = square * width_u;
        if (work > UINT64_MAX - accumulated || (count > 0 && accumulated + work > target_work)) break;
        accumulated += work;
        ++count;
    }
    return std::max<int32_t>(1, count);
}

const char *ragged_kernel_name(RaggedKernelKind kind) {
    switch (kind) {
        case RaggedKernelKind::Sve: return "holy_fitra_ragged_attention_sve";
        case RaggedKernelKind::Neon: return "holy_fitra_ragged_attention_neon";
        default: return "holy_fitra_ragged_attention_scalar";
    }
}

static void invoke_ragged(RaggedKernelKind kind, const hf_ragged_attention_batch &batch) {
    switch (kind) {
        case RaggedKernelKind::Sve: holy_fitra_ragged_attention_sve(&batch); break;
        case RaggedKernelKind::Neon: holy_fitra_ragged_attention_neon(&batch); break;
        default: holy_fitra_ragged_attention_scalar(&batch); break;
    }
}

std::unique_ptr<RaggedRequest> submit_ragged_attention(Scheduler &scheduler, const hf_ragged_attention_batch &batch, const RaggedDispatchPlan &plan) {
    if (!hf_validate_ragged_batch(&batch) || plan.sequences_per_task <= 0 || plan.sequences_per_task > batch.sequence_count) return nullptr;
    auto state = std::make_shared<RaggedGroupState>();
    const int32_t fixed_chunk_size = std::max<int32_t>(1, plan.sequences_per_task);
    size_t chunk_count = 0;
    for (int32_t first = 0; first < batch.sequence_count;) {
        const int32_t chunk_size = plan.adaptive_chunking ? choose_ragged_chunk_size(batch.offsets, batch.sequence_count, first, batch.d_model, plan.target_work_per_task) : fixed_chunk_size;
        const int32_t safe_chunk = std::max<int32_t>(1, std::min<int32_t>(chunk_size, batch.sequence_count - first));
        const int32_t last = first + safe_chunk;
        ++chunk_count;
        first = last;
    }
    state->remaining = chunk_count;
    for (int32_t first = 0; first < batch.sequence_count;) {
        const int32_t chunk_size = plan.adaptive_chunking ? choose_ragged_chunk_size(batch.offsets, batch.sequence_count, first, batch.d_model, plan.target_work_per_task) : fixed_chunk_size;
        const int32_t safe_chunk = std::max<int32_t>(1, std::min<int32_t>(chunk_size, batch.sequence_count - first));
        const int32_t last = first + safe_chunk;
        Task task;
        auto task_finished = std::make_shared<std::atomic_bool>(false);
        task.core_class = plan.core_class;
        task.priority = plan.priority;
        task.deadline_ns = plan.deadline_ns;
        task.sequence = static_cast<uint64_t>(first);
        task.cancellation = state->cancellation;
        task.function = [batch, first, last, plan, state, task_finished](TaskContext &) {
            hf_ragged_attention_batch chunk = batch;
            chunk.sequence_count = last - first;
            // Keep global packed pointers and use the global offset subarray. The
            // kernel indexes all rows in global token coordinates, so no worker
            // task needs to allocate or construct rebased offsets.
            chunk.offsets = batch.offsets + first;
            chunk.offsets_count = static_cast<uint64_t>(last - first) + 1u;
            if (state->cancellation->is_cancelled()) {
                if (!task_finished->exchange(true)) state->finish(TaskResult::Cancelled);
                return;
            }
            try {
                invoke_ragged(plan.kernel, chunk);
                if (!task_finished->exchange(true)) state->finish(TaskResult::Completed);
            } catch (...) {
                if (!task_finished->exchange(true)) state->finish(TaskResult::Failed);
            }
        };
        task.on_cancel = [state, task_finished](TaskContext &) {
            if (!task_finished->exchange(true)) state->finish(TaskResult::Cancelled);
        };
        task.on_deadline_missed = [state, task_finished](TaskContext &) {
            if (!task_finished->exchange(true)) state->finish(TaskResult::DeadlineMissed);
        };
        task.on_failure = [state, task_finished](TaskContext &) {
            if (!task_finished->exchange(true)) state->finish(TaskResult::Failed);
        };
        const SubmitStatus status = scheduler.submit(std::move(task));
        if (status == SubmitStatus::Backpressure || status == SubmitStatus::Stopped || status == SubmitStatus::Rejected) state->finish(TaskResult::Failed);
        first = last;
    }
    return std::make_unique<RaggedRequest>(std::move(state));
}

} // namespace holyfitra
