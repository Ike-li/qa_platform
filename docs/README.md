# Documentation Index

This directory has three kinds of documents. Keep new material in the right lane so status, evidence, and historical notes do not drift into each other.

## Current Sources

Use these first when deciding current behavior or implementation scope:

| Document | Purpose |
|---|---|
| [architecture.md](architecture.md) | Runtime architecture, layer boundaries, execution lifecycle, storage, security, and operations contracts. |
| [feature-catalog.md](feature-catalog.md) | Current feature status, PRD ID mapping, accepted gaps, and implementation notes. |
| [product-status.md](product-status.md) | Current Beta/GA pilot boundary, target user, committed and non-committed product capabilities, and success metrics. |
| [TODO.md](TODO.md) | Active backlog and remaining acceptance gaps. |
| [development.md](development.md) | Local setup, service startup, and developer test commands. |
| [runbook.md](runbook.md) | Operator procedures for incidents, key rotation, lifecycle policies, and production hardening. |
| [testing-strategy.md](testing-strategy.md) | Test layering rules, quality gate policy, warning registry, flaky handling, and regression process. |

## Evidence And Audit Logs

These explain why decisions were made or record verification history. They are not the primary source for current product scope:

| Document | Purpose |
|---|---|
| [backend-test-audit.md](backend-test-audit.md) | Backend test coverage audit and strengthening notes. |
| [release-quality-review-slices.md](release-quality-review-slices.md) | Release-quality evidence slices and sign-off checklist. |
| [ui-test-checklist.md](ui-test-checklist.md) | UI verification checklist; release acceptance still requires linked commands, screenshots, or CI artifacts. |
| [project-memory.md](project-memory.md) | Short handoff memory for the current repository state, latest commits, and verified commands. |

## Product And Historical Planning

These are useful context, but they can be ahead of or behind `main`:

| Document | Purpose |
|---|---|
| [prd.md](prd.md) | Product target and roadmap. Treat as target state, not proof of current implementation. |
| [tasks/README.md](tasks/README.md) | Task-package index for self-contained implementation tasks. |

## Archive

These files are retained as historical evidence. Do not use them as live implementation status without checking the current sources first:

| Document | Purpose |
|---|---|
| [archive/doc-conflict-audit.md](archive/doc-conflict-audit.md) | Historical document conflict audit and fix trail. |
| [archive/fix-roadmap.md](archive/fix-roadmap.md) | Historical review consolidation and decisions. Do not use as active backlog without checking `TODO.md`. |

## Maintenance Rules

- Current truth lives in `architecture.md`, `feature-catalog.md`, `product-status.md`, `TODO.md`, `development.md`, `runbook.md`, and `testing-strategy.md`.
- Historical audit documents belong under `archive/`; they may explain old wording, but they must not be used as live status without checking the current sources.
- New task packages go under `docs/tasks/` and must update [tasks/README.md](tasks/README.md).
- Generated local artifacts stay out of docs unless they are linked from a repeatable command, CI artifact, or explicit release-evidence entry.
