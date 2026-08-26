"""Deterministic local token-language-model baseline for Holy Fitra.

This module deliberately implements a small byte-level causal bigram model. It is
not a transformer and must never be presented as comparable to Qwen-class
models. Its role is to make the first missing language-model contracts explicit:
tokenization, causal next-token training, checkpoint identity, deterministic
generation, and replayable evaluation receipts.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np


SCHEMA = "holyfitra.local-causal-bigram/v1"
BYTE_VOCAB_SIZE = 256
BOS_TOKEN = BYTE_VOCAB_SIZE
VOCAB_SIZE = BYTE_VOCAB_SIZE + 1
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_CORPUS_BYTES = 64 * 1024 * 1024
MAX_GENERATED_TOKENS = 16 * 1024


class LocalLanguageModelError(ValueError):
    """A local-language-model input, checkpoint, or receipt is invalid."""


class ByteTokenizer:
    """A deterministic UTF-8 byte tokenizer with one reserved begin token."""

    vocabulary_size = VOCAB_SIZE
    bos_token = BOS_TOKEN

    @staticmethod
    def encode(text: str) -> np.ndarray:
        if not isinstance(text, str):
            raise LocalLanguageModelError("tokenizer input must be text")
        encoded = text.encode("utf-8")
        if not encoded:
            raise LocalLanguageModelError("tokenizer input must not be empty")
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise LocalLanguageModelError(f"document exceeds {MAX_DOCUMENT_BYTES} byte limit")
        return np.frombuffer(encoded, dtype=np.uint8).astype(np.int32, copy=True)

    @staticmethod
    def decode(tokens: Iterable[int]) -> str:
        values = tuple(int(token) for token in tokens)
        if any(token < 0 or token >= BYTE_VOCAB_SIZE for token in values):
            raise LocalLanguageModelError("decoded tokens must be byte vocabulary values")
        return bytes(values).decode("utf-8", errors="replace")


def _hash_texts(texts: Iterable[str]) -> tuple[str, tuple[np.ndarray, ...], int]:
    digest = hashlib.sha256()
    tokens: list[np.ndarray] = []
    total_bytes = 0
    for index, text in enumerate(texts):
        if not isinstance(text, str):
            raise LocalLanguageModelError(f"document {index} must be text")
        encoded = ByteTokenizer.encode(text)
        total_bytes += int(encoded.size)
        if total_bytes > MAX_CORPUS_BYTES:
            raise LocalLanguageModelError(f"corpus exceeds {MAX_CORPUS_BYTES} byte limit")
        raw = text.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "little"))
        digest.update(raw)
        tokens.append(encoded)
    if not tokens:
        raise LocalLanguageModelError("training or evaluation corpus must not be empty")
    return digest.hexdigest(), tuple(tokens), total_bytes


@dataclass(frozen=True)
class LocalLMTrainingReceipt:
    corpus_sha256: str
    model_sha256: str
    documents: int
    corpus_bytes: int
    transitions: int
    smoothing: float

    def body(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "corpus_sha256": self.corpus_sha256,
            "model_sha256": self.model_sha256,
            "documents": self.documents,
            "corpus_bytes": self.corpus_bytes,
            "transitions": self.transitions,
            "smoothing": self.smoothing,
            "tokenizer": "utf8-byte/v1",
            "vocabulary_size": VOCAB_SIZE,
            "context_tokens": 1,
            "architecture": "causal-bigram",
        }


@dataclass(frozen=True)
class LocalLMEvaluationReceipt:
    corpus_sha256: str
    model_sha256: str
    documents: int
    corpus_bytes: int
    transitions: int
    mean_nll: float

    def body(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "corpus_sha256": self.corpus_sha256,
            "model_sha256": self.model_sha256,
            "documents": self.documents,
            "corpus_bytes": self.corpus_bytes,
            "transitions": self.transitions,
            "mean_nll": self.mean_nll,
        }


class CausalBigramLanguageModel:
    """A finite, causal next-token model with deterministic greedy generation."""

    def __init__(self, *, smoothing: float = 0.1) -> None:
        if not isinstance(smoothing, (int, float)) or isinstance(smoothing, bool) or not np.isfinite(float(smoothing)) or not 0.0 < float(smoothing) <= 1.0:
            raise LocalLanguageModelError("smoothing must be finite and between 0 and 1")
        self.smoothing = float(smoothing)
        self.counts = np.zeros((VOCAB_SIZE, BYTE_VOCAB_SIZE), dtype=np.uint64)
        self.transitions = 0

    @property
    def model_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(SCHEMA.encode("utf-8"))
        digest.update(repr(self.smoothing).encode("ascii"))
        digest.update(self.counts.tobytes(order="C"))
        digest.update(int(self.transitions).to_bytes(8, "little", signed=False))
        return digest.hexdigest()

    def fit(self, texts: Iterable[str]) -> LocalLMTrainingReceipt:
        corpus_sha256, documents, corpus_bytes = _hash_texts(texts)
        counts = np.zeros_like(self.counts)
        transitions = 0
        for document in documents:
            previous = BOS_TOKEN
            for token in document:
                counts[previous, int(token)] += 1
                transitions += 1
                previous = int(token)
        if transitions <= 0:
            raise LocalLanguageModelError("training corpus has no transitions")
        self.counts = counts
        self.transitions = transitions
        return LocalLMTrainingReceipt(corpus_sha256, self.model_sha256, len(documents), corpus_bytes, transitions, self.smoothing)

    def _distribution(self, previous: int) -> np.ndarray:
        if not 0 <= previous < VOCAB_SIZE:
            raise LocalLanguageModelError("previous token is outside the tokenizer vocabulary")
        row = self.counts[previous].astype(np.float64) + self.smoothing
        total = float(row.sum())
        if not np.isfinite(total) or total <= 0.0:
            raise LocalLanguageModelError("invalid local-model probability row")
        return row / total

    def generate(self, prompt: str, *, max_new_tokens: int = 128) -> str:
        if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool) or not 0 <= max_new_tokens <= MAX_GENERATED_TOKENS:
            raise LocalLanguageModelError(f"max_new_tokens must be between 0 and {MAX_GENERATED_TOKENS}")
        prompt_tokens = ByteTokenizer.encode(prompt) if prompt else np.empty((0,), dtype=np.int32)
        previous = int(prompt_tokens[-1]) if prompt_tokens.size else BOS_TOKEN
        generated: list[int] = []
        for _ in range(max_new_tokens):
            next_token = int(np.argmax(self._distribution(previous)))
            generated.append(next_token)
            previous = next_token
        return ByteTokenizer.decode(generated)

    def evaluate(self, texts: Iterable[str]) -> LocalLMEvaluationReceipt:
        corpus_sha256, documents, corpus_bytes = _hash_texts(texts)
        nll = 0.0
        transitions = 0
        for document in documents:
            previous = BOS_TOKEN
            for token in document:
                probability = float(self._distribution(previous)[int(token)])
                nll -= float(np.log(probability))
                transitions += 1
                previous = int(token)
        if transitions <= 0 or not np.isfinite(nll):
            raise LocalLanguageModelError("evaluation did not produce a finite next-token loss")
        return LocalLMEvaluationReceipt(corpus_sha256, self.model_sha256, len(documents), corpus_bytes, transitions, nll / transitions)

    def save(self, output: Path) -> None:
        output = Path(output)
        if not output.name:
            raise LocalLanguageModelError("checkpoint output must have a file name")
        metadata = json.dumps({"schema": SCHEMA, "smoothing": self.smoothing, "transitions": self.transitions, "model_sha256": self.model_sha256}, sort_keys=True, separators=(",", ":"))
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        with temporary.open("wb") as handle:
            np.savez_compressed(handle, counts=self.counts, metadata=np.asarray(metadata))
        temporary.replace(output)

    @classmethod
    def load(cls, checkpoint: Path) -> "CausalBigramLanguageModel":
        try:
            with np.load(Path(checkpoint), allow_pickle=False) as payload:
                metadata = json.loads(str(payload["metadata"].item()))
                counts = np.asarray(payload["counts"], dtype=np.uint64)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise LocalLanguageModelError("invalid local-language-model checkpoint") from error
        if metadata.get("schema") != SCHEMA or counts.shape != (VOCAB_SIZE, BYTE_VOCAB_SIZE):
            raise LocalLanguageModelError("checkpoint schema or tensor shape is incompatible")
        model = cls(smoothing=float(metadata.get("smoothing", 0.0)))
        transitions = metadata.get("transitions")
        if not isinstance(transitions, int) or transitions <= 0:
            raise LocalLanguageModelError("checkpoint transition count is invalid")
        model.counts = np.ascontiguousarray(counts)
        model.transitions = transitions
        if metadata.get("model_sha256") != model.model_sha256:
            raise LocalLanguageModelError("checkpoint model digest does not match contents")
        return model


def _read_documents(paths: Iterable[Path]) -> tuple[str, ...]:
    documents: list[str] = []
    for path in paths:
        try:
            documents.append(Path(path).read_text(encoding="utf-8"))
        except OSError as error:
            raise LocalLanguageModelError(f"cannot read corpus file {path}") from error
    return tuple(documents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Holy Fitra byte-level causal language-model baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train")
    train.add_argument("corpus", nargs="+", type=Path)
    train.add_argument("--output", required=True, type=Path)
    train.add_argument("--smoothing", type=float, default=0.1)
    generate = commands.add_parser("generate")
    generate.add_argument("checkpoint", type=Path)
    generate.add_argument("prompt")
    generate.add_argument("--max-new-tokens", type=int, default=128)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("checkpoint", type=Path)
    evaluate.add_argument("corpus", nargs="+", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "train":
            model = CausalBigramLanguageModel(smoothing=arguments.smoothing)
            receipt = model.fit(_read_documents(arguments.corpus))
            model.save(arguments.output)
            print(json.dumps({"ok": True, "checkpoint": str(arguments.output), "receipt": receipt.body()}, sort_keys=True))
            return 0
        model = CausalBigramLanguageModel.load(arguments.checkpoint)
        if arguments.command == "generate":
            print(json.dumps({"ok": True, "model_sha256": model.model_sha256, "text": model.generate(arguments.prompt, max_new_tokens=arguments.max_new_tokens)}, sort_keys=True))
            return 0
        receipt = model.evaluate(_read_documents(arguments.corpus))
        print(json.dumps({"ok": True, "receipt": receipt.body()}, sort_keys=True))
        return 0
    except LocalLanguageModelError as error:
        print(f"holyfitra-local-lm: error: {error}")
        return 1


__all__ = ["BOS_TOKEN", "BYTE_VOCAB_SIZE", "CausalBigramLanguageModel", "ByteTokenizer", "LocalLMEvaluationReceipt", "LocalLMTrainingReceipt", "LocalLanguageModelError", "SCHEMA", "VOCAB_SIZE"]


if __name__ == "__main__":
    raise SystemExit(main())
