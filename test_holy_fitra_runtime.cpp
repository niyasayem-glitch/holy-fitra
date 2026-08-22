#include "holy_fitra_runtime.h"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <vector>

int main() {
    const int in_dim = 5;
    const int out_dim = 3;
    const int group_size = 2;
    std::vector<uint8_t> packed(12, 0);
    std::vector<float> scales(12, 1.0f);
    std::vector<float> bias(out_dim, 0.0f);
    std::vector<float> input(in_dim, 2.0f);
    std::vector<float> output(out_dim, 7.0f);
    hf_nibbleflow_model model{packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(), in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()};
    hf_holyfitra_runtime *runtime = hf_runtime_create(&model, 32, 0);
    assert(runtime != nullptr);
    hf_runtime_request *request = nullptr;
    assert(hf_runtime_submit_matvec(runtime, input.data(), input.size(), output.data(), output.size(), -1, HF_RUNTIME_PRIORITY_INTERACTIVE, 0, &request) == HF_INVALID_ARGUMENT);
    assert(request == nullptr);
    assert(hf_runtime_submit_matvec(runtime, input.data(), input.size(), output.data(), output.size(), HF_RUNTIME_CORE_ANY, 99, 0, &request) == HF_INVALID_ARGUMENT);
    assert(request == nullptr);
    assert(hf_runtime_submit_matvec(runtime, input.data(), input.size(), output.data(), output.size(), HF_RUNTIME_CORE_ANY, HF_RUNTIME_PRIORITY_INTERACTIVE, 0, &request) == HF_OK);
    assert(request != nullptr);
    assert(hf_runtime_wait(request, 1000) == HF_OK);
    for (float value : output) assert(std::fabs(value) < 1e-6f);
    hf_runtime_request_destroy(request);
    hf_runtime_set_thermal(runtime, 3);
    hf_runtime_set_thermal(runtime, 99);
    hf_runtime_stats stats = hf_runtime_get_stats(runtime);
    assert(stats.completed >= 1);
    assert(stats.abi_version == 1);
    hf_runtime_destroy(runtime);
    return 0;
}
