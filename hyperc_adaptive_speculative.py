#!/usr/bin/env python3
"""Adaptive speculative decoding for HyperC.

The policy changes draft length only after a completed transactional round.
It never mutates cache state, so policy adaptation cannot invalidate rollback
semantics. Thermal states are bounded and hysteretic rather than arbitrary.
"""
from __future__ import annotations

from dataclasses import dataclass

from hyperc_speculative import SpeculativeDecoder, SpeculativePlan, make_models


@dataclass
class ThermalState:
    level: str = "cool"

    def limit(self, k_max: int) -> int:
        return {"cool": k_max, "warm": max(1, int(k_max * 0.75)), "hot": max(1, int(k_max * 0.4)), "critical": 1}.get(self.level, 1)


@dataclass
class AdaptiveSpeculativePolicy:
    draft_k: int = 4
    target_acceptance: float = 0.72
    gain: float = 3.0
    k_min: int = 1
    k_max: int = 8
    ewma_alpha: float = 0.25
    acceptance_ewma: float = 0.0
    rounds: int = 0

    def __post_init__(self) -> None:
        if not self.k_min <= self.draft_k <= self.k_max:
            raise ValueError("draft_k must be within bounds")
        if not 0.0 < self.ewma_alpha <= 1.0:
            raise ValueError("ewma_alpha must be in (0, 1]")
        if not 0.0 <= self.target_acceptance <= 1.0:
            raise ValueError("target_acceptance must be in [0, 1]")

    def update(self, accepted: int, rejected: int, thermal: ThermalState) -> int:
        observed = accepted / max(1, accepted + rejected)
        if self.rounds == 0:
            self.acceptance_ewma = observed
        else:
            self.acceptance_ewma = self.ewma_alpha * observed + (1.0 - self.ewma_alpha) * self.acceptance_ewma
        self.rounds += 1
        proposed = round(self.draft_k + self.gain * (self.acceptance_ewma - self.target_acceptance))
        self.draft_k = max(self.k_min, min(self.k_max, proposed))
        self.draft_k = min(self.draft_k, thermal.limit(self.k_max))
        return self.draft_k


class AdaptiveSpeculativeDecoder(SpeculativeDecoder):
    def __init__(self, *args, policy: AdaptiveSpeculativePolicy | None = None, thermal: ThermalState | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = policy or AdaptiveSpeculativePolicy(draft_k=self.plan.draft_k)
        self.thermal = thermal or ThermalState()
        self.history: list[dict[str, float | int | str]] = []

    def step(self) -> list[int]:
        accepted_before = self.accepted_draft
        rejected_before = self.rejected_draft
        emitted = super().step()
        accepted = self.accepted_draft - accepted_before
        rejected = self.rejected_draft - rejected_before
        next_k = self.policy.update(accepted, rejected, self.thermal)
        self.plan.draft_k = next_k
        self.history.append({
            "round": self.rounds,
            "accepted": accepted,
            "rejected": rejected,
            "acceptance_ewma": self.policy.acceptance_ewma,
            "draft_k": next_k,
            "thermal": self.thermal.level,
        })
        return emitted


def demo() -> dict[str, object]:
    draft, target = make_models(vocab=32, seed=41)
    plan = SpeculativePlan(draft_k=4, mode="greedy")
    policy = AdaptiveSpeculativePolicy(draft_k=4, k_max=8, target_acceptance=0.6)
    decoder = AdaptiveSpeculativeDecoder(draft, target, plan, policy=policy, thermal=ThermalState("cool"), max_tokens=256)
    decoder.cache.tokens = [0]
    tokens = decoder.generate(64)
    return {"tokens": len(tokens), "cache_length": len(decoder.cache.tokens), "history": decoder.history, "final_k": decoder.plan.draft_k}


if __name__ == "__main__":
    import json
    print(json.dumps(demo(), indent=2))
