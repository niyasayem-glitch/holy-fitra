#include "holy_fitra_dispatch.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <thread>
#include <vector>

int main() {
    holyfitra::SchedulerConfig config;
    config.little_workers = 2;
    config.big_workers = 2;
    config.queue_capacity = 8;
    holyfitra::Scheduler scheduler(config);
    std::atomic<uint64_t> accepted{0};
    std::atomic<uint64_t> rejected{0};
    std::atomic<uint64_t> completed{0};
    std::atomic<uint64_t> cancelled{0};
    std::atomic<uint64_t> failed{0};
    std::vector<std::thread> submitters;
    for (int worker = 0; worker < 8; ++worker) {
        submitters.emplace_back([&, worker] {
            for (int iteration = 0; iteration < 500; ++iteration) {
                holyfitra::Task task;
                task.cancellation = std::make_shared<holyfitra::CancellationToken>();
                task.function = [&, worker, iteration](holyfitra::TaskContext &) {
                    std::this_thread::sleep_for(std::chrono::microseconds(50));
                    if (((worker * 500 + iteration) % 37) == 0) throw std::runtime_error("stress failure");
                };
                task.on_cancel = [&](holyfitra::TaskContext &) { cancelled.fetch_add(1, std::memory_order_relaxed); };
                task.on_failure = [&](holyfitra::TaskContext &) { failed.fetch_add(1, std::memory_order_relaxed); };
                task.on_deadline_missed = [&](holyfitra::TaskContext &) { cancelled.fetch_add(1, std::memory_order_relaxed); };
                task.priority = static_cast<holyfitra::Priority>((worker + iteration) % 4);
                task.core_class = (iteration % 3 == 0) ? holyfitra::CoreClass::BigPreferred : holyfitra::CoreClass::Any;
                const auto status = scheduler.submit(std::move(task));
                if (status == holyfitra::SubmitStatus::Accepted) accepted.fetch_add(1, std::memory_order_relaxed);
                else rejected.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }
    std::thread thermal([&] {
        for (int iteration = 0; iteration < 100; ++iteration) {
            scheduler.set_thermal_state(static_cast<holyfitra::ThermalState>(iteration % 4));
            std::this_thread::yield();
        }
    });
    std::thread stopper([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
        scheduler.shutdown();
    });
    for (auto &thread : submitters) thread.join();
    thermal.join();
    stopper.join();
    scheduler.shutdown();
    const auto stats = scheduler.stats();
    completed.store(stats.completed, std::memory_order_relaxed);
    const uint64_t terminal = completed.load(std::memory_order_relaxed) + cancelled.load(std::memory_order_relaxed) + failed.load(std::memory_order_relaxed);
    assert(terminal == accepted.load(std::memory_order_relaxed));
    assert(stats.queued == 0);
    std::cout << "accepted=" << accepted << " rejected=" << rejected << " completed=" << completed
              << " cancelled=" << cancelled << " failed=" << failed << "\n";
    return 0;
}
