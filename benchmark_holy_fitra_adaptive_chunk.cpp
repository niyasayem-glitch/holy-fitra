#include "holy_fitra_ragged_scheduler.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>

static double run_case(bool adaptive, const hf_ragged_attention_batch &batch, holyfitra::Scheduler &scheduler) {
    holyfitra::RaggedDispatchPlan plan;
    plan.kernel = holyfitra::RaggedKernelKind::Neon;
    plan.core_class = holyfitra::CoreClass::Any;
    plan.priority = holyfitra::Priority::Throughput;
    plan.sequences_per_task = 4;
    plan.adaptive_chunking = adaptive;
    plan.target_work_per_task = 30000;
    const auto start = std::chrono::steady_clock::now();
    auto request = holyfitra::submit_ragged_attention(scheduler, batch, plan);
    if (!request || request->wait(60000) != holyfitra::RaggedWaitStatus::Completed) return -1.0;
    const auto end = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(end - start).count();
}

int main() {
    const int32_t d_model = 16;
    const int32_t lengths[] = {2, 3, 4, 8, 16, 32, 48, 64, 96, 128, 160, 192};
    const int32_t count = sizeof(lengths) / sizeof(lengths[0]);
    int32_t offsets[count + 1] = {0};
    for (int32_t i = 0; i < count; ++i) offsets[i + 1] = offsets[i] + lengths[i];
    const size_t elements = static_cast<size_t>(offsets[count]) * d_model;
    std::vector<float> q(elements, 0.01f), k(elements, 0.02f), v(elements, 0.03f), output(elements, 0.0f);
    hf_ragged_attention_batch batch{q.data(), q.size(), k.data(), k.size(), v.data(), v.size(), output.data(), output.size(), offsets, static_cast<size_t>(count) + 1u, count, d_model};
    holyfitra::SchedulerConfig config;
    config.little_workers = 2;
    config.big_workers = 2;
    config.queue_capacity = 64;
    holyfitra::Scheduler scheduler(config);
    double fixed = 0.0;
    double adaptive = 0.0;
    for (int i = 0; i < 5; ++i) fixed += run_case(false, batch, scheduler);
    for (int i = 0; i < 5; ++i) adaptive += run_case(true, batch, scheduler);
    scheduler.shutdown();
    std::cout << "{\"fixed_mean_ms\":" << fixed / 5.0 << ",\"adaptive_mean_ms\":" << adaptive / 5.0 << "}\n";
    return 0;
}
