#include "holy_fitra_runtime.h"
#include <cassert>
#include <cstdint>
#include <cmath>
#include <vector>

int main() {
    const int in_dim = 5;
    const int out_dim = 3;
    const int group_size = 2;
    const size_t batch = 16;
    const size_t input_stride = 8;
    const size_t output_stride = 5;
    std::vector<uint8_t> packed(12, 0);
    std::vector<float> scales(12, 1.0f);
    std::vector<float> bias(out_dim, 0.0f);
    std::vector<float> input(batch * input_stride, 0.0f);
    std::vector<float> output(batch * output_stride, -1.0f);
    std::vector<float> baseline(batch * output_stride, -2.0f);
    hf_nibbleflow_model model{packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(), in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()};
    hf_holyfitra_runtime *runtime = hf_runtime_create(&model, 64, 0);
    assert(runtime != nullptr);

    for (size_t row = 0; row < batch; ++row) {
        for (int col = 0; col < in_dim; ++col) input[row * input_stride + static_cast<size_t>(col)] = static_cast<float>(row + col);
        hf_runtime_request *request = nullptr;
        assert(hf_runtime_submit_matvec(runtime, input.data() + row * input_stride, input_stride, baseline.data() + row * output_stride, output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &request) == HF_OK);
        assert(hf_runtime_wait(request, 1000) == HF_OK);
        hf_runtime_request_destroy(request);
    }

    hf_runtime_request *batch_request = nullptr;
    const hf_runtime_stats before_parallel_batch = hf_runtime_get_stats(runtime);
    assert(hf_runtime_submit_matvec_batch(runtime, input.data(), batch, input_stride, output.data(), output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &batch_request) == HF_OK);
    assert(hf_runtime_wait(batch_request, 1000) == HF_OK);
    const hf_runtime_stats after_parallel_batch = hf_runtime_get_stats(runtime);
    // The host scheduler exposes at least two workers for this 16-row request,
    // proving that the public batch handle now completes multiple bounded ranges.
    assert(after_parallel_batch.completed >= before_parallel_batch.completed + 2);
    hf_runtime_batch_receipt parallel_receipt{};
    assert(hf_runtime_get_batch_receipt(batch_request, &parallel_receipt) == HF_OK);
    assert(parallel_receipt.abi_version == HF_RUNTIME_BATCH_RECEIPT_ABI);
    assert(parallel_receipt.row_count == batch);
    assert(parallel_receipt.planned_ranges >= 2);
    assert(parallel_receipt.admitted_ranges == parallel_receipt.planned_ranges);
    assert(parallel_receipt.completed_ranges == parallel_receipt.planned_ranges);
    assert(parallel_receipt.cancelled_ranges == 0);
    assert(parallel_receipt.deadline_missed_ranges == 0);
    assert(parallel_receipt.failed_ranges == 0);
    assert(parallel_receipt.rejected_ranges == 0);
    hf_runtime_request_destroy(batch_request);
    for (size_t row = 0; row < batch; ++row) for (int col = 0; col < out_dim; ++col) assert(std::fabs(output[row * output_stride + static_cast<size_t>(col)] - baseline[row * output_stride + static_cast<size_t>(col)]) < 1e-6f);

    hf_runtime_request *single_row_request = nullptr;
    assert(hf_runtime_submit_matvec_batch(runtime, input.data(), 1, input_stride, output.data(), output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &single_row_request) == HF_OK);
    assert(hf_runtime_wait(single_row_request, 1000) == HF_OK);
    hf_runtime_batch_receipt single_row_receipt{};
    assert(hf_runtime_get_batch_receipt(single_row_request, &single_row_receipt) == HF_OK);
    assert(single_row_receipt.row_count == 1);
    assert(single_row_receipt.planned_ranges == 1);
    assert(single_row_receipt.admitted_ranges == 1);
    assert(single_row_receipt.completed_ranges == 1);
    hf_runtime_request_destroy(single_row_request);

    assert(hf_runtime_get_batch_receipt(nullptr, &single_row_receipt) == HF_INVALID_ARGUMENT);
    assert(hf_runtime_get_batch_receipt(nullptr, nullptr) == HF_INVALID_ARGUMENT);

    hf_runtime_request *overflow_request = nullptr;
    assert(hf_runtime_submit_matvec_batch(runtime, input.data(), SIZE_MAX, input_stride, output.data(), output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &overflow_request) == HF_OVERFLOW);
    assert(overflow_request == nullptr);
    hf_runtime_destroy(runtime);
    return 0;
}
