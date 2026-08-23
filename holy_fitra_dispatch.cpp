#include "holy_fitra_dispatch.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <random>
#include <thread>

#if defined(__linux__)
#include <pthread.h>
#include <sched.h>
#endif

namespace holyfitra {

uint64_t monotonic_time_ns() {
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());
}

const char *submit_status_string(SubmitStatus status) {
    switch (status) {
        case SubmitStatus::Accepted: return "accepted";
        case SubmitStatus::Backpressure: return "backpressure";
        case SubmitStatus::Stopped: return "stopped";
        case SubmitStatus::Rejected: return "rejected";
    }
    return "unknown";
}

namespace {

class WorkDeque {
public:
    explicit WorkDeque(size_t capacity) : capacity_(capacity) {}

    bool push(Task task) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (items_.size() >= capacity_) return false;
        items_.push_back(std::move(task));
        return true;
    }

    static bool higher_priority(const Task &left, const Task &right) {
        const int left_priority = static_cast<int>(left.priority);
        const int right_priority = static_cast<int>(right.priority);
        if (left_priority != right_priority) return left_priority > right_priority;
        // A non-zero deadline outranks an untimed task; among timed tasks the
        // earliest deadline wins. Sequence order breaks remaining ties.
        if ((left.deadline_ns != 0) != (right.deadline_ns != 0)) return left.deadline_ns != 0;
        if (left.deadline_ns != 0 && left.deadline_ns != right.deadline_ns) return left.deadline_ns < right.deadline_ns;
        return left.sequence > right.sequence;
    }

    bool pop_owner(Task &out, const std::function<bool(const Task &)> &allowed) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto best = items_.end();
        for (auto it = items_.begin(); it != items_.end(); ++it) {
            if (allowed(*it) && (best == items_.end() || higher_priority(*it, *best))) best = it;
        }
        if (best == items_.end()) return false;
        out = std::move(*best);
        items_.erase(best);
        return true;
    }

    bool steal(Task &out, const std::function<bool(const Task &)> &allowed) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto best = items_.end();
        for (auto it = items_.begin(); it != items_.end(); ++it) {
            if (allowed(*it) && (best == items_.end() || higher_priority(*it, *best))) best = it;
        }
        if (best == items_.end()) return false;
        out = std::move(*best);
        items_.erase(best);
        return true;
    }

    size_t size() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return items_.size();
    }

    void drain(std::vector<Task> &out) {
        std::lock_guard<std::mutex> lock(mutex_);
        while (!items_.empty()) {
            out.push_back(std::move(items_.front()));
            items_.pop_front();
        }
    }

private:
    size_t capacity_;
    mutable std::mutex mutex_;
    std::deque<Task> items_;
};

} // namespace

struct Scheduler::Impl {
    struct Worker {
        int id;
        bool big;
        WorkDeque queue;
        std::thread thread;
        WorkerStats stats;
        Worker(int worker_id, bool is_big, size_t capacity) : id(worker_id), big(is_big), queue(capacity) {}
    };

    SchedulerConfig config;
    std::vector<std::unique_ptr<Worker>> workers;
    std::atomic<bool> stop{false};
    std::atomic<ThermalState> thermal{ThermalState::Normal};
    std::atomic<uint64_t> sequence{0};
    std::atomic<uint64_t> submitted{0};
    std::atomic<uint64_t> completed{0};
    std::atomic<uint64_t> cancelled{0};
    std::atomic<uint64_t> deadline_missed{0};
    std::atomic<uint64_t> rejected{0};
    std::atomic<uint64_t> stolen{0};
    mutable std::mutex wake_mutex;
    std::mutex lifecycle_mutex;
    std::condition_variable wake_cv;

    explicit Impl(SchedulerConfig scheduler_config) : config(std::move(scheduler_config)) {
        int little = config.little_workers;
        int big = config.big_workers;
        if (little <= 0 && big <= 0) {
            const unsigned hardware = std::max(2u, std::thread::hardware_concurrency());
            little = static_cast<int>(std::max(1u, hardware > 2 ? hardware - 2 : 1));
            big = 1;
        }
        int id = 0;
        for (int i = 0; i < little; ++i) workers.emplace_back(new Worker(id++, false, config.queue_capacity));
        for (int i = 0; i < big; ++i) workers.emplace_back(new Worker(id++, true, config.queue_capacity));
        for (auto &worker : workers) worker->thread = std::thread([this, raw = worker.get()] { worker_loop(*raw); });
    }

    bool thermal_allows(const Worker &worker, const Task &task) const {
        const ThermalState state = thermal.load(std::memory_order_acquire);
        if (state == ThermalState::Critical && worker.big) return false;
        switch (task.core_class) {
            case CoreClass::Any: return true;
            case CoreClass::BigOnly: return worker.big && state != ThermalState::Critical;
            case CoreClass::LittleOnly: return !worker.big;
            case CoreClass::BigPreferred: return worker.big || state == ThermalState::Critical;
            case CoreClass::LittlePreferred: return !worker.big || state == ThermalState::Hot || state == ThermalState::Critical;
        }
        return true;
    }

    bool can_take(const Worker &worker, const Task &task) const {
        if (!thermal_allows(worker, task)) return false;
        if (task.cancellation && task.cancellation->is_cancelled()) return true;
        return true;
    }

    bool has_compatible_work(const Worker &worker) const {
        for (const auto &candidate : workers) {
            if (candidate->queue.size() == 0) continue;
            // A non-empty compatible queue is sufficient; exact inspection is
            // deferred to pop to keep the wake predicate inexpensive.
            if (!worker.big || thermal.load(std::memory_order_acquire) != ThermalState::Critical) return true;
        }
        return false;
    }

    bool take_task(Worker &worker, Task &task) {
        const auto allowed = [this, &worker](const Task &candidate) { return can_take(worker, candidate); };
        if (worker.queue.pop_owner(task, allowed)) return true;
        const size_t count = workers.size();
        if (count <= 1) return false;
        const size_t start = (static_cast<size_t>(worker.id) + 1u) % count;
        for (size_t offset = 0; offset < count - 1; ++offset) {
            Worker &victim = *workers[(start + offset) % count];
            if (victim.queue.steal(task, allowed)) {
                ++worker.stats.stolen;
                stolen.fetch_add(1, std::memory_order_relaxed);
                return true;
            }
        }
        return false;
    }

    void pin_worker(const Worker &worker) {
#if defined(__linux__)
        if (!config.pin_threads) return;
        const std::vector<int> &cpus = worker.big ? config.big_cpus : config.little_cpus;
        if (cpus.empty()) return;
        cpu_set_t set;
        CPU_ZERO(&set);
        CPU_SET(cpus[static_cast<size_t>(worker.id) % cpus.size()], &set);
#if defined(__ANDROID__)
        // Bionic does not expose pthread_setaffinity_np in the API-level
        // headers used by this library. Pin the calling worker thread through
        // sched_setaffinity(0, ...), which Android supports for this purpose.
        (void)sched_setaffinity(0, sizeof(set), &set);
#else
        (void)pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
#endif
#else
        (void)worker;
#endif
    }

    void worker_loop(Worker &worker) {
        pin_worker(worker);
        while (!stop.load(std::memory_order_acquire)) {
            Task task;
            if (!take_task(worker, task)) {
                std::unique_lock<std::mutex> lock(wake_mutex);
                wake_cv.wait_for(lock, std::chrono::milliseconds(2), [this, &worker] {
                    return stop.load(std::memory_order_acquire) || has_compatible_work(worker);
                });
                continue;
            }
            if (task.cancellation && task.cancellation->is_cancelled()) {
                ++worker.stats.cancelled;
                cancelled.fetch_add(1, std::memory_order_relaxed);
                if (task.on_cancel) {
                    TaskContext context;
                    context.worker_id = worker.id;
                    context.on_big_core = worker.big;
                    context.cancellation = task.cancellation;
                    task.on_cancel(context);
                }
                continue;
            }
            if (task.deadline_ns != 0 && monotonic_time_ns() > task.deadline_ns) {
                ++worker.stats.deadline_missed;
                deadline_missed.fetch_add(1, std::memory_order_relaxed);
                if (task.on_deadline_missed) {
                    TaskContext context;
                    context.worker_id = worker.id;
                    context.on_big_core = worker.big;
                    context.cancellation = task.cancellation;
                    task.on_deadline_missed(context);
                }
                continue;
            }
            TaskContext context;
            context.worker_id = worker.id;
            context.on_big_core = worker.big;
            context.cancellation = task.cancellation;
            try {
                task.function(context);
                ++worker.stats.executed;
                completed.fetch_add(1, std::memory_order_relaxed);
            } catch (...) {
                // A task exception must not strand an owning request. The
                // callback is deliberately best-effort and cannot kill a worker.
                if (task.on_failure) {
                    try {
                        task.on_failure(context);
                    } catch (...) {
                    }
                }
            }
        }
    }

    SubmitStatus submit(Task task) {
        std::lock_guard<std::mutex> lifecycle_lock(lifecycle_mutex);
        if (stop.load(std::memory_order_acquire)) {
            rejected.fetch_add(1, std::memory_order_relaxed);
            return SubmitStatus::Stopped;
        }
        if (!task.function) {
            rejected.fetch_add(1, std::memory_order_relaxed);
            return SubmitStatus::Rejected;
        }
        if (task.deadline_ns != 0 && task.deadline_ns <= monotonic_time_ns()) {
            rejected.fetch_add(1, std::memory_order_relaxed);
            return SubmitStatus::Rejected;
        }
        if (thermal.load(std::memory_order_acquire) == ThermalState::Critical && task.core_class == CoreClass::BigOnly) {
            rejected.fetch_add(1, std::memory_order_relaxed);
            return SubmitStatus::Rejected;
        }
        task.sequence = sequence.fetch_add(1, std::memory_order_relaxed);
        Worker *best = nullptr;
        int best_penalty = 0;
        size_t best_queue = 0;
        const ThermalState current_thermal = thermal.load(std::memory_order_acquire);
        for (auto &candidate_worker : workers) {
            Worker *worker = candidate_worker.get();
            if (task.core_class == CoreClass::BigOnly && !worker->big) continue;
            if (task.core_class == CoreClass::LittleOnly && worker->big) continue;
            if (worker->big && current_thermal == ThermalState::Critical) continue;
            const int penalty = task.core_class == CoreClass::BigPreferred ? (worker->big ? 0 : 1) : (task.core_class == CoreClass::LittlePreferred ? (worker->big ? 1 : 0) : 0);
            const size_t queue_size = worker->queue.size();
            if (!best || penalty < best_penalty || (penalty == best_penalty && queue_size < best_queue)) {
                best = worker;
                best_penalty = penalty;
                best_queue = queue_size;
            }
        }
        if (!best) {
            rejected.fetch_add(1, std::memory_order_relaxed);
            return SubmitStatus::Rejected;
        }
        if (!best->queue.push(std::move(task))) {
            rejected.fetch_add(1, std::memory_order_relaxed);
            return SubmitStatus::Backpressure;
        }
        submitted.fetch_add(1, std::memory_order_relaxed);
        wake_cv.notify_all();
        return SubmitStatus::Accepted;
    }

    void set_thermal_state(ThermalState state) {
        thermal.store(state, std::memory_order_release);
        wake_cv.notify_all();
    }

    SchedulerStats stats() const {
        size_t queued = 0;
        for (const auto &worker : workers) queued += worker->queue.size();
        return {submitted.load(), completed.load(), cancelled.load(), deadline_missed.load(), rejected.load(), stolen.load(), queued};
    }

    void shutdown() {
        std::lock_guard<std::mutex> lifecycle_lock(lifecycle_mutex);
        bool expected = false;
        if (!stop.compare_exchange_strong(expected, true)) return;
        wake_cv.notify_all();
        for (auto &worker : workers) if (worker->thread.joinable()) worker->thread.join();
        for (auto &worker : workers) {
            std::vector<Task> pending;
            worker->queue.drain(pending);
            for (Task &task : pending) {
                ++worker->stats.cancelled;
                cancelled.fetch_add(1, std::memory_order_relaxed);
                if (!task.on_cancel) continue;
                TaskContext context;
                context.worker_id = worker->id;
                context.on_big_core = worker->big;
                context.cancellation = task.cancellation;
                try {
                    task.on_cancel(context);
                } catch (...) {
                }
            }
        }
    }
};

Scheduler::Scheduler(SchedulerConfig config) : impl_(new Impl(std::move(config))) {}
Scheduler::~Scheduler() { shutdown(); }
SubmitStatus Scheduler::submit(Task task) { return impl_->submit(std::move(task)); }
void Scheduler::set_thermal_state(ThermalState state) { impl_->set_thermal_state(state); }
ThermalState Scheduler::thermal_state() const { return impl_->thermal.load(std::memory_order_acquire); }
void Scheduler::shutdown() { impl_->shutdown(); }
SchedulerStats Scheduler::stats() const { return impl_->stats(); }
std::vector<WorkerStats> Scheduler::worker_stats() const {
    std::vector<WorkerStats> result;
    for (const auto &worker : impl_->workers) result.push_back(worker->stats);
    return result;
}

} // namespace holyfitra
