#include "holy_fitra_dispatch.h"
#include <atomic>
#include <chrono>
#include <cstdio>
#include <thread>

using namespace holyfitra;

int main() {
    Scheduler scheduler(SchedulerConfig{3, 2, 4096, false, {}, {}});
    constexpr int task_count = 20000;
    std::atomic<int> completed{0};
    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < task_count; ++i) {
        Task task;
        task.priority = (i % 20 == 0) ? Priority::Interactive : Priority::Throughput;
        task.core_class = (i % 7 == 0) ? CoreClass::BigPreferred : (i % 11 == 0 ? CoreClass::LittlePreferred : CoreClass::Any);
        task.function = [&completed](TaskContext &) {
            volatile uint32_t value = 0;
            for (int i = 0; i < 32; ++i) value = value * 33u + static_cast<uint32_t>(i);
            (void)value;
            completed.fetch_add(1, std::memory_order_relaxed);
        };
        SubmitStatus status;
        do {
            status = scheduler.submit(task);
            if (status == SubmitStatus::Backpressure) std::this_thread::yield();
        } while (status == SubmitStatus::Backpressure);
        if (status != SubmitStatus::Accepted) return 1;
    }
    while (completed.load(std::memory_order_acquire) < task_count) std::this_thread::yield();
    scheduler.shutdown();
    const auto end = std::chrono::steady_clock::now();
    const double elapsed_ms = std::chrono::duration<double, std::milli>(end - start).count();
    const SchedulerStats stats = scheduler.stats();
    const double tasks_per_second = static_cast<double>(stats.completed) / (elapsed_ms / 1000.0);
    std::printf("tasks=%d completed=%llu elapsed_ms=%.3f tasks_per_second=%.1f stolen=%llu rejected=%llu queued=%zu\n", task_count, static_cast<unsigned long long>(stats.completed), elapsed_ms, tasks_per_second, static_cast<unsigned long long>(stats.stolen), static_cast<unsigned long long>(stats.rejected), stats.queued);
    return stats.completed == static_cast<uint64_t>(task_count) && stats.queued == 0 ? 0 : 1;
}
