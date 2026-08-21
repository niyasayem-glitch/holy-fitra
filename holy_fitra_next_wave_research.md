# Holy Fitra Next-Wave Research Findings

## Ownership and borrowing

Rust’s ownership model makes one component responsible for a value, while references borrow without taking ownership. Immutable references may coexist, but a mutable reference is exclusive. References must remain valid and cannot outlive their owned data. Holy Fitra should adapt these rules to tensor buffers, KV-cache generations, scheduler task metadata, consent tokens, reversible receipts, and JNI direct buffers. The first safe implementation should be an explicit metadata layer (`owned`, `borrow`, `borrow_mut`, `shared`) with diagnostics before a full lifetime checker is attempted.

Source: [Rust References and Borrowing](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)

## Algebraic data types

Haskell’s algebraic data types combine sum types, where a value is one of several alternatives, and product types, where a value contains multiple fields. This maps naturally to Holy Fitra’s uncertainty and safety domain: `Prediction | Claim | Fact`, `Ok(value) | Err(error)`, `Some(value) | None`, and runtime states such as `Ready | Running | Cancelled | Failed`. The compiler should eventually require exhaustive matching over these closed variants.

Source: [HaskellWiki: Algebraic Data Type](https://www.haskell.org/haskellwiki/algebraic_data_type)

## Structured concurrency

Swift’s structured concurrency model makes child tasks belong to a parent scope. Child tasks must finish or be cancelled before the parent scope exits. Task priority, cancellation, task-local context, and deadlines can propagate through the hierarchy. Holy Fitra should use this model for speculative decoding, ragged attention requests, JNI work, Android scheduler tasks, and AI-agent tool calls. Detached work should require an explicit unsafe/effect annotation.

Sources: [Swift Concurrency](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/) and [Swift Structured Concurrency Proposal SE-0304](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0304-structured-concurrency.md)

## Selected implementation wave

1. Add a typed `Result<T,E>` and `Option<T>` contract layer to the frontend/runtime without destabilizing the existing scalar ABI.
2. Add ownership-mode annotations and static duplicate/mutation checks for function signatures and local declarations.
3. Add an explicit `task`/`await` metadata model with bounded capacity, cancellation, deadline, priority, and parent scope.
4. Add `supervisor` metadata for restart/fallback policy, mapped to the existing self-healing proof and thermal fallback runtime.
5. Add effect propagation through call graphs, rejecting a caller that lacks the callee’s required effects.
6. Add a typed AI kernel contract that records dtype, device, layout, quantization proof, memory budget, energy budget, and fallback precision.

## Safety boundaries

The next wave will not add unrestricted macros, hidden threads, implicit network access, silent quantization, or a fake lifetime checker. Each feature will begin as explicit metadata with diagnostics and runtime contracts, then gain deeper lowering only after regression coverage exists.
