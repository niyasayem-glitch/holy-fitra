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
NGRAM_SCHEMA = "holyfitra.local-causal-ngram/v1"
BYTE_VOCAB_SIZE = 256
BOS_TOKEN = BYTE_VOCAB_SIZE
VOCAB_SIZE = BYTE_VOCAB_SIZE + 1
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_CORPUS_BYTES = 64 * 1024 * 1024
MAX_GENERATED_TOKENS = 16 * 1024
MAX_NGRAM_ORDER = 4
MAX_NGRAM_CONTEXTS = 32 * 1024


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
    architecture: str = "causal-bigram"
    context_tokens: int = 1
    context_rows: int = VOCAB_SIZE
    parameter_count: int = 0
    schema: str = SCHEMA

    def body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "corpus_sha256": self.corpus_sha256,
            "model_sha256": self.model_sha256,
            "documents": self.documents,
            "corpus_bytes": self.corpus_bytes,
            "transitions": self.transitions,
            "smoothing": self.smoothing,
            "tokenizer": "utf8-byte/v1",
            "vocabulary_size": VOCAB_SIZE,
            "context_tokens": self.context_tokens,
            "context_rows": self.context_rows,
            "parameter_count": self.parameter_count,
            "architecture": self.architecture,
        }


@dataclass(frozen=True)
class LocalLMEvaluationReceipt:
    corpus_sha256: str
    model_sha256: str
    documents: int
    corpus_bytes: int
    transitions: int
    mean_nll: float
    architecture: str = "causal-bigram"
    context_tokens: int = 1
    context_rows: int = VOCAB_SIZE
    parameter_count: int = 0
    schema: str = SCHEMA

    def body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "corpus_sha256": self.corpus_sha256,
            "model_sha256": self.model_sha256,
            "documents": self.documents,
            "corpus_bytes": self.corpus_bytes,
            "transitions": self.transitions,
            "mean_nll": self.mean_nll,
            "architecture": self.architecture,
            "context_tokens": self.context_tokens,
            "context_rows": self.context_rows,
            "parameter_count": self.parameter_count,
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


class CausalNgramLanguageModel:
    """A bounded sparse causal n-gram model with deterministic longest-context backoff."""

    def __init__(self, *, order: int = 2, smoothing: float = 0.1, max_contexts: int = MAX_NGRAM_CONTEXTS) -> None:
        if not isinstance(order, int) or isinstance(order, bool) or not 1 <= order <= MAX_NGRAM_ORDER:
            raise LocalLanguageModelError(f"order must be an integer between 1 and {MAX_NGRAM_ORDER}")
        if not isinstance(smoothing, (int, float)) or isinstance(smoothing, bool) or not np.isfinite(float(smoothing)) or not 0.0 < float(smoothing) <= 1.0:
            raise LocalLanguageModelError("smoothing must be finite and between 0 and 1")
        if not isinstance(max_contexts, int) or isinstance(max_contexts, bool) or not 1 <= max_contexts <= MAX_NGRAM_CONTEXTS:
            raise LocalLanguageModelError(f"max_contexts must be an integer between 1 and {MAX_NGRAM_CONTEXTS}")
        self.order = int(order)
        self.smoothing = float(smoothing)
        self.max_contexts = int(max_contexts)
        self.counts: dict[tuple[int, ...], np.ndarray] = {}
        self.transitions = 0

    @property
    def context_tokens(self) -> int:
        return self.order

    @property
    def model_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(NGRAM_SCHEMA.encode("utf-8"))
        digest.update(int(self.order).to_bytes(2, "little"))
        digest.update(repr(self.smoothing).encode("ascii"))
        digest.update(int(self.max_contexts).to_bytes(8, "little"))
        digest.update(int(self.transitions).to_bytes(8, "little", signed=False))
        for context in sorted(self.counts):
            digest.update(len(context).to_bytes(1, "little"))
            for token in context:
                digest.update(int(token).to_bytes(2, "little", signed=False))
            digest.update(self.counts[context].tobytes(order="C"))
        return digest.hexdigest()

    @staticmethod
    def _contexts(history: tuple[int, ...], order: int) -> tuple[tuple[int, ...], ...]:
        maximum = min(order, len(history))
        return tuple(history[-width:] if width else () for width in range(maximum, -1, -1))

    def _row(self, context: tuple[int, ...], table: dict[tuple[int, ...], np.ndarray]) -> np.ndarray:
        row = table.get(context)
        if row is None:
            if len(table) >= self.max_contexts:
                raise LocalLanguageModelError(f"n-gram context limit {self.max_contexts} exceeded")
            row = np.zeros((BYTE_VOCAB_SIZE,), dtype=np.uint64)
            table[context] = row
        return row

    def fit(self, texts: Iterable[str]) -> LocalLMTrainingReceipt:
        corpus_sha256, documents, corpus_bytes = _hash_texts(texts)
        table: dict[tuple[int, ...], np.ndarray] = {}
        transitions = 0
        for document in documents:
            history: tuple[int, ...] = (BOS_TOKEN,)
            for token in document:
                for context in self._contexts(history, self.order):
                    self._row(context, table)[int(token)] += 1
                transitions += 1
                history = (history + (int(token),))[-self.order :]
        if transitions <= 0:
            raise LocalLanguageModelError("training corpus has no transitions")
        self.counts = {context: np.ascontiguousarray(row) for context, row in table.items()}
        self.transitions = transitions
        return LocalLMTrainingReceipt(corpus_sha256, self.model_sha256, len(documents), corpus_bytes, transitions, self.smoothing, "causal-sparse-ngram", self.context_tokens, len(self.counts), NGRAM_SCHEMA)

    def _distribution(self, history: tuple[int, ...]) -> np.ndarray:
        distribution = np.full((BYTE_VOCAB_SIZE,), 1.0 / BYTE_VOCAB_SIZE, dtype=np.float64)
        found = False
        for context in reversed(self._contexts(history, self.order)):
            row = self.counts.get(context)
            if row is not None:
                total = float(row.sum())
                if not np.isfinite(total) or total <= 0.0:
                    raise LocalLanguageModelError("invalid n-gram probability row")
                distribution = (row.astype(np.float64) + self.smoothing * distribution) / (total + self.smoothing)
                found = True
        if not found or not np.all(np.isfinite(distribution)) or not np.isclose(float(distribution.sum()), 1.0, rtol=1e-9, atol=1e-9):
            raise LocalLanguageModelError("n-gram model has no valid matching context")
        return distribution

    def generate(self, prompt: str, *, max_new_tokens: int = 128) -> str:
        if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool) or not 0 <= max_new_tokens <= MAX_GENERATED_TOKENS:
            raise LocalLanguageModelError(f"max_new_tokens must be between 0 and {MAX_GENERATED_TOKENS}")
        prompt_tokens = ByteTokenizer.encode(prompt) if prompt else np.empty((0,), dtype=np.int32)
        history: tuple[int, ...] = ((BOS_TOKEN,) + tuple(int(token) for token in prompt_tokens))[-self.order :]
        generated: list[int] = []
        for _ in range(max_new_tokens):
            next_token = int(np.argmax(self._distribution(history)))
            generated.append(next_token)
            history = (history + (next_token,))[-self.order :]
        return ByteTokenizer.decode(generated)

    def evaluate(self, texts: Iterable[str]) -> LocalLMEvaluationReceipt:
        corpus_sha256, documents, corpus_bytes = _hash_texts(texts)
        nll = 0.0
        transitions = 0
        for document in documents:
            history: tuple[int, ...] = (BOS_TOKEN,)
            for token in document:
                probability = float(self._distribution(history)[int(token)])
                nll -= float(np.log(probability))
                transitions += 1
                history = (history + (int(token),))[-self.order :]
        if transitions <= 0 or not np.isfinite(nll):
            raise LocalLanguageModelError("evaluation did not produce a finite next-token loss")
        return LocalLMEvaluationReceipt(corpus_sha256, self.model_sha256, len(documents), corpus_bytes, transitions, nll / transitions, "causal-sparse-ngram", self.context_tokens, len(self.counts), NGRAM_SCHEMA)

    def save(self, output: Path) -> None:
        output = Path(output)
        contexts = tuple(sorted(self.counts))
        context_keys = np.asarray([list(context) + [-1] * (self.order - len(context)) for context in contexts], dtype=np.int16)
        context_lengths = np.asarray([len(context) for context in contexts], dtype=np.int16)
        counts = np.stack([self.counts[context] for context in contexts])
        metadata = json.dumps({"schema": NGRAM_SCHEMA, "order": self.order, "smoothing": self.smoothing, "max_contexts": self.max_contexts, "transitions": self.transitions, "model_sha256": self.model_sha256}, sort_keys=True, separators=(",", ":"))
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        with temporary.open("wb") as handle:
            np.savez_compressed(handle, context_keys=context_keys, context_lengths=context_lengths, counts=counts, metadata=np.asarray(metadata))
        temporary.replace(output)

    @classmethod
    def load(cls, checkpoint: Path) -> "CausalNgramLanguageModel":
        try:
            with np.load(Path(checkpoint), allow_pickle=False) as payload:
                metadata = json.loads(str(payload["metadata"].item()))
                context_keys = np.asarray(payload["context_keys"], dtype=np.int16)
                context_lengths = np.asarray(payload["context_lengths"], dtype=np.int16)
                counts = np.asarray(payload["counts"], dtype=np.uint64)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise LocalLanguageModelError("invalid local-language-model checkpoint") from error
        if metadata.get("schema") != NGRAM_SCHEMA:
            raise LocalLanguageModelError("checkpoint schema or tensor shape is incompatible")
        model = cls(order=metadata.get("order"), smoothing=float(metadata.get("smoothing", 0.0)), max_contexts=metadata.get("max_contexts"))
        if context_keys.ndim != 2 or context_keys.shape[1] != model.order or context_lengths.shape != (context_keys.shape[0],) or counts.shape != (context_keys.shape[0], BYTE_VOCAB_SIZE) or not 1 <= context_keys.shape[0] <= model.max_contexts:
            raise LocalLanguageModelError("checkpoint schema or tensor shape is incompatible")
        table: dict[tuple[int, ...], np.ndarray] = {}
        for key, length, row in zip(context_keys, context_lengths, counts, strict=True):
            width = int(length)
            if not 0 <= width <= model.order or np.any(key[:width] < 0) or np.any(key[:width] >= VOCAB_SIZE) or np.any(key[width:] != -1):
                raise LocalLanguageModelError("checkpoint context encoding is invalid")
            context = tuple(int(token) for token in key[:width])
            if context in table:
                raise LocalLanguageModelError("checkpoint contains duplicate contexts")
            table[context] = np.ascontiguousarray(row)
        transitions = metadata.get("transitions")
        if not isinstance(transitions, int) or transitions <= 0:
            raise LocalLanguageModelError("checkpoint transition count is invalid")
        model.counts = table
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


def load_local_language_model(checkpoint: Path) -> object:
    try:
        with np.load(Path(checkpoint), allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"].item()))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        raise LocalLanguageModelError("invalid local-language-model checkpoint") from error
    schema = metadata.get("schema")
    if schema == SCHEMA:
        return CausalBigramLanguageModel.load(checkpoint)
    if schema == NGRAM_SCHEMA:
        return CausalNgramLanguageModel.load(checkpoint)
    from holyfitra_attention_lm import ATTENTION_SCHEMA, CausalEmbeddingAttentionLanguageModel
    if schema == ATTENTION_SCHEMA:
        return CausalEmbeddingAttentionLanguageModel.load(checkpoint)
    raise LocalLanguageModelError("checkpoint schema is unsupported")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Holy Fitra byte-level causal language-model baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train")
    train.add_argument("corpus", nargs="+", type=Path)
    train.add_argument("--output", required=True, type=Path)
    train.add_argument("--architecture", choices=["ngram", "attention"], default="ngram", help="bounded local model family")
    train.add_argument("--smoothing", type=float, default=0.1)
    train.add_argument("--order", type=int, default=1, help=f"causal context tokens: 1 for bigram, 2-{MAX_NGRAM_ORDER} for sparse n-gram")
    train.add_argument("--max-contexts", type=int, default=MAX_NGRAM_CONTEXTS, help="upper bound for sparse n-gram contexts")
    train.add_argument("--d-model", type=int, default=16, help="attention embedding width")
    train.add_argument("--context-tokens", type=int, default=16, help="attention causal context limit")
    train.add_argument("--learning-rate", type=float, default=0.05, help="attention SGD learning rate")
    train.add_argument("--epochs", type=int, default=4, help="attention training epochs")
    train.add_argument("--seed", type=int, default=17, help="attention initialization seed")
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
            if arguments.architecture == "attention":
                from holyfitra_attention_lm import CausalEmbeddingAttentionLanguageModel
                model = CausalEmbeddingAttentionLanguageModel(d_model=arguments.d_model, context_tokens=arguments.context_tokens, learning_rate=arguments.learning_rate, epochs=arguments.epochs, seed=arguments.seed)
            else:
                model = CausalBigramLanguageModel(smoothing=arguments.smoothing) if arguments.order == 1 else CausalNgramLanguageModel(order=arguments.order, smoothing=arguments.smoothing, max_contexts=arguments.max_contexts)
            receipt = model.fit(_read_documents(arguments.corpus))
            model.save(arguments.output)
            print(json.dumps({"ok": True, "checkpoint": str(arguments.output), "receipt": receipt.body()}, sort_keys=True))
            return 0
        model = load_local_language_model(arguments.checkpoint)
        if arguments.command == "generate":
            print(json.dumps({"ok": True, "model_sha256": model.model_sha256, "text": model.generate(arguments.prompt, max_new_tokens=arguments.max_new_tokens)}, sort_keys=True))
            return 0
        receipt = model.evaluate(_read_documents(arguments.corpus))
        print(json.dumps({"ok": True, "receipt": receipt.body()}, sort_keys=True))
        return 0
    except LocalLanguageModelError as error:
        print(f"holyfitra-local-lm: error: {error}")
        return 1


__all__ = ["BOS_TOKEN", "BYTE_VOCAB_SIZE", "CausalBigramLanguageModel", "CausalNgramLanguageModel", "ByteTokenizer", "LocalLMEvaluationReceipt", "LocalLMTrainingReceipt", "LocalLanguageModelError", "NGRAM_SCHEMA", "SCHEMA", "VOCAB_SIZE", "load_local_language_model"]


if __name__ == "__main__":
    raise SystemExit(main())
