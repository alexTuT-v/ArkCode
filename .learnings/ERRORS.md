# Errors

Command failures and integration errors.

---

## [ERR-20260810-009] unified-plan-multi-hunk-context

**Logged**: 2026-08-10T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
A unified Plan patch failed atomically because one cleanup hunk expected a duplicate list item that had already been removed.

### Error
`apply_patch verification failed: Failed to find expected lines in plan.md`

### Context
- The failed patch grouped independent architecture, model, and cleanup edits.
- A second occurrence came from treating overlapping range output as a duplicated source line.
- No part of the failed patch was applied.

### Suggested Fix
Patch independently reviewable Plan sections in separate operations after reading their current ranges.

### Metadata
- Reproducible: yes
- Related Files: plan.md
- Recurrence-Count: 3
- First-Seen: 2026-08-10
- Last-Seen: 2026-08-10

### Resolution
- **Resolved**: 2026-08-10T00:00:00+08:00
- **Commit/PR**: none
- **Notes**: Continued using small exact-context patches.

---

## [ERR-20260810-008] markdown-backticks-in-shell-verifier

**Logged**: 2026-08-10T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
A read-only spec verification command allowed Markdown backticks inside shell double quotes, causing unintended command substitution.

### Error
`zsh: command not found` for Markdown code-span contents such as `Explore` and `os.chdir`.

### Context
- The command was only reading spec files with `rg`; no target document was modified.
- The verification process exited non-zero before producing a valid pass result.
- The first retry also overfit its assertions:it treated the deliberately invalid `Explore` acceptance example as a live role-name residue and required an exact spacing variant.

### Suggested Fix
Use single-quoted fixed-string patterns for Markdown text containing backticks, and avoid nesting an extra `zsh -c` layer.

### Metadata
- Reproducible: yes
- Related Files: spec_sub_agent.md, spec_worktree.md, spec_agent_team.md
- Recurrence-Count: 2
- First-Seen: 2026-08-10
- Last-Seen: 2026-08-10

### Resolution
- **Resolved**: 2026-08-10T00:00:00+08:00
- **Commit/PR**: none
- **Notes**: Re-ran the verifier with fixed-string, single-quoted patterns.

---

## [ERR-20260810-007] spec-patch-context-mismatch

**Logged**: 2026-08-10T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
Multi-hunk spec patches failed atomically because expected requirement lines did not exactly match the current documents.

### Error
`apply_patch verification failed: Failed to find expected lines`

### Context
- The attempted patch combined goals, functional requirements, non-functional requirements, and acceptance criteria.
- The actual F9/F10 text was more detailed than the abbreviated context used in the patch.
- A later patch treated overlapping `sed` output as a duplicated line even though the source contained it only once.
- The failed patch made no file changes.

### Suggested Fix
Read the exact local ranges immediately before editing and apply smaller independent hunks when a document has evolved across review rounds.

### Metadata
- Reproducible: yes
- Related Files: spec_worktree.md, spec_agent_team.md
- Recurrence-Count: 2
- First-Seen: 2026-08-10
- Last-Seen: 2026-08-10

### Resolution
- **Resolved**: 2026-08-10T00:00:00+08:00
- **Commit/PR**: none
- **Notes**: Re-read the exact requirements and continued with smaller patches.

---

## [ERR-20260810-006] apply-patch-target-disappeared

**Logged**: 2026-08-10T23:07:14+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
准备撤回对 `spec.md` 的越界修改时，目标文件已从共享工作区删除，补丁校验失败。

### Error
`apply_patch verification failed: Failed to read file to update spec.md: No such file or directory`

### Context
- 文件在前一次验证时仍存在，随后变为 Git 状态 `D spec.md`。
- 共享工作区可能发生用户或外部进程并发修改。
- 失败补丁未改动三份目标模块 Spec。

### Suggested Fix
编辑共享工作区文件前重新确认目标存在；发现用户已删除不在任务范围内的文件时，不恢复、不覆盖，只报告当前状态。

### Metadata
- Reproducible: no
- Related Files: spec.md

### Resolution
- **Resolved**: 2026-08-10T23:07:14+08:00
- **Commit/PR**: none
- **Notes**: 保留删除状态，不再处理 spec.md；后续仅使用三份指定模块文档。

---

## [ERR-20260810-004] memory-e2e-provider-connection

**Logged**: 2026-08-10T16:07:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
记忆系统真实 TUI 验收已通过受控 PTY 启动，但主模型请求因供应商连接错误中断，无法完成第二轮真实召回。

### Error
`Connection error.`

### Context
- 使用 `deepseek/deepseek-v4-flash` 提交“请记住：以后优先用中文简洁回答”。
- 失败会话只记录一条 user 和一条既有错误占位 assistant 消息。
- 项目记忆目录没有产生近期写入，符合“异常 turn 不提取”的设计。
- 自动化集成测试已覆盖成功提取、下一轮召回和 JSONL 不变性。

### Suggested Fix
恢复 Provider 网络或配置可用 Provider 后，重新执行两轮真实 TUI 对话验收。

### Metadata
- Reproducible: unknown
- Related Files: tests/integration/test_memory_lifecycle.py

---

## [ERR-20260810-003] tmux-not-installed

**Logged**: 2026-08-10T16:00:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
项目要求使用 tmux 进行端到端验收，但当前运行环境未安装 tmux。

### Error
`zsh:1: command not found: tmux`

### Context
- 尝试启动隔离的 `arkcode-memory-e2e-20260810` tmux session。
- 自动化测试、ruff 和 mypy 均已通过；只有指定的 tmux 验收方式不可用。
- 未擅自安装系统软件或修改全局环境。

### Suggested Fix
在开发环境安装 tmux；当前运行可使用受控 PTY session 完成等价的交互验证，并明确记录与项目指定方式的差异。

### Metadata
- Reproducible: yes
- Related Files: AGENT.md

---

## [ERR-20260810-002] superpowers-codex-reference-path

**Logged**: 2026-08-10T12:32:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
The Codex adaptation reference was looked up relative to the Superpowers package root instead of the `using-superpowers` skill directory.

### Error
`sed: .../skills/references/codex-tools.md: No such file or directory`

### Context
- `using-superpowers/SKILL.md` links to `references/codex-tools.md` relative to its own directory.
- The actual file is `using-superpowers/references/codex-tools.md`.

### Suggested Fix
Resolve skill-linked relative paths against the directory containing that skill's `SKILL.md`.

### Metadata
- Reproducible: yes
- Related Files: using-superpowers/SKILL.md, using-superpowers/references/codex-tools.md

### Resolution
- **Resolved**: 2026-08-10T12:32:00+08:00
- **Commit/PR**: none
- **Notes**: Located and read the reference from the correct skill-relative path.

---

## [ERR-20260808-001] apply_patch

**Logged**: 2026-08-08T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
Checklist checkbox patch used partial lines while apply_patch requires exact full-line context.

### Error
`apply_patch verification failed: Failed to find expected lines`

### Context
- Attempted to change many checklist markers using abbreviated line text.
- No source or document content was changed by the failed operation.

### Suggested Fix
Patch complete checklist lines or replace a bounded section with exact context.

### Metadata
- Reproducible: yes
- Related Files: checklist.md

---
## ERR-20260808-002 — 签名补丁引入额外缩进

- **现象**：修改测试内嵌 async handler 签名后，pytest 收集报 `IndentationError`。
- **原因**：apply_patch 的替换行比原作用域多了一层缩进。
- **预防**：修改嵌套函数签名后，先读取局部上下文或运行 `ruff check`/语法收集，再执行完整测试。

---

## ERR-20260808-003 — Plan Mode 写工具在权限引擎路径进入审批

- **现象**：Provider 在 Plan Mode 返回 `InstallSkill` 调用时，集成测试停在审批等待，而非直接拒绝。
- **原因**：`Agent._check_permission` 只在未启用 Engine 时执行 Plan Mode 硬拒绝；启用 Engine 后直接委托通用 fallback，write 类得到 ASK。
- **修复**：把 `mode is PLAN and not read_only` 的拒绝规则提升到 Engine 分支之前。
- **预防**：模式级不变量必须先于可配置权限规则执行，并同时覆盖启用/禁用 Engine 两条测试路径。

---

## ERR-20260808-004 — rg 模式中的反引号被 shell 解析

- **现象**：文档路径扫描命令在 zsh 报 `unmatched "`，未执行搜索。
- **原因**：双引号命令字符串中的反引号参与了 shell 解析。
- **修复**：将正则模式改为单引号包裹，避免命令替换语义。
- **预防**：传递包含 Markdown 反引号、`$()` 或 `$` 的搜索模式时优先使用单引号。

---

## [ERR-20260808-005] git-add-sandbox-permission

**Logged**: 2026-08-08T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
Git staging failed because the managed workspace exposes `.git` as read-only by default.

### Error
`fatal: Unable to create '.git/index.lock': Operation not permitted`

### Context
- Attempted to stage the verified Skill-system baseline before structural refactoring.
- Source files were writable, but updating the Git index requires explicit escalation.

### Suggested Fix
Run scoped `git add` and `git commit` commands with managed approval when a user explicitly requests a commit.

### Metadata
- Reproducible: yes
- Related Files: .git/index

### Resolution
- **Resolved**: 2026-08-08T00:00:00+08:00
- **Commit/PR**: c1db037
- **Notes**: Scoped Git staging and commit completed with managed approval; unrelated untracked files remained excluded.

---

## [ERR-20260808-006] sdd-workspace-not-executable

**Logged**: 2026-08-08T21:40:30+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
The bundled SDD workspace helper exists but does not have an executable file mode.

### Error
`permission denied: .../subagent-driven-development/scripts/sdd-workspace`

### Context
- Attempted to invoke the helper directly while initializing the refactor task ledger.
- The bundled `task-brief` helper also invokes `sdd-workspace` directly when no explicit output path is supplied.
- The project test command that followed still ran and produced the expected baseline result.

### Suggested Fix
Invoke bundled shell helpers explicitly through `bash`; for `task-brief`, also supply its explicit output-file argument so it does not directly execute `sdd-workspace`.

### Metadata
- Reproducible: yes
- Related Files: superpowers/subagent-driven-development/scripts/sdd-workspace

### Resolution
- **Resolved**: 2026-08-08T21:40:30+08:00
- **Commit/PR**: none
- **Notes**: Subsequent SDD helper calls use `bash <script>` and explicit output paths where nested execution would occur; no external Skill files were modified.

---

## [ERR-20260810-001] git-add-sandbox-permission-recurrence

**Logged**: 2026-08-10T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
Scoped Git staging of an approved spec document was blocked because the managed
workspace exposes `.git` as read-only.

### Error
`fatal: Unable to create '.git/index.lock': Operation not permitted`

### Context
- Attempted to stage only the new MCP deferred-tool discovery spec.
- The document was written and verified successfully; only Git metadata mutation failed.
- A commit was not required to satisfy the user's design request, so no permission expansion was requested.

### Suggested Fix
Only request managed approval for scoped `git add` and `git commit` when the user
explicitly requires a commit or the commit is necessary to complete the task.

### Metadata
- Reproducible: yes
- Related Files: .git/index, docs/superpowers/specs/2026-08-10-mcp-deferred-tool-discovery-spec.md
- See Also: ERR-20260808-005

### Resolution
- **Resolved**: 2026-08-10T00:00:00+08:00
- **Commit/PR**: none
- **Notes**: Kept the validated spec as an untracked workspace file and stopped before requesting unnecessary privileges.

---

## [ERR-20260810-005] python-command-unavailable

**Logged**: 2026-08-10T20:21:52+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
Spec self-review assumed a `python` executable, but this workspace exposes Python through `python3` or the project virtual environment.

### Error
`zsh: command not found: python`

### Context
- Attempted a read-only script to verify requirement-number continuity in `spec.md`.
- The failed check made no file changes.

### Suggested Fix
Use `python3` for lightweight workspace scripts, or the project virtual-environment interpreter when project dependencies are required.

### Metadata
- Reproducible: yes
- Related Files: spec.md

### Resolution
- **Resolved**: 2026-08-10T20:21:52+08:00
- **Commit/PR**: none
- **Notes**: Re-ran the check with `python3`.

---
