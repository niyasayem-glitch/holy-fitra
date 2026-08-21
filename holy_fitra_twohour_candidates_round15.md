# Breakthrough Round 15 — Android-Oriented Tiered Memory Residency

Round 15 targets the software boundary around Android big.LITTLE and thermal-aware execution. The sandbox cannot observe real Android thermal sensors, so the selected design uses explicit host-provided pressure and thermal hints to manage residency of shared tensors safely.

| Rank | Candidate | Potential breakthrough | Risk | Decision |
|---:|---|---|---|---|
| 1 | Tiered residency manager over shared tensor pool | Evict/demote cold shared tensors under pressure while pinning hot ones | Medium | **Selected** |
| 2 | Thermal-aware cache demotion | Reclaim memory before thermal throttling | Medium | Defer |
| 3 | Big.LITTLE memory-affinity hints | Better native placement | High/device-dependent | Defer |
| 4 | Query-aware weight prefetch | Hide reconstruction latency | Medium | Defer |
| 5 | Pressure-triggered float32→float16 demotion | Lower resident bytes | Medium | Defer |
| 6 | Shared-pool LRU eviction | General memory pressure control | Medium | Defer |
| 7 | Pinned hot-layer leases | Avoid thrashing | Low/medium | Defer |
| 8 | Arena compaction | Reduce fragmentation | High alias risk | Defer |
| 9 | Android ashmem/HardwareBuffer bridge | Physical zero-copy bridge | High/platform-specific | Defer |
| 10 | Thermal hysteresis controller | Avoid oscillating residency | Medium | Defer |
| 11 | Native page-fault telemetry | Better device diagnosis | High | Defer |
| 12 | Memory-budget admission control | Prevent OOM | Low | Defer |
| 13 | Model-layer priority tiers | Preserve critical weights | Low/medium | Defer |
| 14 | GPU/NNAPI shared allocation | Device acceleration | High and unavailable here | Defer |
| 15 | Hardware-coherent unified RAM | True Apple-style physical behavior | Impossible in sandbox | Reject |

## Selection and retention rule

Implement a deterministic residency manager that tracks handles, access frequency, last-use timestamps, priority, pin state, pressure level, and thermal hint. It may release only unpinned cold handles, reports pressure/thermal decisions, and never mutates or silently invalidates a live handle. Retain only if it reclaims shared-pool bytes, preserves hot/pinned tensors, avoids thrashing through hysteresis, and passes all existing gates. Device claims remain explicitly unverified.

## Round 15 implementation and evidence

Implemented `holyfitra_residency.py`, a deterministic tiered residency manager over the shared tensor pool. It tracks hot/warm/cold/evicted tiers, access count, last-use timestamps, priorities, pin state, active leases, pressure hints, and caller-provided thermal labels. Rebalancing uses hysteresis: nominal pressure does nothing; warm/critical hints reclaim only cold, unpinned, unleased records. Hot and pinned records are preserved, and active leases defer eviction until release.

The focused round 15 suite passes **5 tests**; the complete applicable suite passes **131 tests with 0 failures**. Termux-compatible host validation, AArch64 object emission, ragged scalar/NEON/SVE checks, scheduler validation, and ASAN/UBSAN native gates pass.

In the x86-64 sandbox benchmark, three 1,024-byte tensors occupied 3,072 physical bytes. Under critical pressure, a cold unleased tensor was reclaimed after a lease-protected first pass, reducing physical bytes to 2,048 and reclaiming **1,024 bytes**. The hot tensor remained hot, the pinned tensor remained resident, and the active lease continued to read valid data. Thermal hints are explicit inputs; no physical Android sensor was queried.

## Round 15 retention decision

Retain the tiered residency manager. It provides a software analogue of Android-oriented memory pressure management while preserving ownership and active-use safety. It does not claim physical unified RAM, actual thermal sensing, big.LITTLE placement, or device-level Android validation.
