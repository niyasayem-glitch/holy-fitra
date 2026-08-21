#ifndef HOLY_FITRA_DISPATCH_H
#define HOLY_FITRA_DISPATCH_H

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace holyfitra {

enum class CoreClass { Any, BigOnly, LittleOnly, BigPreferred, LittlePreferred };
enum class Priority : int { Background = 0, Throughput = 1, Latency = 2, Interactive = 3 };
enum class ThermalState { Normal, Warm, Hot, Critical };
enum class SubmitStatus { Accepted, Backpressure, Stopped, Rejected };

enum class TaskResult { Completed, Cancelled, DeadlineMissed, Failed };

struct CancellationToken {
    std::atomic<bool> cancelled{false};
    void cancel() { cancelled.store(true, std::memory_order_release); }
    bool is_cancelled() const { return cancelled.load(std::memory_order_acquire); }
};

struct TaskContext {
    int worker_id = -1;
    bool on_big_core = false;
    std::shared_ptr<CancellationToken> cancellation;
    bool cancelled() const { return cancellation && cancellation->is_cancelled(); }
};

using TaskFunction = std::function<void(TaskContext &)>;

struct Task {
    TaskFunction function;
    TaskFunction on_cancel;
    TaskFunction on_deadline_missed;
    CoreClass core_class = CoreClass::Any;
    Priority priority = Priority::Throughput;
    uint64_t deadline_ns = 0;
    uint64_t sequence = 0;
    std::shared_ptr<CancellationToken> cancellation;
};

struct WorkerStats {
    uint64_t executed = 0;
    uint64_t cancelled = 0;
    uint64_t deadline_missed = 0;
    uint64_t stolen = 0;
    uint64_t rejected = 0;
};

struct SchedulerConfig {
    int little_workers = 0;
    int big_workers = 0;
    size_t queue_capacity = 256;
    bool pin_threads = false;
    std::vector<int> little_cpus;
    std::vector<int> big_cpus;
};

struct SchedulerStats {
    uint64_t submitted = 0;
    uint64_t completed = 0;
    uint64_t cancelled = 0;
    uint64_t deadline_missed = 0;
    uint64_t rejected = 0;
    uint64_t stolen = 0;
    size_t queued = 0;
};

class Scheduler {
public:
    explicit Scheduler(SchedulerConfig config);
    ~Scheduler();

    Scheduler(const Scheduler &) = delete;
    Scheduler &operator=(const Scheduler &) = delete;

    SubmitStatus submit(Task task);
    void set_thermal_state(ThermalState state);
    ThermalState thermal_state() const;
    void shutdown();
    SchedulerStats stats() const;
    std::vector<WorkerStats> worker_stats() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

uint64_t monotonic_time_ns();
const char *submit_status_string(SubmitStatus status);

} // namespace holyfitra

#endif
