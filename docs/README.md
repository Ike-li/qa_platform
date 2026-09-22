# Documentation Index

This directory has a few kinds of documents. Keep new material in the right lane so status, evidence, task packages, and historical notes do not drift into each other.

## Current Sources

Use these first when deciding current behavior or implementation scope:

| Document | Purpose |
|---|---|
| [architecture.md](architecture.md) | Runtime architecture, layer boundaries, execution lifecycle, storage, security, and operations contracts. |
| [feature-catalog.md](feature-catalog.md) | Current feature status, PRD ID mapping, accepted gaps, and implementation notes. |
| [product.md](product.md) | Product target, roadmap, and pilot Beta/GA boundary (§9). Treat the roadmap as target state; current implementation is proven by `feature-catalog.md` and `TODO.md`. |
| [TODO.md](TODO.md) | Active backlog and remaining acceptance gaps. |
| [development.md](development.md) | Local setup, service startup, and developer test commands. |
| [runbook.md](runbook.md) | Operator procedures for incidents, key rotation, lifecycle policies, and production hardening. |
| [testing-strategy.md](testing-strategy.md) | Test layering rules, quality gate policy, warning registry, flaky handling, and regression process. |

## Evidence And Audit Logs

These record verification history. They are not the primary source for current product scope:

| Document | Purpose |
|---|---|
| [ui-test-checklist.md](ui-test-checklist.md) | UI verification checklist; release acceptance still requires linked commands, screenshots, or CI artifacts. |

## Task Packages

| Document | Purpose |
|---|---|
| [tasks/README.md](tasks/README.md) | Task-package index for self-contained implementation tasks. |

## Archive

These files are retained as historical evidence. Do not use them as live implementation status without checking the current sources first:

| Document | Purpose |
|---|---|


## Maintenance Rules

- Current truth lives in `architecture.md`, `feature-catalog.md`, `product.md`, `TODO.md`, `development.md`, `runbook.md`, and `testing-strategy.md`.
- New task packages go under `docs/tasks/` and must update [tasks/README.md](tasks/README.md).
- Generated local artifacts stay out of docs unless they are linked from a repeatable command, CI artifact, or explicit release-evidence entry.
- Tests verify product behavior, not documentation wording. Do not add meta-tests that pin doc strings or other test files' source text; see `AGENTS.md` and `testing-strategy.md`.
