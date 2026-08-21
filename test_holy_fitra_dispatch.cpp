#include "holy_fitra_dispatch.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

using namespace holyfitra;

int main() {
    {
        Scheduler scheduler(SchedulerConfig{2, 1, 64, false, {}, {}});
        std::atomic<int> completed{0};
        for (int i = 0; i < 240; ++i) {
            Task task;
            task.priority = (i % 12 == 0) ? Priority::Interactive : Priority::Throughput;
            task.core_class = (i % 5 == 0) ? CoreClass::BigPreferred : CoreClass::Any;
            task.function = [&completed](TaskContext &context) {
                if (!context.cancelled()) completed.fetch_add(1, std::memory_order_relaxed);
            };
            SubmitStatus status;
            do {
                status = scheduler.submit(task);
                if (status == SubmitStatus::Backpressure) std::this_thread::yield();
            } while (status == SubmitStatus::Backpressure);
            assert(status == SubmitStatus::Accepted);
        }
        auto cancelled_token = std::make_shared<CancellationToken>();
        cancelled_token->cancel();
        Task cancelled;
        cancelled.cancellation = cancelled_token;
        cancelled.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(cancelled)) == SubmitStatus::Accepted);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        scheduler.shutdown();
        const SchedulerStats stats = scheduler.stats();
        assert(completed.load() == 240);
        assert(stats.completed == 240);
        assert(stats.cancelled >= 1);
        assert(stats.queued == 0);
    }

    {
        Scheduler scheduler(SchedulerConfig{1, 1, 4, false, {}, {}});
        scheduler.set_thermal_state(ThermalState::Critical);
        Task strict_big;
        strict_big.core_class = CoreClass::BigOnly;
        strict_big.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(strict_big)) == SubmitStatus::Rejected);
        Task preferred_big;
        preferred_big.core_class = CoreClass::BigPreferred;
        preferred_big.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(preferred_big)) == SubmitStatus::Accepted);
        scheduler.shutdown();
    }

    {
        Scheduler scheduler(SchedulerConfig{1, 0, 1, false, {}, {}});
        Task expired;
        expired.deadline_ns = monotonic_time_ns() - 1;
        expired.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(expired)) == SubmitStatus::Rejected);
        scheduler.shutdown();
    }

    {
        Scheduler scheduler(SchedulerConfig{1, 0, 1, false, {}, {}});
        std::mutex mutex;
        std::condition_variable condition;
        bool release = false;
        Task blocking;
        blocking.function = [&](TaskContext &) {
            std::unique_lock<std::mutex> lock(mutex);
            condition.wait(lock, [&] { return release; });
        };
        assert(scheduler.submit(std::move(blocking)) == SubmitStatus::Accepted);
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        Task queued;
        queued.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(queued)) == SubmitStatus::Accepted);
        Task overflow;
        overflow.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(overflow)) == SubmitStatus::Backpressure);
        {
            std::lock_guard<std::mutex> lock(mutex);
            release = true;
        }
        condition.notify_all();
        scheduler.shutdown();
    }

    return 0;
}
