# Archive

Historical records live here so current-source docs stay focused on the implementation state, backlog, and release evidence.

| Document | Purpose |
|---|---|
| [backend-test-audit.md](backend-test-audit.md) | Backend test coverage audit and strengthening notes (2026-05-30 snapshot). |
| [release-quality-review-slices.md](release-quality-review-slices.md) | Release-quality evidence slices and sign-off checklist for the release-candidate gate branch. |
| [doc-conflict-audit.md](doc-conflict-audit.md) | Historical document conflict audit and fix trail. |
| [fix-roadmap.md](fix-roadmap.md) | Historical review consolidation and decisions. |
| [FRONTEND_PROMPT.md](FRONTEND_PROMPT.md) | Initial frontend implementation brief; superseded by `../../frontend/README.md` (API contract) and `../../DESIGN.md` (design system). |
| [CI_FAILURE_FIX.md](CI_FAILURE_FIX.md) | 一次性 CI 失败修复记录。 |
| [CI_MONITORING_PLAN.md](CI_MONITORING_PLAN.md) | CI 监控计划快照；当前 CI 协议见根目录 CLAUDE.md。 |
| [REFACTORING_CHECKLIST.md](REFACTORING_CHECKLIST.md) | 一次性重构检查清单快照。 |

Do not use archived files as live status without checking `../architecture.md`, `../feature-catalog.md`, `../TODO.md`, and current test evidence first.

---

## 2026-09-22 清理说明

删除了 14 份自评类快照：三份第一性原理分析与 PRD 重审、两份工作总结、一份文档健康检查报告、四份文档治理计划与调研，以及 `reviews/2026-06-09/` 整个目录。

它们的共同问题是记录了当时的**结论**而非事实——健康度打分（4.3 / 4.7 / 4.8 / 77 分，四套口径互相矛盾）、"上线就绪 ✅"、"验证 10/10"。这类结论在写下的那一刻可能成立，之后每一次改动都让它更不准，而读者无从判断它何时失效。2026-09 的实测发现文档标着"上线就绪"时有五个端点 100% 崩溃，就是这么来的。

需要回溯某次决策，看对应 commit message 的 trailer（`Constraint:` / `Rejected:` / `Tested:` / `Not-tested:`）。那些记录与代码同生共死，不会单独腐败。
