#include "nibbleflow_android.h"

#include <cassert>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

int main() {
    std::vector<uint8_t> packed = {0x21, 0x21, 0x21, 0x21, 0x43, 0x43, 0x43, 0x43};
    std::vector<float> scales(8, 1.0f);
    std::vector<float> bias(4, 0.0f);
    hf_nibbleflow_model model{
        packed.data(), packed.size(), scales.data(), scales.size(), bias.data(), bias.size(),
        4, 4, 2, hf_nibbleflow_runtime_abi()
    };
    const float input[] = {1.0f, -1.0f, 0.5f, -0.5f};
    float output[4] = {};

    assert(hf_nibbleflow_matvec(&model, input, 4, output, 4) == HF_OK);
    for (float value : output) assert(std::fabs(value + 1.5f) < 1e-6f);
    const float invalid_input[] = {std::numeric_limits<float>::quiet_NaN(), -1.0f, 0.5f, -0.5f};
    assert(hf_nibbleflow_matvec(&model, invalid_input, 4, output, 4) == HF_INVALID_ARGUMENT);

    hf_nibbleflow_static_calibration calibration{
        HF_NIBBLEFLOW_CALIBRATION_ABI, 0.5f, 0, 1.0f, 0.0f, 0.01f, 0.0f, 0.02f, 16
    };
    assert(hf_nibbleflow_validate_static_calibration(&calibration) == HF_OK);
    calibration.observed_clipping_fraction = 0.02f;
    assert(hf_nibbleflow_validate_static_calibration(&calibration) == HF_INVALID_ARGUMENT);
    calibration.observed_clipping_fraction = 0.0f;

    std::vector<int8_t> activation_scratch(4, 0);
    std::vector<float> adapter_scratch(2, 0.0f);
    const std::vector<float> down = {1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f};
    const std::vector<float> up = {1.0f, 2.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
    hf_nibbleflow_adapter adapter{down.data(), down.size(), up.data(), up.size(), 2, 0.5f, HF_NIBBLEFLOW_ADAPTER_ABI};
    assert(hf_nibbleflow_validate_adapter(&model, &adapter) == HF_OK);

    hf_nibbleflow_execution_plan plan{
        HF_NIBBLEFLOW_EXECUTION_ABI,
        HF_NIBBLEFLOW_ACTIVATION_STATIC_INT8,
        &calibration,
        &adapter,
        activation_scratch.data(), activation_scratch.size(),
        adapter_scratch.data(), adapter_scratch.size()
    };
    assert(hf_nibbleflow_validate_execution_plan(&model, &plan) == HF_OK);
    assert(hf_nibbleflow_matvec_ex(&model, &plan, input, 4, output, 4) == HF_OK);
    assert(std::fabs(output[0] + 2.0f) < 1e-6f);
    for (int index = 1; index < 4; ++index) assert(std::fabs(output[index] + 1.5f) < 1e-6f);

    plan.activation_scratch_count = 3;
    assert(hf_nibbleflow_validate_execution_plan(&model, &plan) == HF_BUFFER_TOO_SMALL);
    plan.activation_scratch_count = activation_scratch.size();
    adapter.down_count -= 1;
    assert(hf_nibbleflow_validate_adapter(&model, &adapter) == HF_BUFFER_TOO_SMALL);
    return 0;
}
