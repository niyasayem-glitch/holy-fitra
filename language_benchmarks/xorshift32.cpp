#include <chrono>
#include <cstdint>
#include <iostream>

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const uint64_t iterations = std::stoull(argv[1]);
    uint32_t state = static_cast<uint32_t>(std::stoul(argv[2]));
    const auto started = std::chrono::steady_clock::now();
    for (uint64_t index = 0; index < iterations; ++index) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
    }
    const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - started).count();
    std::cout << "result=" << state << " loop_ns=" << elapsed << "\n";
    return 0;
}
