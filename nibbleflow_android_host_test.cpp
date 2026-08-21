#include "nibbleflow_android.h"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

int main() {
    const int in_dim = 5;
    const int out_dim = 3;
    const int group_size = 2;
    const size_t packed_bytes = 12;
    const size_t scale_count = 12;
    std::vector<uint8_t> packed(packed_bytes, 0);
    std::vector<float> scales(scale_count, 1.0f);
    std::vector<float> bias(out_dim, 0.0f);
    // Three output lanes, two input pairs per group layout for this fixture.
    // All nibbles are zero, so the expected output is exactly zero.
    hf_nibbleflow_model model{packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(), in_dim, out_dim, group_size, 1};
    assert(hf_nibbleflow_runtime_abi() == 1);
    assert(hf_nibbleflow_validate_model(&model) == HF_OK);
    std::vector<float> input(in_dim, 2.0f);
    std::vector<float> output(out_dim, 7.0f);
    assert(hf_nibbleflow_matvec(&model, input.data(), input.size(), output.data(), output.size()) == HF_OK);
    for (float value : output) assert(std::fabs(value) < 1e-6f);
    model.packed_bytes = 1;
    assert(hf_nibbleflow_validate_model(&model) == HF_BUFFER_TOO_SMALL);
    std::printf("nibbleflow_android_host_test: pass abi=%u neon=%d status=%s\n", hf_nibbleflow_runtime_abi(), hf_nibbleflow_has_neon(), hf_status_string(HF_OK));
    return 0;
}
