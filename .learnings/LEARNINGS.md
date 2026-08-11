# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20260810-001] correction

**Logged**: 2026-08-10T23:07:14+08:00
**Priority**: medium
**Status**: resolved
**Area**: docs

### Summary
模块对比必须严格使用用户指定的三份 Spec，不能把同目录的 `spec.md` 自动视为权威来源。

### Details
在比较 SubAgent、Worktree、Agent Team 与 mewCode 时，用户指定的输入只有 `spec_sub_agent.md`、`spec_worktree.md`、`spec_agent_team.md`。此前误将存在问题的 `spec.md` 当作新版 canonical spec，并同步修改了它，扩大了任务范围。

### Suggested Action
开始文档对比前固定 source-of-truth 清单；未被用户列入且已知有问题的文档只可忽略，不能用于推导方案或进行一致性同步。

### Metadata
- Source: user_feedback
- Related Files: spec_sub_agent.md, spec_worktree.md, spec_agent_team.md, spec.md
- Tags: scope, source-of-truth, specification

### Resolution
- **Resolved**: 2026-08-10T23:07:14+08:00
- **Notes**: 后续比较排除 spec.md；该文件随后已从工作区删除，不再恢复或修改。

---

## [LRN-20260808-001] correction

**Logged**: 2026-08-08T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: backend

### Summary
Structural designs must treat the Textual TUI as an explicit subsystem rather than hiding it behind a generic `ui` label.

### Details
The initial architecture tree listed `ui/` without defining the boundaries among the Textual application, controllers, widgets, dialogs, rendering, streaming, and command adapters. The user correctly identified that the TUI design was missing.

### Suggested Action
Use an explicit `tui/` package with documented internal layers and keep terminal presentation concerns out of application and agent domains.

### Metadata
- Source: user_feedback
- Related Files: src/Arkcode/tui
- Tags: architecture, tui, module-boundaries

### Resolution
- **Resolved**: 2026-08-08T00:00:00+08:00
- **Notes**: The architecture section was revised to include a first-class `tui/` subsystem.

---
