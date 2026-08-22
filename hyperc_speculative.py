#!/usr/bin/env python3
"""HyperC speculative decoding prototype.

The runtime implements:
- draft proposal of K tokens;
- target verification in one logical batch;
- greedy acceptance for deterministic decoding;
- rejection sampling for exact target-distribution sampling;
- transactional KV/cache semantics with rollback-safe commit;
- a compiler-pass SpecIR plan and AArch64 LLVM orchestration stub.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class CacheState:
    tokens: list[int] = field(default_factory=list)
    max_tokens: int = 4096

    def begin(self) -> int:
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool) or self.max_tokens <= 0:
            raise RuntimeError("cache capacity must be a positive integer")
        if len(self.tokens) >= self.max_tokens:
            raise RuntimeError("cache capacity exhausted")
        return len(self.tokens)

    def rollback(self, checkpoint: int) -> None:
        if not 0 <= checkpoint <= len(self.tokens):
            raise RuntimeError("invalid cache checkpoint")
        del self.tokens[checkpoint:]

    def commit(self, checkpoint: int, accepted: list[int]) -> None:
        if checkpoint != len(self.tokens) or checkpoint < 0:
            raise RuntimeError("transaction was modified before commit")
        if len(self.tokens) + len(accepted) > self.max_tokens:
            raise RuntimeError("speculative commit exceeds cache capacity")
        self.tokens.extend(int(x) for x in accepted)


class MarkovModel:
    """Small deterministic next-token model used to test compiler semantics."""

    def __init__(self, logits: np.ndarray, name: str):
        logits = np.asarray(logits, dtype=np.float64)
        if logits.ndim != 2 or logits.shape[0] != logits.shape[1] or logits.shape[0] <= 0 or not np.all(np.isfinite(logits)) or not name:
            raise ValueError("logits must be a finite non-empty [vocab, vocab] matrix with a name")
        self.logits = np.ascontiguousarray(logits)
        self.vocab = logits.shape[0]
        self.name = name
        self.calls = 0
        self.token_evals = 0

    def distribution(self, prefix: list[int]) -> np.ndarray:
        if not prefix:
            state = 0
        else:
            state = int(prefix[-1]) % self.vocab
        self.calls += 1
        self.token_evals += 1
        row = self.logits[state] - np.max(self.logits[state])
        probabilities = np.exp(row)
        probabilities /= np.sum(probabilities)
        if not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0.0) or not np.isclose(float(np.sum(probabilities)), 1.0, rtol=1e-6, atol=1e-6):
            raise RuntimeError("model produced an invalid probability distribution")
        return probabilities

    def reset_counters(self) -> None:
        self.calls = 0
        self.token_evals = 0


def sample_distribution(probabilities: np.ndarray, rng: np.random.Generator) -> int:
    probabilities = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    if probabilities.size == 0 or not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0.0):
        raise RuntimeError("invalid sampling distribution")
    total = float(np.sum(probabilities))
    if not math.isfinite(total) or total <= 0.0:
        raise RuntimeError("sampling distribution has no finite mass")
    probabilities = probabilities / total
    return int(rng.choice(len(probabilities), p=probabilities))


@dataclass
class SpeculativePlan:
    draft_k: int = 5
    mode: str = "greedy"
    cache_policy: str = "transactional"

    def __post_init__(self) -> None:
        if not isinstance(self.draft_k, int) or isinstance(self.draft_k, bool) or self.draft_k <= 0 or self.mode not in {"greedy", "sample"} or self.cache_policy != "transactional" or not self.operations:
            raise ValueError("invalid speculative plan")
    operations: tuple[str, ...] = (
        "draft.propose[k]",
        "target.verify_batch[k]",
        "accept.prefix",
        "rollback.rejected_suffix",
        "commit.accepted_plus_repair",
    )

    def to_spec_ir(self) -> str:
        ops = "\n".join(f"  {index}: {operation}" for index, operation in enumerate(self.operations))
        return f"""speculative_plan HyperCSpec {{
  draft_k: {self.draft_k}
  mode: {self.mode}
  cache_policy: {self.cache_policy}
{ops}
}}"""


def emit_llvm_orchestration(plan: SpeculativePlan) -> str:
    """Emit a small LLVM ABI stub; model kernels remain external runtime calls."""
    return f"""; HyperC speculative decoding compiler-pass stub
; draft_k={plan.draft_k}, mode={plan.mode}, cache={plan.cache_policy}
; The runtime call performs draft proposal, target verification, acceptance,
; residual repair, and transactional KV-cache commit.
target triple = \"aarch64-linux-android21\"

declare i32 @hyperc_speculative_runtime_step(ptr, ptr, ptr, i32, i32)

define i32 @hyperc_speculative_step(ptr %state, ptr %draft, ptr %target, i32 %cache_len) {{
entry:
  %accepted = call i32 @hyperc_speculative_runtime_step(ptr %state, ptr %draft, ptr %target, i32 {plan.draft_k}, i32 %cache_len)
  ret i32 %accepted
}}
"""


def emit_aarch64_object(plan: SpeculativePlan, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ir = output_dir / "hyperc_speculative_step.ll"
    obj = output_dir / "hyperc_speculative_step.aarch64.o"
    ir.write_text(emit_llvm_orchestration(plan))
    command = ["llc", "-mtriple=aarch64-linux-android21", "-O2", "-filetype=obj", str(ir), "-o", str(obj)]
    start = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True)
    return {
        "success": completed.returncode == 0,
        "elapsed_ms": (time.perf_counter() - start) * 1000,
        "ir": str(ir),
        "object": str(obj),
        "object_bytes": obj.stat().st_size if obj.exists() else None,
        "stderr": completed.stderr[-1000:],
        "command": " ".join(command),
    }


class SpeculativeDecoder:
    def __init__(self, draft: MarkovModel, target: MarkovModel, plan: SpeculativePlan, max_tokens: int = 4096, seed: int = 17):
        if draft.vocab != target.vocab:
            raise ValueError("draft and target vocabularies must match")
        if plan.draft_k <= 0:
            raise ValueError("draft_k must be positive")
        if plan.mode not in ("greedy", "sample"):
            raise ValueError("mode must be greedy or sample")
        self.draft = draft
        self.target = target
        self.plan = plan
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        self.cache = CacheState(max_tokens=max_tokens)
        self.rng = np.random.default_rng(seed)
        self.rounds = 0
        self.accepted_draft = 0
        self.rejected_draft = 0
        self.target_batches = 0
        self.target_token_evals = 0

    def _draft_propose(self) -> tuple[list[int], list[np.ndarray]]:
        proposal: list[int] = []
        distributions: list[np.ndarray] = []
        prefix = list(self.cache.tokens)
        for _ in range(self.plan.draft_k):
            distribution = self.draft.distribution(prefix + proposal)
            distributions.append(distribution)
            token = int(np.argmax(distribution)) if self.plan.mode == "greedy" else sample_distribution(distribution, self.rng)
            proposal.append(token)
        return proposal, distributions

    def _target_verify(self, proposal: list[int]) -> list[np.ndarray]:
        # One logical target batch verifies all proposed positions. The toy
        # model evaluates sequentially to preserve exact autoregressive states.
        target_distributions = []
        prefix = list(self.cache.tokens)
        for token in proposal:
            target_distributions.append(self.target.distribution(prefix))
            prefix.append(token)
        target_distributions.append(self.target.distribution(prefix))
        self.target_batches += 1
        self.target_token_evals += len(target_distributions)
        return target_distributions

    def _greedy_accept(self, proposal: list[int], target_distributions: list[np.ndarray]) -> tuple[list[int], int]:
        accepted: list[int] = []
        for token, distribution in zip(proposal, target_distributions):
            target_token = int(np.argmax(distribution))
            if token != target_token:
                self.rejected_draft += 1
                return accepted + [target_token], len(accepted)
            accepted.append(token)
            self.accepted_draft += 1
        return accepted + [int(np.argmax(target_distributions[-1]))], len(accepted)

    def _sample_accept(self, proposal: list[int], draft_distributions: list[np.ndarray], target_distributions: list[np.ndarray]) -> tuple[list[int], int]:
        accepted: list[int] = []
        for index, token in enumerate(proposal):
            target_p = float(target_distributions[index][token])
            draft_q = float(draft_distributions[index][token])
            if not math.isfinite(target_p) or not math.isfinite(draft_q) or target_p < 0.0 or draft_q < 0.0:
                raise RuntimeError("invalid draft or target probability")
            draft_q = max(draft_q, 1e-12)
            probability = min(1.0, target_p / draft_q)
            if self.rng.random() <= probability:
                accepted.append(token)
                self.accepted_draft += 1
                continue
            residual = np.maximum(target_distributions[index] - draft_distributions[index], 0.0)
            total = float(np.sum(residual))
            repaired = target_distributions[index] if total <= 1e-12 else residual / total
            accepted.append(sample_distribution(repaired, self.rng))
            self.rejected_draft += 1
            return accepted, len(accepted) - 1
        accepted.append(sample_distribution(target_distributions[-1], self.rng))
        return accepted, len(proposal)

    def step(self) -> list[int]:
        checkpoint = self.cache.begin()
        proposal, draft_distributions = self._draft_propose()
        target_distributions = self._target_verify(proposal)
        if self.plan.mode == "greedy":
            emitted, accepted_count = self._greedy_accept(proposal, target_distributions)
        else:
            emitted, accepted_count = self._sample_accept(proposal, draft_distributions, target_distributions)
        # A failed proposal never mutates committed state. Only the verified
        # accepted prefix and repair token are committed atomically.
        self.cache.rollback(checkpoint)
        self.cache.commit(checkpoint, emitted)
        self.rounds += 1
        return emitted

    def generate(self, count: int) -> list[int]:
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("count must be non-negative")
        prefix_len = len(self.cache.tokens)
        output: list[int] = []
        while len(output) < count:
            output.extend(self.step())
        # A speculative round can emit more than the caller requested. Those
        # surplus tokens must not remain committed in the KV cache, otherwise
        # a later call would observe state that was never returned to the user.
        desired_cache_len = prefix_len + count
        if len(self.cache.tokens) > desired_cache_len:
            del self.cache.tokens[desired_cache_len:]
        return output[:count]


def standard_generate(target: MarkovModel, prefix: list[int], count: int) -> list[int]:
    if not isinstance(count, int) or isinstance(count, bool) or count < 0 or not all(isinstance(token, int) and not isinstance(token, bool) and 0 <= token < target.vocab for token in prefix):
        raise ValueError("invalid generation count or prefix")
    output = list(prefix)
    for _ in range(count):
        distribution = target.distribution(output)
        output.append(int(np.argmax(distribution)))
    return output[len(prefix):]


def make_models(vocab: int = 32, seed: int = 41) -> tuple[MarkovModel, MarkovModel]:
    if not isinstance(vocab, int) or isinstance(vocab, bool) or vocab <= 0:
        raise ValueError("vocab must be a positive integer")
    rng = np.random.default_rng(seed)
    target_logits = rng.normal(0, 0.25, size=(vocab, vocab)).astype(np.float64)
    # A strong self-transition gives the draft a realistic high-acceptance path.
    target_logits += np.eye(vocab, dtype=np.float64) * 1.5
    draft_logits = target_logits * 0.96 + rng.normal(0, 0.04, size=target_logits.shape)
    return MarkovModel(draft_logits, "draft"), MarkovModel(target_logits, "target")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", type=int, default=256)
    parser.add_argument("--draft-k", type=int, default=5)
    parser.add_argument("--vocab", type=int, default=32)
    parser.add_argument("--output", type=Path, default=Path("speculative-build"))
    args = parser.parse_args()
    draft, target = make_models(args.vocab)
    prefix = [0]
    baseline = standard_generate(target, prefix, args.tokens)
    target.reset_counters()
    draft.reset_counters()
    greedy_plan = SpeculativePlan(draft_k=args.draft_k, mode="greedy")
    decoder = SpeculativeDecoder(draft, target, greedy_plan, max_tokens=args.tokens + args.draft_k + 2)
    decoder.cache.tokens = prefix.copy()
    start = time.perf_counter()
    speculative = decoder.generate(args.tokens)
    elapsed_ms = (time.perf_counter() - start) * 1000
    exact = baseline == speculative
    object_result = emit_aarch64_object(greedy_plan, args.output)
    # Separate sampling run validates transactional invariants and residual path.
    sample_draft, sample_target = make_models(args.vocab, seed=41)
    sample_plan = SpeculativePlan(draft_k=args.draft_k, mode="sample")
    sample_decoder = SpeculativeDecoder(sample_draft, sample_target, sample_plan, max_tokens=args.tokens + args.draft_k + 2, seed=99)
    sample_decoder.cache.tokens = prefix.copy()
    sample_decoder.generate(args.tokens)
    result = {
        "plan": {"draft_k": args.draft_k, "mode": greedy_plan.mode, "spec_ir": greedy_plan.to_spec_ir()},
        "greedy": {
            "exact_match_to_standard": exact,
            "tokens": args.tokens,
            "elapsed_ms": elapsed_ms,
            "target_batches": decoder.target_batches,
            "target_token_evals": decoder.target_token_evals,
            "draft_token_evals": draft.token_evals,
            "accepted_draft_tokens": decoder.accepted_draft,
            "rejected_draft_tokens": decoder.rejected_draft,
            "acceptance_rate": decoder.accepted_draft / max(1, decoder.accepted_draft + decoder.rejected_draft),
            "rounds": decoder.rounds,
            "tokens_per_target_batch": args.tokens / max(1, decoder.target_batches),
            "cache_length": len(decoder.cache.tokens),
        },
        "sampling_invariants": {
            "cache_within_capacity": len(sample_decoder.cache.tokens) <= sample_decoder.cache.max_tokens,
            "cache_length": len(sample_decoder.cache.tokens),
            "rounds": sample_decoder.rounds,
            "accepted_draft_tokens": sample_decoder.accepted_draft,
            "rejected_draft_tokens": sample_decoder.rejected_draft,
            "target_batches": sample_decoder.target_batches,
        },
        "aarch64_object": object_result,
        "limitations": [
            "The Markov models validate control flow and acceptance semantics, not neural-model quality.",
            "The emitted LLVM object is an orchestration ABI stub; model kernels remain external runtime calls.",
            "Real speedup requires a target model that verifies K draft positions in one efficient batch.",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if exact and result["sampling_invariants"]["cache_within_capacity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
