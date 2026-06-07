# Methodology evolution timeline (v3.0 → v3.11)

> **What this doc is.** A chronological catalogue of the invariant testing
> methodology dimensions that this project has industrialized. Each "vX.Y"
> entry marks the launch (or sub-pattern split) of a methodology dimension.
> Read this when you want to understand "why does this codebase have so
> many `tests/test_feat_*_invariant_*.py` files" or when proposing a new
> methodology dimension.
>
> **简体中文版本**: [`methodology-evolution.zh-CN.md`](methodology-evolution.zh-CN.md).

## Overview

| Dimension | Launch cycle | Anchor R# | Status (cycle-51) | Applications |
| --------- | ------------ | --------- | ----------------- | ------------ |
| v3.0      | cycle-1      | various   | Foundation        | 100+         |
| v3.1      | cycle-19     | R178      | Industrialized    | 8+           |
| v3.2      | cycle-21     | R210      | Industrialized    | 6+           |
| v3.3      | cycle-23     | R230      | Industrialized    | 6+           |
| v3.4      | cycle-25     | R260      | Industrialized    | 5+           |
| v3.5      | cycle-27     | R287      | Industrialized    | 5+           |
| v3.6      | cycle-29     | R296      | Fully industrialized | 9+        |
| v3.7      | cycle-31     | R306      | Industrialized    | 4+           |
| v3.8      | cycle-32     | R313      | Industrialized    | 6+           |
| v3.9      | cycle-35     | R326      | Industrialized    | 6+           |
| v3.10.1   | cycle-46     | R404      | Industrialized    | 2+           |
| v3.10.2   | cycle-47     | R412      | Industrialized    | 3+           |
| v3.10.3   | cycle-48     | R422      | Industrialized    | 5+           |
| **v3.11** | **cycle-47** (R414 1st app) → **cycle-51 (formal naming)** | **R414 → R448** | **Fully industrialized (deepening)** | **13+** |

## v3.11 — Meta-invariant layer (元方法学层)

**Status (cycle-52)**: Fully industrialized (deepening) — 13 applications, 5 sub-patterns (Ratchet validation / doc-parity / API contract / i18n / Mixin matrix).

### Definition

A **meta-invariant** is an invariant that protects another invariant from
silent decay. It uses synthetic inputs (drift scenarios) to prove that the
target invariant's helper functions correctly fire when expected. This
guards against refactors that silently break the target's detection logic
while leaving the test PASSING.

### Sub-patterns (cycle-51)

| Sub-pattern        | 1st app  | Cycle | Apps | Guards                                                     |
| ------------------ | -------- | ----- | ---- | ---------------------------------------------------------- |
| Ratchet validation | R418     | 47    | 7    | R412/R422 ratchet uplifts (R418/R426/R428/R432/R436/R440/R446) |
| doc-parity         | R424     | 48    | 1    | R335/R340/R346/R400/R408/R394                              |
| API contract       | R430     | 49    | 1    | R404 (endpoint summary)                                    |
| **i18n**           | **R438** | **50**| **3**| **R350 (R438) / R353 (R442) / R366 (R448)**                |
| Mixin matrix       | R414     | 47    | 1    | R406 (Mixin route registration matrix)                     |

**13 applications** = (Ratchet validation 7) + (doc-parity 1) + (API contract 1) + (i18n 3) + (Mixin matrix 1).

### Industrialization milestones

- **Initial (1 app)**: cycle-47, R414 launches Mixin matrix negative validation
- **2nd app**: cycle-47, R418 launches Ratchet validation sub-pattern
- **3rd app (industrialization)**: cycle-48, R424 launches doc-parity sub-pattern
- **6th app (multi-sub-pattern)**: cycle-49, R430 launches API contract sub-pattern
- **9th app (complete-industrialization)**: cycle-50, R438 launches i18n sub-pattern (4 sub-patterns)
- **11th app (deepening)**: cycle-51, R442 strengthens i18n sub-pattern to 2 apps
- **13th app (further deepening)**: cycle-52, R448 strengthens i18n sub-pattern to 3 apps (industrialization threshold)

### Design principles

1. **Synthetic inputs, not real codebase**: Meta-invariants use hand-crafted
   drift scenarios, not the real codebase, to avoid coupling between meta
   and target invariants.
2. **4-layer structure**:
   - Layer 1: synthetic drift detection (positive fire case)
   - Layer 2: synthetic ceiling tolerance (negative fire case)
   - Layer 3: helper edge case smoke (e.g., `_meta` filtering)
   - Layer 4: lineage + milestone marker
3. **Sub-pattern split by guarded dimension**: Each sub-pattern protects a
   specific methodology dimension. New sub-patterns emerge when meta-invariant
   pattern extends to a new dimension (e.g., R424 → doc-parity, R430 → API
   contract, R438 → i18n).

## See also

- [`contributor-guide-invariant-tests.md`](contributor-guide-invariant-tests.md)
  — full invariant test pattern catalogue
- [`code-reviews/`](code-reviews/) — cycle-by-cycle code reviews including
  pattern industrialization milestones
- [`lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md) —
  why silent decay defeats normal review (foundational read for understanding
  why meta-invariants exist)
