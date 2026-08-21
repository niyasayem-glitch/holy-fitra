#include "holy_fitra_ragged_scheduler.h"
#include <cassert>
#include <cmath>
#include <vector>

static void fill(std::vector<float> &values, float offset) {
    for (size_t i = 0; i < values.size(); ++i) values[i] = offset + static_cast<float>(i % 11) * 0.01f;
}

int main() {
    const int32_t d_model = 8;
    const int32_t sequence_count = 8;
    const int32_t lengths[sequence_count] = {1, 2, 3, 5, 7, 8, 4, 6};
    int32_t offsets[sequence_count + 1] = {0};
    for (int32_t i = 0; i < sequence_count; ++i) offsets[i + 1] = offsets[i] + lengths[i];
    const size_t total = static_cast<size_t>(offsets[sequence_count]);
    std::vector<float> q(total * d_model), k(total * d_model), v(total * d_model), expected(total * d_model, 0.0f), output(total * d_model, 0.0f);
    fill(q, 0.1f); fill(k, 0.2f); fill(v, 0.3f);
    hf_ragged_attention_batch batch{q.data(), k.data(), v.data(), output.data(), offsets, sequence_count, d_model};
    hf_ragged_attention_batch reference{q.data(), k.data(), v.data(), expected.data(), offsets, sequence_count, d_model};
    holy_fitra_ragged_attention_scalar(&reference);

    holyfitra::SchedulerConfig config;
    config.little_workers = 2;
    config.big_workers = 1;
    config.queue_capacity = 32;
    holyfitra::Scheduler scheduler(config);
    holyfitra::RaggedDispatchPlan plan;
    plan.kernel = holyfitra::RaggedKernelKind::Neon;
    plan.core_class = holyfitra::CoreClass::BigPreferred;
    plan.priority = holyfitra::Priority::Throughput;
    plan.sequences_per_task = 2;
    auto request = holyfitra::submit_ragged_attention(scheduler, batch, plan);
    assert(request != nullptr);
    assert(request->wait(5000) == holyfitra::RaggedWaitStatus::Completed);
    for (size_t i = 0; i < output.size(); ++i) assert(std::fabs(output[i] - expected[i]) < 1e-5f);

    assert(holyfitra::choose_ragged_kernel(true, true, 8, false, true) == holyfitra::RaggedKernelKind::Sve);
    assert(holyfitra::choose_ragged_kernel(true, true, 8, true, true) == holyfitra::RaggedKernelKind::Neon);
    assert(holyfitra::choose_ragged_core(holyfitra::RaggedKernelKind::Sve, holyfitra::Priority::Throughput, 100000, false) == holyfitra::CoreClass::BigPreferred);
    assert(holyfitra::choose_ragged_core(holyfitra::RaggedKernelKind::Sve, holyfitra::Priority::Throughput, 100000, true) == holyfitra::CoreClass::LittlePreferred);

    holyfitra::RaggedThermalChunkController controller(65536);
    assert(controller.target_work() == 65536);
    controller.update(holyfitra::ThermalState::Hot);
    assert(controller.target_work() == 32768);
    controller.update(holyfitra::ThermalState::Critical);
    assert(controller.target_work() == 16384);
    controller.update(holyfitra::ThermalState::Normal);
    controller.update(holyfitra::ThermalState::Normal);
    assert(controller.target_work() == 16384);
    controller.update(holyfitra::ThermalState::Normal);
    assert(controller.target_work() > 16384);

    std::fill(output.begin(), output.end(), 0.0f);
    auto cancelled = holyfitra::submit_ragged_attention(scheduler, batch, plan);
    assert(cancelled != nullptr);
    cancelled->cancel();
    const auto cancelled_status = cancelled->wait(5000);
    assert(cancelled_status == holyfitra::RaggedWaitStatus::Cancelled || cancelled_status == holyfitra::RaggedWaitStatus::Completed);
    scheduler.shutdown();
    return 0;
}
