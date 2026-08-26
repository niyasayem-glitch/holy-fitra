"""Bounded trainable causal embedding-attention baseline for Holy Fitra.

This is deliberately a small single-layer NumPy reference model. It supplies a
real causal attention training and decoding contract, but is not evidence of
transformer-scale quality or Qwen-class capabilities.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from holyfitra_local_lm import (
    BOS_TOKEN,
    BYTE_VOCAB_SIZE,
    LocalLMEvaluationReceipt,
    LocalLMTrainingReceipt,
    LocalLanguageModelError,
    MAX_GENERATED_TOKENS,
    VOCAB_SIZE,
    ByteTokenizer,
    _hash_texts,
)


ATTENTION_SCHEMA = "holyfitra.local-causal-embedding-attention/v1"
MAX_ATTENTION_CONTEXT = 32
MAX_ATTENTION_DIM = 64
MAX_ATTENTION_EPOCHS = 16
MAX_ATTENTION_PARAMETERS = 160_000


class CausalEmbeddingAttentionLanguageModel:
    """A bounded single-head causal attention next-byte model with SGD training."""

    def __init__(
        self,
        *,
        d_model: int = 16,
        context_tokens: int = 16,
        learning_rate: float = 0.05,
        epochs: int = 4,
        seed: int = 17,
    ) -> None:
        if not isinstance(d_model, int) or isinstance(d_model, bool) or not 4 <= d_model <= MAX_ATTENTION_DIM:
            raise LocalLanguageModelError(f"d_model must be an integer between 4 and {MAX_ATTENTION_DIM}")
        if not isinstance(context_tokens, int) or isinstance(context_tokens, bool) or not 2 <= context_tokens <= MAX_ATTENTION_CONTEXT:
            raise LocalLanguageModelError(f"context_tokens must be an integer between 2 and {MAX_ATTENTION_CONTEXT}")
        if not isinstance(learning_rate, (int, float)) or isinstance(learning_rate, bool) or not np.isfinite(float(learning_rate)) or not 0.0 < float(learning_rate) <= 1.0:
            raise LocalLanguageModelError("learning_rate must be finite and between 0 and 1")
        if not isinstance(epochs, int) or isinstance(epochs, bool) or not 1 <= epochs <= MAX_ATTENTION_EPOCHS:
            raise LocalLanguageModelError(f"epochs must be an integer between 1 and {MAX_ATTENTION_EPOCHS}")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise LocalLanguageModelError("seed must be an integer")
        self.d_model = int(d_model)
        self.context_tokens = int(context_tokens)
        self.learning_rate = float(learning_rate)
        self.epochs = int(epochs)
        self.seed = int(seed)
        if self.parameter_count > MAX_ATTENTION_PARAMETERS:
            raise LocalLanguageModelError(f"attention parameter count exceeds {MAX_ATTENTION_PARAMETERS}")
        rng = np.random.default_rng(self.seed)
        scale = np.float32(1.0 / np.sqrt(self.d_model))
        self.embedding = rng.normal(0.0, scale, (VOCAB_SIZE, self.d_model)).astype(np.float32)
        self.position = rng.normal(0.0, scale, (self.context_tokens, self.d_model)).astype(np.float32)
        self.wq = rng.normal(0.0, scale, (self.d_model, self.d_model)).astype(np.float32)
        self.wk = rng.normal(0.0, scale, (self.d_model, self.d_model)).astype(np.float32)
        self.wv = rng.normal(0.0, scale, (self.d_model, self.d_model)).astype(np.float32)
        self.wo = rng.normal(0.0, scale, (self.d_model, self.d_model)).astype(np.float32)
        self.output = rng.normal(0.0, scale, (self.d_model, BYTE_VOCAB_SIZE)).astype(np.float32)
        self.bias = np.zeros((BYTE_VOCAB_SIZE,), dtype=np.float32)
        self.transitions = 0

    @property
    def parameter_count(self) -> int:
        return int(VOCAB_SIZE * self.d_model + self.context_tokens * self.d_model + 4 * self.d_model * self.d_model + self.d_model * BYTE_VOCAB_SIZE + BYTE_VOCAB_SIZE)

    def _arrays(self) -> dict[str, np.ndarray]:
        return {
            "embedding": self.embedding,
            "position": self.position,
            "wq": self.wq,
            "wk": self.wk,
            "wv": self.wv,
            "wo": self.wo,
            "output": self.output,
            "bias": self.bias,
        }

    @property
    def model_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(ATTENTION_SCHEMA.encode("utf-8"))
        for value in (self.d_model, self.context_tokens, self.epochs, self.seed, self.transitions):
            digest.update(int(value).to_bytes(8, "little", signed=True))
        digest.update(repr(self.learning_rate).encode("ascii"))
        for name, value in self._arrays().items():
            digest.update(name.encode("ascii"))
            digest.update(np.ascontiguousarray(value).tobytes(order="C"))
        return digest.hexdigest()

    def _forward(self, tokens: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        values = np.asarray(tokens, dtype=np.int32).reshape(-1)
        if not 1 <= values.size <= self.context_tokens or np.any(values < 0) or np.any(values >= VOCAB_SIZE):
            raise LocalLanguageModelError("attention input must contain in-vocabulary tokens within the context limit")
        length = int(values.size)
        x = self.embedding[values] + self.position[:length]
        q = x @ self.wq
        k = x @ self.wk
        v = x @ self.wv
        scores = (q @ k.T) / np.float32(np.sqrt(self.d_model))
        scores[np.triu_indices(length, k=1)] = -np.inf
        stabilized = scores - np.max(scores, axis=1, keepdims=True)
        probabilities = np.exp(stabilized).astype(np.float32)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        attended = probabilities @ v
        hidden = x + attended @ self.wo
        logits = hidden @ self.output + self.bias
        return logits.astype(np.float32), {"tokens": values, "x": x, "q": q, "k": k, "v": v, "p": probabilities, "attended": attended, "hidden": hidden}

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - np.max(logits, axis=-1, keepdims=True)
        values = np.exp(shifted).astype(np.float32)
        values /= values.sum(axis=-1, keepdims=True)
        return values

    def logits_for_tokens(self, tokens: Iterable[int]) -> np.ndarray:
        """Return causal logits for tests and diagnostics without mutation."""
        logits, _ = self._forward(np.asarray(tuple(tokens), dtype=np.int32))
        return logits.copy()

    def _step(self, inputs: np.ndarray, targets: np.ndarray) -> float:
        logits, cache = self._forward(inputs)
        probabilities = self._softmax(logits)
        rows = np.arange(targets.size)
        loss = -float(np.log(probabilities[rows, targets]).mean())
        d_logits = probabilities
        d_logits[rows, targets] -= 1.0
        d_logits /= np.float32(targets.size)
        hidden, attended, p, q, k, v, x = (cache[name] for name in ("hidden", "attended", "p", "q", "k", "v", "x"))
        d_output = hidden.T @ d_logits
        d_bias = d_logits.sum(axis=0)
        d_hidden = d_logits @ self.output.T
        d_x = d_hidden.copy()
        d_attended = d_hidden @ self.wo.T
        d_wo = attended.T @ d_hidden
        d_v = p.T @ d_attended
        d_p = d_attended @ v.T
        d_scores = p * (d_p - np.sum(d_p * p, axis=1, keepdims=True))
        scale = np.float32(np.sqrt(self.d_model))
        d_q = (d_scores @ k) / scale
        d_k = (d_scores.T @ q) / scale
        d_wq = x.T @ d_q
        d_wk = x.T @ d_k
        d_wv = x.T @ d_v
        d_x += d_q @ self.wq.T + d_k @ self.wk.T + d_v @ self.wv.T
        d_embedding = np.zeros_like(self.embedding)
        np.add.at(d_embedding, cache["tokens"], d_x)
        d_position = np.zeros_like(self.position)
        d_position[:targets.size] = d_x
        gradients = (d_embedding, d_position, d_wq, d_wk, d_wv, d_wo, d_output, d_bias)
        squared_norm = sum(float(np.sum(np.square(gradient, dtype=np.float64))) for gradient in gradients)
        if not np.isfinite(squared_norm):
            raise LocalLanguageModelError("attention training gradient is non-finite")
        clip = min(1.0, 5.0 / max(float(np.sqrt(squared_norm)), 1e-12))
        for parameter, gradient in zip(self._arrays().values(), gradients, strict=True):
            parameter -= np.float32(self.learning_rate * clip) * gradient.astype(np.float32)
        return loss

    def _batches(self, documents: tuple[np.ndarray, ...]) -> Iterable[tuple[np.ndarray, np.ndarray]]:
        for document in documents:
            inputs = np.concatenate((np.asarray([BOS_TOKEN], dtype=np.int32), document[:-1]))
            for start in range(0, document.size, self.context_tokens):
                end = min(start + self.context_tokens, int(document.size))
                yield inputs[start:end], document[start:end]

    def fit(self, texts: Iterable[str]) -> LocalLMTrainingReceipt:
        corpus_sha256, documents, corpus_bytes = _hash_texts(texts)
        transitions = sum(int(document.size) for document in documents)
        if transitions <= 0:
            raise LocalLanguageModelError("training corpus has no transitions")
        for _ in range(self.epochs):
            for inputs, targets in self._batches(documents):
                self._step(inputs, targets)
        self.transitions = transitions * self.epochs
        return LocalLMTrainingReceipt(corpus_sha256, self.model_sha256, len(documents), corpus_bytes, transitions, self.learning_rate, "causal-embedding-attention", self.context_tokens, 0, self.parameter_count, ATTENTION_SCHEMA)

    def evaluate(self, texts: Iterable[str]) -> LocalLMEvaluationReceipt:
        corpus_sha256, documents, corpus_bytes = _hash_texts(texts)
        nll = 0.0
        transitions = 0
        for inputs, targets in self._batches(documents):
            logits, _ = self._forward(inputs)
            probabilities = self._softmax(logits)
            nll -= float(np.log(probabilities[np.arange(targets.size), targets]).sum())
            transitions += int(targets.size)
        if transitions <= 0 or not np.isfinite(nll):
            raise LocalLanguageModelError("attention evaluation did not produce a finite next-token loss")
        return LocalLMEvaluationReceipt(corpus_sha256, self.model_sha256, len(documents), corpus_bytes, transitions, nll / transitions, "causal-embedding-attention", self.context_tokens, 0, self.parameter_count, ATTENTION_SCHEMA)

    def generate(self, prompt: str, *, max_new_tokens: int = 128) -> str:
        if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool) or not 0 <= max_new_tokens <= MAX_GENERATED_TOKENS:
            raise LocalLanguageModelError(f"max_new_tokens must be between 0 and {MAX_GENERATED_TOKENS}")
        prompt_tokens = ByteTokenizer.encode(prompt) if prompt else np.empty((0,), dtype=np.int32)
        history = [BOS_TOKEN, *(int(token) for token in prompt_tokens)]
        generated: list[int] = []
        for _ in range(max_new_tokens):
            logits, _ = self._forward(np.asarray(history[-self.context_tokens :], dtype=np.int32))
            next_token = int(np.argmax(logits[-1]))
            generated.append(next_token)
            history.append(next_token)
        return ByteTokenizer.decode(generated)

    def save(self, output: Path) -> None:
        output = Path(output)
        metadata = json.dumps({"schema": ATTENTION_SCHEMA, "d_model": self.d_model, "context_tokens": self.context_tokens, "learning_rate": self.learning_rate, "epochs": self.epochs, "seed": self.seed, "transitions": self.transitions, "model_sha256": self.model_sha256}, sort_keys=True, separators=(",", ":"))
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        with temporary.open("wb") as handle:
            np.savez_compressed(handle, **self._arrays(), metadata=np.asarray(metadata))
        temporary.replace(output)

    @classmethod
    def load(cls, checkpoint: Path) -> "CausalEmbeddingAttentionLanguageModel":
        try:
            with np.load(Path(checkpoint), allow_pickle=False) as payload:
                metadata = json.loads(str(payload["metadata"].item()))
                arrays = {name: np.asarray(payload[name], dtype=np.float32) for name in ("embedding", "position", "wq", "wk", "wv", "wo", "output", "bias")}
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise LocalLanguageModelError("invalid local-language-model checkpoint") from error
        if metadata.get("schema") != ATTENTION_SCHEMA:
            raise LocalLanguageModelError("checkpoint schema or tensor shape is incompatible")
        model = cls(d_model=metadata.get("d_model"), context_tokens=metadata.get("context_tokens"), learning_rate=float(metadata.get("learning_rate", 0.0)), epochs=metadata.get("epochs"), seed=metadata.get("seed"))
        expected = {name: value.shape for name, value in model._arrays().items()}
        if any(arrays[name].shape != expected[name] or not np.all(np.isfinite(arrays[name])) for name in expected):
            raise LocalLanguageModelError("checkpoint schema or tensor shape is incompatible")
        transitions = metadata.get("transitions")
        if not isinstance(transitions, int) or transitions <= 0:
            raise LocalLanguageModelError("checkpoint transition count is invalid")
        for name, value in arrays.items():
            setattr(model, name, np.ascontiguousarray(value))
        model.transitions = transitions
        if metadata.get("model_sha256") != model.model_sha256:
            raise LocalLanguageModelError("checkpoint model digest does not match contents")
        return model


__all__ = ["ATTENTION_SCHEMA", "CausalEmbeddingAttentionLanguageModel", "MAX_ATTENTION_CONTEXT", "MAX_ATTENTION_DIM", "MAX_ATTENTION_EPOCHS", "MAX_ATTENTION_PARAMETERS"]
