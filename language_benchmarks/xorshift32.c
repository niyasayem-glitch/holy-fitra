#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static uint64_t monotonic_ns(void) {
    struct timespec value;
    clock_gettime(CLOCK_MONOTONIC, &value);
    return (uint64_t)value.tv_sec * 1000000000ull + (uint64_t)value.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const uint64_t iterations = strtoull(argv[1], NULL, 10);
    uint32_t state = (uint32_t)strtoul(argv[2], NULL, 10);
    const uint64_t started = monotonic_ns();
    for (uint64_t index = 0; index < iterations; ++index) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
    }
    printf("result=%" PRIu32 " loop_ns=%" PRIu64 "\n", state, monotonic_ns() - started);
    return 0;
}
