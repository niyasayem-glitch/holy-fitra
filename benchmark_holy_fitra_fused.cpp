#include "holy_fitra_runtime.h"
#include <chrono>
#include <cstdio>
#include <vector>

static double seconds_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

int main() {
    const int in_dim = 64;
    const int out_dim = 64;
    const int group_size = 8;
    const size_t batch = 2048;
    const size_t input_stride = 64;
    const size_t output_stride = 64;
    std::vector<uint8_t> packed(static_cast<size_t>(out_dim) * ((in_dim + group_size - 1) / group_size) * ((in_dim + 1) / 2), 0);
    std::vector<float> scales(static_cast<size_t>(out_dim) * ((in_dim + group_size - 1) / group_size), 1.0f);
    std::vector<float> bias(out_dim, 0.0f);
    std::vector<float> input(batch * input_stride, 1.0f);
    std::vector<float> output(batch * output_stride, 0.0f);
    hf_nibbleflow_model model{packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(), in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()};
    hf_holyfitra_runtime *runtime = hf_runtime_create(&model, 4096, 0);
    if (!runtime) return 1;

    const auto single_start = std::chrono::steady_clock::now();
    for (size_t row = 0; row < batch; ++row) {
        hf_runtime_request *request = nullptr;
        if (hf_runtime_submit_matvec(runtime, input.data() + row * input_stride, input_stride, output.data() + row * output_stride, output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &request) != HF_OK) return 2;
        if (hf_runtime_wait(request, 5000) != HF_OK) return 3;
        hf_runtime_request_destroy(request);
    }
    const double single_seconds = seconds_since(single_start);

    const auto batch_start = std::chrono::steady_clock::now();
    hf_runtime_request *batch_request = nullptr;
    if (hf_runtime_submit_matvec_batch(runtime, input.data(), batch, input_stride, output.data(), output_stride, HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_THROUGHPUT, 0, &batch_request) != HF_OK) return 4;
    if (hf_runtime_wait(batch_request, 5000) != HF_OK) return 5;
    hf_runtime_request_destroy(batch_request);
    const double batch_seconds = seconds_since(batch_start);
    std::printf("batch=%zu single_ms=%.3f fused_ms=%.3f speedup=%.2fx\n", batch, single_seconds * 1000.0, batch_seconds * 1000.0, single_seconds / batch_seconds);
    hf_runtime_destroy(runtime);
    return 0;
}
