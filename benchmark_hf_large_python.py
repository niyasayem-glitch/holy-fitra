"""Pure-Python scalar reference for HF_LARGE_MODEL_BENCHMARK_CONTRACT.md.

Deliberately avoids NumPy, PyTorch, Numba, Cython, and native extensions.
"""

from __future__ import annotations

import time

IN_DIM = 1024
OUT_DIM = 1024
GROUP_SIZE = 32
BATCH = 32
MEASURED_RUNS = 3


def next_word(state: int) -> tuple[int, int]:
    state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
    return state, state


def generated_signed(state: int, divisor: int) -> tuple[int, float]:
    state, word = next_word(state)
    return state, (int(word % 2049) - 1024) / float(divisor)


def sign_extend_nibble(value: int) -> int:
    value &= 0x0F
    return value if value < 8 else value - 16


def packed_index(groups: int, pairs: int, tile: int, group: int, pair: int, lane: int) -> int:
    return (((tile * groups + group) * pairs + pair) * 4) + lane


def scale_index(groups: int, tile: int, group: int, lane: int) -> int:
    return (tile * groups + group) * 4 + lane


def build_fixture() -> tuple[list[int], list[float], list[float], list[float]]:
    groups = (IN_DIM + GROUP_SIZE - 1) // GROUP_SIZE
    tiles = (OUT_DIM + 3) // 4
    pairs = GROUP_SIZE // 2
    state = 0x4F1BBCD9
    packed: list[int] = []
    for _ in range(tiles * groups * pairs * 4):
        state, word = next_word(state)
        packed.append(word & 0xFF)
    scales: list[float] = []
    for _ in range(tiles * groups * 4):
        state, word = next_word(state)
        scales.append((int(word % 15) + 1) / 16.0)
    bias: list[float] = []
    for _ in range(OUT_DIM):
        state, value = generated_signed(state, 32)
        bias.append(value)
    inputs: list[float] = []
    for _ in range(BATCH * IN_DIM):
        state, value = generated_signed(state, 1024)
        inputs.append(value)
    return packed, scales, bias, inputs


def matvec_batch(packed: list[int], scales: list[float], bias: list[float], inputs: list[float]) -> list[float]:
    groups = (IN_DIM + GROUP_SIZE - 1) // GROUP_SIZE
    tiles = (OUT_DIM + 3) // 4
    pairs = GROUP_SIZE // 2
    output = [0.0] * (BATCH * OUT_DIM)
    for row in range(BATCH):
        input_offset = row * IN_DIM
        output_offset = row * OUT_DIM
        for out_index in range(OUT_DIM):
            tile = out_index // 4
            lane = out_index % 4
            total = 0.0
            for group in range(groups):
                group_sum = 0.0
                start = group * GROUP_SIZE
                scale = scales[scale_index(groups, tile, group, lane)]
                for pair in range(pairs):
                    packed_value = packed[packed_index(groups, pairs, tile, group, pair, lane)]
                    input_index = start + pair * 2
                    group_sum += inputs[input_offset + input_index] * sign_extend_nibble(packed_value)
                    group_sum += inputs[input_offset + input_index + 1] * sign_extend_nibble(packed_value >> 4)
                total += group_sum * scale
            output[output_offset + out_index] = total + bias[out_index]
    return output


def checksums_for(output: list[float]) -> tuple[float, float]:
    total = 0.0
    weighted = 0.0
    for index, value in enumerate(output):
        total += value
        weighted += (index + 1) * value
    return total, weighted


def main() -> None:
    packed, scales, bias, inputs = build_fixture()
    matvec_batch(packed, scales, bias, inputs)  # warm-up
    total_seconds = 0.0
    output: list[float] = []
    for _ in range(MEASURED_RUNS):
        start = time.perf_counter()
        output = matvec_batch(packed, scales, bias, inputs)
        total_seconds += time.perf_counter() - start
    output_sum, output_weighted = checksums_for(output)
    operations = BATCH * IN_DIM * OUT_DIM
    print(
        "engine=pure_python_scalar"
        f" in_dim={IN_DIM}"
        f" out_dim={OUT_DIM}"
        f" batch={BATCH}"
        f" macs={operations}"
        f" measured_runs={MEASURED_RUNS}"
        f" avg_batch_ms={(total_seconds / MEASURED_RUNS) * 1000.0:.6f}"
        f" output_sum={output_sum:.6f}"
        f" output_weighted={output_weighted:.6f}"
        " planned_ranges=1 admitted_ranges=1 completed_ranges=1"
    )


if __name__ == "__main__":
    main()
