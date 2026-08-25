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
        bool started = false;
        bool release = false;
        Task blocking;
        blocking.function = [&](TaskContext &) {
            std::unique_lock<std::mutex> lock(mutex);
            started = true;
            condition.notify_all();
            condition.wait(lock, [&] { return release; });
        };
        assert(scheduler.submit(std::move(blocking)) == SubmitStatus::Accepted);
        {
            std::unique_lock<std::mutex> lock(mutex);
            assert(condition.wait_for(lock, std::chrono::seconds(1), [&] { return started; }));
        }
        std::atomic<int> drained{0};
        Task queued;
        queued.function = [](TaskContext &) {};
        queued.on_cancel = [&drained](TaskContext &) { drained.fetch_add(1, std::memory_order_relaxed); };
        assert(scheduler.submit(std::move(queued)) == SubmitStatus::Accepted);
        Task overflow;
        overflow.function = [](TaskContext &) {};
        assert(scheduler.submit(std::move(overflow)) == SubmitStatus::Backpressure);
        std::thread stopper([&scheduler] { scheduler.shutdown(); });
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        {
            std::lock_guard<std::mutex> lock(mutex);
            release = true;
        }
        condition.notify_all();
        stopper.join();
        assert(drained.load(std::memory_order_relaxed) == 1);
    }

    {
        Scheduler scheduler(SchedulerConfig{1, 0, 4, false, {}, {}});
        std::atomic<int> failed{0};
        std::atomic<bool> started{false};
        Task throwing;
        throwing.function = [&started](TaskContext &) { started.store(true, std::memory_order_release); throw 7; };
        throwing.on_failure = [&failed](TaskContext &) { failed.fetch_add(1, std::memory_order_relaxed); };
        assert(scheduler.submit(std::move(throwing)) == SubmitStatus::Accepted);
        while (!started.load(std::memory_order_acquire)) std::this_thread::yield();
        scheduler.shutdown();
        assert(failed.load(std::memory_order_relaxed) == 1);
    }

    {
        Scheduler scheduler(SchedulerConfig{1, 0, 8, false, {}, {}});
        std::mutex mutex;
        std::condition_variable condition;
        bool started = false;
        bool release = false;
        std::vector<int> order;
        Task blocker;
        blocker.function = [&](TaskContext &) {
            std::unique_lock<std::mutex> lock(mutex);
            started = true;
            condition.notify_all();
            condition.wait(lock, [&] { return release; });
        };
        assert(scheduler.submit(std::move(blocker)) == SubmitStatus::Accepted);
        {
            std::unique_lock<std::mutex> lock(mutex);
            assert(condition.wait_for(lock, std::chrono::seconds(1), [&] { return started; }));
        }
        const auto append = [&](int value, Priority priority, uint64_t deadline_ns) {
            Task task;
            task.priority = priority;
            task.deadline_ns = deadline_ns;
            task.function = [&, value](TaskContext &) {
                std::lock_guard<std::mutex> lock(mutex);
                order.push_back(value);
                condition.notify_all();
            };
            assert(scheduler.submit(std::move(task)) == SubmitStatus::Accepted);
        };
        const uint64_t now = monotonic_time_ns();
        append(1, Priority::Background, 0);
        append(2, Priority::Latency, now + 2000000000ull);
        append(3, Priority::Latency, now + 1000000000ull);
        append(4, Priority::Interactive, 0);
        {
            std::lock_guard<std::mutex> lock(mutex);
            release = true;
        }
        condition.notify_all();
        {
            std::unique_lock<std::mutex> lock(mutex);
            assert(condition.wait_for(lock, std::chrono::seconds(1), [&] { return order.size() == 4; }));
        }
        scheduler.shutdown();
        assert((order == std::vector<int>{4, 3, 2, 1}));
    }

    return 0;
}
