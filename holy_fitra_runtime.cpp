#include "holy_fitra_runtime.h"
#include "holy_fitra_android_topology.h"

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
    hf_status result = HF_KERNEL_FAILURE;
    std::shared_ptr<holyfitra::CancellationToken> cancellation = std::make_shared<holyfitra::CancellationToken>();
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
        hf_status result = context.cancelled() ? HF_CANCELLED : hf_nibbleflow_matvec(&runtime->model, input, input_count, output, output_count);
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            state->result = result;
            state->done = true;
        }
        state->condition.notify_all();
    };
    task.on_cancel = [state](holyfitra::TaskContext &) {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->result = HF_CANCELLED;
        state->done = true;
        state->condition.notify_all();
    };
    task.on_deadline_missed = [state](holyfitra::TaskContext &) {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->result = HF_DEADLINE_MISSED;
        state->done = true;
        state->condition.notify_all();
    };
    const SubmitStatus status = runtime->scheduler->submit(std::move(task));
    if (status == SubmitStatus::Backpressure) {
        delete state;
        return HF_BUFFER_TOO_SMALL;
    }
    if (status == SubmitStatus::Stopped || status == SubmitStatus::Rejected) {
        delete state;
        return HF_KERNEL_FAILURE;
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
    Task task;
    task.core_class = to_core_class(core_class);
    task.priority = to_priority(priority);
    task.deadline_ns = deadline_ns;
    task.cancellation = state->cancellation;
    task.function = [runtime, input, batch_count, input_stride, output, output_stride, state](holyfitra::TaskContext &context) {
        hf_status result = HF_OK;
        for (size_t index = 0; index < batch_count; ++index) {
            if (context.cancelled()) {
                result = HF_CANCELLED;
                break;
            }
            if (context.deadline_ns != 0 && holyfitra::monotonic_time_ns() > context.deadline_ns) {
                result = HF_DEADLINE_MISSED;
                break;
            }
            result = hf_nibbleflow_matvec(&runtime->model, input + index * input_stride, input_stride, output + index * output_stride, output_stride);
            if (result != HF_OK) break;
        }
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            state->result = result;
            state->done = true;
        }
        state->condition.notify_all();
    };
    task.on_cancel = [state](holyfitra::TaskContext &) {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->result = HF_CANCELLED;
        state->done = true;
        state->condition.notify_all();
    };
    task.on_deadline_missed = [state](holyfitra::TaskContext &) {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->result = HF_DEADLINE_MISSED;
        state->done = true;
        state->condition.notify_all();
    };
    const SubmitStatus status = runtime->scheduler->submit(std::move(task));
    if (status == SubmitStatus::Backpressure) {
        delete state;
        return HF_BUFFER_TOO_SMALL;
    }
    if (status == SubmitStatus::Stopped || status == SubmitStatus::Rejected) {
        delete state;
        return HF_KERNEL_FAILURE;
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
