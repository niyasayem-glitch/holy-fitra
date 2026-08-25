#include "holy_fitra_runtime.h"
#include "holy_fitra_android_topology.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>

using holyfitra::CoreClass;
using holyfitra::Priority;
using holyfitra::Scheduler;
using holyfitra::SchedulerConfig;
using holyfitra::SubmitStatus;
using holyfitra::Task;
using holyfitra::ThermalState;

struct hf_runtime_request {
    std::mutex mutex;
    std::condition_variable condition;
    bool done = false;
    hf_status result = HF_OK;
    std::shared_ptr<holyfitra::CancellationToken> cancellation = std::make_shared<holyfitra::CancellationToken>();
    size_t pending_tasks = 0;
};

struct hf_holyfitra_runtime {
    hf_nibbleflow_model model;
    std::unique_ptr<Scheduler> scheduler;
};

static bool valid_core_class(int value) {
    return value >= HF_RUNTIME_CORE_ANY && value <= HF_RUNTIME_CORE_LITTLE_PREFERRED;
}

static bool valid_priority(int value) {
    return value >= HF_RUNTIME_PRIORITY_BACKGROUND && value <= HF_RUNTIME_PRIORITY_INTERACTIVE;
}

static CoreClass to_core_class(int value) {
    switch (value) {
        case HF_RUNTIME_CORE_BIG_ONLY: return CoreClass::BigOnly;
        case HF_RUNTIME_CORE_LITTLE_ONLY: return CoreClass::LittleOnly;
        case HF_RUNTIME_CORE_BIG_PREFERRED: return CoreClass::BigPreferred;
        case HF_RUNTIME_CORE_LITTLE_PREFERRED: return CoreClass::LittlePreferred;
        default: return CoreClass::Any;
    }
}

static Priority to_priority(int value) {
    switch (value) {
        case HF_RUNTIME_PRIORITY_BACKGROUND: return Priority::Background;
        case HF_RUNTIME_PRIORITY_LATENCY: return Priority::Latency;
        case HF_RUNTIME_PRIORITY_INTERACTIVE: return Priority::Interactive;
        default: return Priority::Throughput;
    }
}

static bool valid_thermal(int value) { return value >= 0 && value <= 3; }

static ThermalState to_thermal(int value) {
    switch (value) {
        case 1: return ThermalState::Warm;
        case 2: return ThermalState::Hot;
        case 3: return ThermalState::Critical;
        default: return ThermalState::Normal;
    }
}

static int status_priority(hf_status status) {
    switch (status) {
        case HF_OK: return 0;
        case HF_CANCELLED: return 1;
        case HF_DEADLINE_MISSED: return 2;
        case HF_KERNEL_FAILURE: return 3;
        default: return 4;
    }
}

static void complete_request_task(hf_runtime_request *state, hf_status result) {
    bool notify = false;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (status_priority(result) > status_priority(state->result)) state->result = result;
        if (state->pending_tasks > 0) --state->pending_tasks;
        if (state->pending_tasks == 0 && !state->done) {
            state->done = true;
            notify = true;
        }
    }
    if (notify) state->condition.notify_all();
}

static void reserve_request_tasks(hf_runtime_request *state, size_t count) {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->pending_tasks += count;
}

static hf_status run_matvec_range(
    hf_holyfitra_runtime *runtime,
    const float *input,
    size_t start,
    size_t end,
    size_t input_stride,
    float *output,
    size_t output_stride,
    holyfitra::TaskContext &context) {
    for (size_t index = start; index < end; ++index) {
        if (context.cancelled()) return HF_CANCELLED;
        if (context.deadline_ns != 0 && holyfitra::monotonic_time_ns() > context.deadline_ns) return HF_DEADLINE_MISSED;
        const hf_status result = hf_nibbleflow_matvec(&runtime->model, input + index * input_stride, input_stride, output + index * output_stride, output_stride);
        if (result != HF_OK) return result;
    }
    return HF_OK;
}

static hf_status submit_runtime_task(hf_holyfitra_runtime *runtime, Task task, hf_runtime_request *state) {
    const SubmitStatus status = runtime->scheduler->submit(std::move(task));
    if (status == SubmitStatus::Accepted) return HF_OK;
    const hf_status result = status == SubmitStatus::Backpressure ? HF_BUFFER_TOO_SMALL : HF_KERNEL_FAILURE;
    complete_request_task(state, result);
    return result;
}

extern "C" uint32_t hf_runtime_abi(void) { return 1; }

extern "C" hf_holyfitra_runtime *hf_runtime_create(const hf_nibbleflow_model *model, size_t queue_capacity, int pin_threads) {
    if (!model || hf_nibbleflow_validate_model(model) != HF_OK) return nullptr;
    auto *runtime = new hf_holyfitra_runtime();
    runtime->model = *model;
    try {
        const auto topology = holyfitra::detect_android_topology();
        SchedulerConfig config = holyfitra::tuned_android_scheduler_config(topology, queue_capacity == 0 ? 256 : queue_capacity, pin_threads != 0);
        runtime->scheduler = std::make_unique<Scheduler>(std::move(config));
    } catch (...) {
        delete runtime;
        return nullptr;
    }
    return runtime;
}

extern "C" void hf_runtime_destroy(hf_holyfitra_runtime *runtime) {
    if (!runtime) return;
    runtime->scheduler.reset();
    delete runtime;
}

extern "C" hf_status hf_runtime_submit_matvec(hf_holyfitra_runtime *runtime, const float *input, size_t input_count, float *output, size_t output_count, int core_class, int priority, uint64_t deadline_ns, hf_runtime_request **request) {
    if (request) *request = nullptr;
    if (!request || !runtime || !runtime->scheduler || !input || !output) return HF_INVALID_ARGUMENT;
    if (!valid_core_class(core_class) || !valid_priority(priority)) return HF_INVALID_ARGUMENT;
    if (input_count < static_cast<size_t>(runtime->model.in_dim) || output_count < static_cast<size_t>(runtime->model.out_dim)) return HF_BUFFER_TOO_SMALL;
    auto *state = new hf_runtime_request();
    Task task;
    task.core_class = to_core_class(core_class);
    task.priority = to_priority(priority);
    task.deadline_ns = deadline_ns;
    task.cancellation = state->cancellation;
    task.function = [runtime, input, input_count, output, output_count, state](holyfitra::TaskContext &context) {
        complete_request_task(state, context.cancelled() ? HF_CANCELLED : hf_nibbleflow_matvec(&runtime->model, input, input_count, output, output_count));
    };
    task.on_cancel = [state](holyfitra::TaskContext &) { complete_request_task(state, HF_CANCELLED); };
    task.on_deadline_missed = [state](holyfitra::TaskContext &) { complete_request_task(state, HF_DEADLINE_MISSED); };
    task.on_failure = [state](holyfitra::TaskContext &) { complete_request_task(state, HF_KERNEL_FAILURE); };
    reserve_request_tasks(state, 1);
    const hf_status submit_result = submit_runtime_task(runtime, std::move(task), state);
    if (submit_result != HF_OK) {
        delete state;
        return submit_result;
    }
    *request = state;
    return HF_OK;
}

extern "C" hf_status hf_runtime_submit_matvec_batch(hf_holyfitra_runtime *runtime, const float *input, size_t batch_count, size_t input_stride, float *output, size_t output_stride, int core_class, int priority, uint64_t deadline_ns, hf_runtime_request **request) {
    if (request) *request = nullptr;
    if (!request || !runtime || !runtime->scheduler || !input || !output || batch_count == 0) return HF_INVALID_ARGUMENT;
    if (!valid_core_class(core_class) || !valid_priority(priority)) return HF_INVALID_ARGUMENT;
    if (input_stride < static_cast<size_t>(runtime->model.in_dim) || output_stride < static_cast<size_t>(runtime->model.out_dim)) return HF_BUFFER_TOO_SMALL;
    if (batch_count > SIZE_MAX / input_stride || batch_count > SIZE_MAX / output_stride) return HF_OVERFLOW;
    auto *state = new hf_runtime_request();

    // Independent rows share one public request while the existing scheduler
    // executes only a bounded number of contiguous ranges. Small batches retain
    // the serial shape to avoid fan-out overhead or an unproven thread claim.
    constexpr size_t kParallelBatchMinimumRows = 4;
    const size_t workers = runtime->scheduler->worker_count();
    const size_t task_count = batch_count >= kParallelBatchMinimumRows && workers > 1 ? std::min(batch_count, workers) : 1;
    const size_t base_rows = batch_count / task_count;
    const size_t remainder = batch_count % task_count;
    // Reserve all completion slots before the first range is submitted. A fast
    // first worker must not make the shared request observable as complete
    // while later ranges are still being enqueued.
    reserve_request_tasks(state, task_count);
    size_t begin = 0;
    for (size_t task_index = 0; task_index < task_count; ++task_index) {
        const size_t end = begin + base_rows + (task_index < remainder ? 1u : 0u);
        Task task;
        task.core_class = to_core_class(core_class);
        task.priority = to_priority(priority);
        task.deadline_ns = deadline_ns;
        task.cancellation = state->cancellation;
        task.function = [runtime, input, begin, end, input_stride, output, output_stride, state](holyfitra::TaskContext &context) {
            complete_request_task(state, run_matvec_range(runtime, input, begin, end, input_stride, output, output_stride, context));
        };
        task.on_cancel = [state](holyfitra::TaskContext &) { complete_request_task(state, HF_CANCELLED); };
        task.on_deadline_missed = [state](holyfitra::TaskContext &) { complete_request_task(state, HF_DEADLINE_MISSED); };
        task.on_failure = [state](holyfitra::TaskContext &) { complete_request_task(state, HF_KERNEL_FAILURE); };
        const hf_status submit_result = submit_runtime_task(runtime, std::move(task), state);
        if (submit_result != HF_OK) {
            state->cancellation->cancel();
            for (size_t unsent = task_index + 1; unsent < task_count; ++unsent) complete_request_task(state, HF_CANCELLED);
            hf_runtime_wait(state, 0);
            delete state;
            return submit_result;
        }
        begin = end;
    }
    *request = state;
    return HF_OK;
}

extern "C" hf_status hf_runtime_wait(hf_runtime_request *request, uint64_t timeout_ms) {
    if (!request) return HF_INVALID_ARGUMENT;
    std::unique_lock<std::mutex> lock(request->mutex);
    if (timeout_ms == 0) {
        request->condition.wait(lock, [request] { return request->done; });
    } else if (!request->condition.wait_for(lock, std::chrono::milliseconds(timeout_ms), [request] { return request->done; })) {
        return HF_TIMEOUT;
    }
    return request->result;
}

extern "C" void hf_runtime_cancel(hf_runtime_request *request) {
    if (request) request->cancellation->cancel();
}

extern "C" void hf_runtime_request_destroy(hf_runtime_request *request) {
    if (!request) return;
    hf_runtime_cancel(request);
    hf_runtime_wait(request, 0);
    delete request;
}

extern "C" void hf_runtime_set_thermal(hf_holyfitra_runtime *runtime, int thermal_state) {
    if (runtime && runtime->scheduler && valid_thermal(thermal_state)) runtime->scheduler->set_thermal_state(to_thermal(thermal_state));
}

extern "C" hf_runtime_stats hf_runtime_get_stats(const hf_holyfitra_runtime *runtime) {
    hf_runtime_stats result{};
    if (!runtime || !runtime->scheduler) return result;
    const auto stats = runtime->scheduler->stats();
    result.submitted = stats.submitted;
    result.completed = stats.completed;
    result.cancelled = stats.cancelled;
    result.deadline_missed = stats.deadline_missed;
    result.rejected = stats.rejected;
    result.stolen = stats.stolen;
    result.queued = stats.queued;
    result.has_neon = hf_nibbleflow_has_neon();
    result.abi_version = hf_runtime_abi();
    return result;
}

extern "C" const char *hf_runtime_status_string(hf_status status) {
    return hf_status_string(status);
}
