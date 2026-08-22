#include "nibbleflow_android.h"

#include <cassert>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

int main() {
    std::vector<uint8_t> packed(8, 0);
    std::vector<float> scales(8, 1.0f);
    std::vector<float> bias(4, 0.0f);
    hf_nibbleflow_model model{
        packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(),
        4, 4, 2, hf_nibbleflow_runtime_abi()
    };
    assert(hf_nibbleflow_validate_model(&model) == HF_OK);

    scales[0] = std::numeric_limits<float>::quiet_NaN();
    assert(hf_nibbleflow_validate_model(&model) == HF_INVALID_ARGUMENT);
    scales[0] = 1.0f;
    scales[1] = std::numeric_limits<float>::infinity();
    assert(hf_nibbleflow_validate_model(&model) == HF_INVALID_ARGUMENT);
    scales[1] = 1.0f;
    bias[0] = -std::numeric_limits<float>::infinity();
    assert(hf_nibbleflow_validate_model(&model) == HF_INVALID_ARGUMENT);
    bias[0] = 0.0f;

    model.in_dim = std::numeric_limits<int32_t>::max();
    model.group_size = 2;
    assert(hf_nibbleflow_validate_model(&model) == HF_BUFFER_TOO_SMALL);

    model.in_dim = 4;
    model.out_dim = std::numeric_limits<int32_t>::max();
    assert(hf_nibbleflow_validate_model(&model) == HF_BUFFER_TOO_SMALL);
    return 0;
}
