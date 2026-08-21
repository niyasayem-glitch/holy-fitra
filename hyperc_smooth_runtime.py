#!/usr/bin/env python3
"""Holy Fitra smooth decoding fast path.

This optimized toy runtime preserves the existing Markov-model semantics while
removing hot-loop list copies, repeated softmax work, and dynamic proposal
allocation. It models the same techniques used by a native decode engine:
precomputed immutable tables, preallocated buffers, cursor-based transactions,
and a fast greedy path separated from sampling.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import numpy as np

from hyperc_speculative import MarkovModel, SpeculativeDecoder, SpeculativePlan, make_models, standard_generate


class PreallocatedTokenCache:
    def __init__(self, max_tokens: int):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.tokens = np.empty(max_tokens, dtype=np.int32)
        self.length = 0

    def load(self, prefix: list[int]) -> None:
        if len(prefix) > len(self.tokens):
            raise RuntimeError("prefix exceeds cache capacity")
        self.tokens[: len(prefix)] = prefix
        self.length = len(prefix)

    def begin(self) -> int:
        return self.length

    def rollback(self, checkpoint: int) -> None:
        if not 0 <= checkpoint <= self.length:
            raise RuntimeError("invalid cache checkpoint")
        self.length = checkpoint

    def commit(self, checkpoint: int, values: np.ndarray, count: int) -> None:
        if checkpoint != self.length:
            raise RuntimeError("cache changed before commit")
        if self.length + count > len(self.tokens):
            raise RuntimeError("cache capacity exhausted")
        self.tokens[self.length : self.length + count] = values[:count]
        self.length += count

    def as_list(self) -> list[int]:
        return self.tokens[: self.length].tolist()


class PrecomputedMarkov:
    def __init__(self, model: MarkovModel):
        logits = np.asarray(model.logits, dtype=np.float64)
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        probabilities = np.exp(shifted)
        probabilities /= np.sum(probabilities, axis=1, keepdims=True)
        self.probabilities = probabilities
        self.greedy = np.argmax(probabilities, axis=1).astype(np.int32)
        self.vocab = probabilities.shape[0]
        self.name = model.name
        self.calls = 0
        self.token_evals = 0

    def distribution_for_state(self, state: int) -> np.ndarray:
        self.calls += 1
        self.token_evals += 1
        return self.probabilities[int(state) % self.vocab]

    def greedy_for_state(self, state: int) -> int:
        self.calls += 1
        self.token_evals += 1
        return int(self.greedy[int(state) % self.vocab])

    def reset_counters(self) -> None:
        self.calls = 0
        self.token_evals = 0


@dataclass
class SmoothPlan:
    draft_k: int = 5
    max_tokens: int = 4096


class SmoothGreedyDecoder:
    def __init__(self, draft: PrecomputedMarkov, target: PrecomputedMarkov, plan: SmoothPlan):
        if plan.draft_k <= 0:
            raise ValueError("draft_k must be positive")
        self.draft = draft
        self.target = target
        self.plan = plan
        self.cache = PreallocatedTokenCache(plan.max_tokens)
        self.proposal = np.empty(plan.draft_k, dtype=np.int32)
        self.emitted = np.empty(plan.draft_k + 1, dtype=np.int32)
        self.rounds = 0
        self.accepted_draft = 0
        self.rejected_draft = 0
        self.target_evals = 0

    def step(self) -> np.ndarray:
        checkpoint = self.cache.begin()
        if checkpoint == 0:
            state = 0
        else:
            state = int(self.cache.tokens[checkpoint - 1])
        for index in range(self.plan.draft_k):
            token = self.draft.greedy_for_state(state)
            self.proposal[index] = token
            state = token
        # Verify the proposal directly from the state sequence. No prefixes,
        # Python token lists, or repeated softmax calculations are needed.
        if checkpoint == 0:
            state = 0
        else:
            state = int(self.cache.tokens[checkpoint - 1])
        accepted = 0
        for index in range(self.plan.draft_k):
            target_token = self.target.greedy_for_state(state)
            proposed = int(self.proposal[index])
            if proposed != target_token:
                self.emitted[accepted] = target_token
                self.rejected_draft += 1
                accepted += 1
                break
            self.emitted[accepted] = proposed
            accepted += 1
            self.accepted_draft += 1
            state = proposed
        else:
            self.emitted[accepted] = self.target.greedy_for_state(state)
            accepted += 1
        self.target_evals += accepted
        self.cache.rollback(checkpoint)
        self.cache.commit(checkpoint, self.emitted, accepted)
        self.rounds += 1
        return self.emitted[:accepted]

    def generate(self, count: int) -> list[int]:
        if count < 0:
            raise ValueError("count must be non-negative")
        prefix_length = self.cache.length
        output = np.empty(max(1, count + self.plan.draft_k + 1), dtype=np.int32)
        produced = 0
        while produced < count:
            chunk = self.step()
            take = min(len(chunk), count - produced)
            output[produced : produced + take] = chunk[:take]
            produced += take
        self.cache.length = prefix_length + count
        return output[:count].tolist()


def benchmark(tokens: int = 512, draft_k: int = 5, repeats: int = 5) -> dict[str, object]:
    draft_model, target_model = make_models(vocab=64, seed=41)
    prefix = [0]
    expected = standard_generate(target_model, prefix, tokens)
    baseline_times: list[float] = []
    smooth_times: list[float] = []
    baseline_output: list[int] = []
    smooth_output: list[int] = []
    for _ in range(repeats):
        draft, target = make_models(vocab=64, seed=41)
        baseline = SpeculativeDecoder(draft, target, SpeculativePlan(draft_k=draft_k, mode="greedy"), max_tokens=tokens + draft_k + 4)
        baseline.cache.tokens = prefix.copy()
        start = time.perf_counter()
        baseline_output = baseline.generate(tokens)
        baseline_times.append((time.perf_counter() - start) * 1000)
        fast_draft, fast_target = make_models(vocab=64, seed=41)
        smooth = SmoothGreedyDecoder(PrecomputedMarkov(fast_draft), PrecomputedMarkov(fast_target), SmoothPlan(draft_k=draft_k, max_tokens=tokens + draft_k + 4))
        smooth.cache.load(prefix)
        start = time.perf_counter()
        smooth_output = smooth.generate(tokens)
        smooth_times.append((time.perf_counter() - start) * 1000)
    baseline_ms = float(np.median(baseline_times))
    smooth_ms = float(np.median(smooth_times))
    return {
        "tokens": tokens,
        "draft_k": draft_k,
        "repeats": repeats,
        "exact_vs_target": smooth_output == expected,
        "baseline_exact_vs_target": baseline_output == expected,
        "baseline_median_ms": baseline_ms,
        "smooth_median_ms": smooth_ms,
        "speedup": baseline_ms / smooth_ms if smooth_ms else None,
        "smooth_cache_length": len(smooth.cache.as_list()),
        "smooth_rounds": smooth.rounds,
        "smooth_target_evals": smooth.target_evals,
        "optimizations": [
            "precomputed immutable transition probabilities",
            "precomputed greedy token table",
            "preallocated proposal and emission buffers",
            "cursor-based cache transactions",
            "direct state transitions without prefix-list copies",
            "greedy fast path separated from sampling",
        ],
        "limitations": [
            "This benchmark uses deterministic Markov fixtures, not a neural transformer.",
            "The smooth path is a host Python prototype; Android speed requires native ARM64 kernels.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2, sort_keys=True))
