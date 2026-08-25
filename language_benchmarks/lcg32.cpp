#include <cstdint>
#include <iostream>

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const uint32_t iterations = static_cast<uint32_t>(std::stoul(argv[1]));
    uint32_t state = static_cast<uint32_t>(std::stoul(argv[2]));
    for (uint32_t index = 0; index < iterations; ++index) {
        state = state * 1664525u + 1013904223u;
    }
    std::cout << "result=" << state << "\n";
    return 0;
}
