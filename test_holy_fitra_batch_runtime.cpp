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
    assert(hf_runtime_submit_matvec_batch(runtime, input.data(), batch, input_stride, output.data(), output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &batch_request) == HF_OK);
    assert(hf_runtime_wait(batch_request, 1000) == HF_OK);
    hf_runtime_request_destroy(batch_request);
    for (size_t row = 0; row < batch; ++row) for (int col = 0; col < out_dim; ++col) assert(std::fabs(output[row * output_stride + static_cast<size_t>(col)] - baseline[row * output_stride + static_cast<size_t>(col)]) < 1e-6f);

    hf_runtime_request *overflow_request = nullptr;
    assert(hf_runtime_submit_matvec_batch(runtime, input.data(), SIZE_MAX, input_stride, output.data(), output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &overflow_request) == HF_OVERFLOW);
    assert(overflow_request == nullptr);
    hf_runtime_destroy(runtime);
    return 0;
}
