#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const uint32_t iterations = (uint32_t)strtoul(argv[1], NULL, 10);
    uint32_t state = (uint32_t)strtoul(argv[2], NULL, 10);
    for (uint32_t index = 0; index < iterations; ++index) {
        state = state * 1664525u + 1013904223u;
    }
    printf("result=%" PRIu32 "\n", state);
    return 0;
}
