# SubAgent、Worktree 与 Agent Team Unified Checklist

> 每项都必须通过运行命令或观察行为获得证据。不得仅以“代码已实现”判定通过；验收报告需记录实际输出、通过/失败/跳过数量和必要的复现步骤。

## 0. 验收前置条件

- [ ] 三份规格、统一 Plan 和 50 个 Tasks 均为当前批准版本。（验证：核对 `spec_sub_agent.md`、`spec_worktree.md`、`spec_agent_team.md`、`plan.md`、`task.md` 的工作区版本）
- [ ] 阶段 A、B、C 的回归门 T17、T29、T50 均已有退出码为 0 的记录。（验证：查看对应执行日志）
- [ ] 测试未依赖真实用户配置或污染主仓库。（验证：测试均使用临时 HOME、临时 Git 仓库和独立 session 目录）

## 1. SubAgent 验收

### 工具、角色和 Fork

- [ ] **SubAgent AC1**：主 Agent 始终看到稳定 Agent schema；定义式子 Agent 看不到 Agent，Fork 只保留 schema 且执行被拒绝。（验证：运行 `pytest tests/subagents/test_filter.py -v`）
- [ ] **SubAgent AC2**：调用 `subagent_type="explore"` 返回 explore 的最终 assistant 文本。（验证：运行 `pytest tests/subagents/test_tools.py -k explore -v`）
- [ ] **SubAgent AC3**：未知角色返回结构化“未知 subagent_type”错误。（验证：运行 `pytest tests/subagents/test_tools.py -k unknown -v`）
- [ ] **SubAgent AC4**：不传 subagent_type 时首条任务含 `<fork_boilerplate>`，父历史前缀不变。（验证：运行 `pytest tests/subagents/test_launcher.py -k fork_prefix -v`）
- [ ] **SubAgent AC5**：Fork 内调用 Agent 被来源防线拒绝，结果明确说明不能嵌套启动。（验证：运行 `pytest tests/subagents/test_launcher.py -k fork_nested -v`）
- [ ] **SubAgent AC6**：定义式子 Agent 的可见工具中没有 Agent。（验证：运行 `pytest tests/subagents/test_filter.py -k defined -v`）
- [ ] **SubAgent AC16**：项目级 `explore.md` 覆盖 builtin explore。（验证：运行 `pytest tests/subagents/test_catalog.py -k project_override -v`）
- [ ] **SubAgent AC19**：即使来源识别失效，历史中的 `<fork_boilerplate>` 仍阻止嵌套 Agent。（验证：运行 `pytest tests/subagents/test_launcher.py -k boilerplate_guard -v`）
- [ ] **SubAgent AC21**：自定义角色的 tools、permissionMode、maxTurns 和追加式 instructions 全部生效，基础 system prompt 保留。（验证：运行 `pytest tests/subagents/test_launcher.py -k custom_definition -v`）
- [ ] **SubAgent AC22**：`explore-v2` 合法；`Explore/foo_bar/foo bar` 和非法字段文件 warning 后跳过；Provider 创建失败不回退。（验证：运行 `pytest tests/subagents/test_models.py tests/subagents/test_catalog.py tests/subagents/test_launcher.py -k 'invalid or provider' -v`）

### 权限与审批

- [ ] **SubAgent AC7**：`permissionMode:dontAsk` 放行普通 Ask 操作，但系统 deny 仍不可绕过。（验证：运行 `pytest tests/permissions/test_permission_core.py -k dont -v`）
- [ ] **SubAgent AC8**：默认模式 Ask 会暂停对应子 Agent，TUI 审批标明来源且响应只恢复该 Agent。（验证：运行 `pytest tests/subagents/test_launcher.py -k approval -v`）

### 后台 Job 生命周期

- [ ] **SubAgent AC9**：显式后台调用立即返回 `{job_id,status:"async_launched"}`，主 Agent 不阻塞。（验证：运行 `pytest tests/subagents/test_tools.py -k async_launched -v`）
- [ ] **SubAgent AC10**：前台运行达到 120 秒后同一执行切到后台并返回 `timed_out_to_background`。（验证：运行 `pytest tests/subagents/test_manager.py -k timeout_background -v`）
- [ ] **SubAgent AC11**：ESC 把前台子 Agent 切到后台，TUI 可继续接收输入且底层 task 未取消。（验证：运行 `pytest tests/subagents/test_manager.py tests/tui/test_tui.py -k esc -v`）
- [ ] **SubAgent AC12**：后台完成后下一轮 reminder 出现 `<task-notification>` 和 Result。（验证：运行 `pytest tests/subagents/test_tools.py -k notification -v`）
- [ ] **SubAgent AC13**：JobList 返回 job_id/name/status/tool_count/last_activity。（验证：运行 `pytest tests/subagents/test_tools.py -k job_list -v`）
- [ ] **SubAgent AC14**：JobGet 返回结果；JobStop 后状态为 cancelled。（验证：运行 `pytest tests/subagents/test_tools.py -k 'job_get or job_stop' -v`）
- [ ] **SubAgent AC15**：JobSend 复用已结束 Agent/Conversation，创建新 job_id 并产生新 `<task-notification>`。（验证：运行 `pytest tests/subagents/test_manager.py -k resume -v`）
- [ ] **SubAgent AC18**：关闭后台功能时 Fork 返回结构化错误，不偷偷转前台。（验证：运行 `pytest tests/subagents/test_tools.py -k background_disabled -v`）
- [ ] **SubAgent AC20**：普通异常进入 failed 并通知；取消单独进入 cancelled；主程序继续运行。（验证：运行 `pytest tests/subagents/test_manager.py -k 'failed or cancelled' -v`）
- [ ] **SubAgent AC20a**：Worktree 后台 Job 可观察 preparing→running→终态，准备失败、取消和清理结果只通知一次。（验证：运行 `pytest tests/integration/test_subagent_worktree.py -k lifecycle -v`）

### Skill 集成

- [ ] **SubAgent AC17**：Skill fork 复用统一 Launcher/TaskManager，不存在第二套 Agent 构造路径。（验证：运行 `pytest tests/skills/test_skills_executor.py -k fork -v`）

## 2. Worktree 验收

### 标识、创建和恢复

- [ ] **Worktree AC1**：`feature/a` 合法，traversal、空段和尾随空格被拒绝。（验证：运行 `pytest tests/worktrees/test_slug.py -v`）
- [ ] **Worktree AC2**：创建 alice 后目录为 `.Arkcode/worktrees/alice/`、分支为 `worktree-alice`。（验证：运行 `pytest tests/worktrees/test_manager.py -k create_simple -v`）
- [ ] **Worktree AC3**：嵌套 slug `team/alice` flatten 为目录/分支中的 `team+alice`。（验证：运行 `pytest tests/worktrees/test_manager.py -k create_nested -v`）
- [ ] **Worktree AC4**：身份完全匹配时快速恢复且不调 git add；manifest 缺失/损坏时 fail-closed 且不改资源。（验证：运行 `pytest tests/worktrees/test_manifest.py tests/worktrees/test_manager.py -k recover -v`）

### 创建后三步设置

- [ ] **Worktree AC5**：本地 Arkcode 配置文件被复制到 Worktree 对应位置。（验证：运行 `pytest tests/worktrees/test_setup.py -k config -v`）
- [ ] **Worktree AC6**：setup 不探测 `.husky/`、不调用或修改 `core.hooksPath`。（验证：运行 `pytest tests/worktrees/test_setup.py -k hooks -v`，并比较创建前后 Git config）
- [ ] **Worktree AC7**：有只读保障时共享依赖可读不可写；无保障时跳过并 warning。（验证：运行 `pytest tests/worktrees/test_setup.py -k readonly -v`）
- [ ] **Worktree AC8**：`.worktreeinclude` 命中的 ignored `.env` 被复制。（验证：运行 `pytest tests/worktrees/test_setup.py -k include -v`）

### cwd、路径与工具隔离

- [ ] **Worktree AC9**：enter 返回完整 session 且不改变 `Path.cwd()`。（验证：运行 `pytest tests/worktrees/test_manager.py -k enter -v`）
- [ ] **Worktree AC9a**：exit/remove/auto_cleanup 前后 `Path.cwd()` 均不变。（验证：运行 `pytest tests/worktrees/test_manager.py -k cwd -v`）
- [ ] **Worktree AC13**：六个核心工具按注入 cwd 解析相对路径。（验证：运行 `pytest tests/tools/test_workspace_context.py -k relative -v`）
- [ ] **Worktree AC14**：Bash subprocess 的 cwd 精确等于 ExecutionPathContext.cwd。（验证：运行 `pytest tests/tools/test_workspace_context.py -k bash_cwd -v`）
- [ ] **Worktree AC14a**：父仓库绝对路径、`../` 和未声明 symlink target 被拒绝；Worktree 内绝对路径允许。（验证：运行 `pytest tests/tools/test_workspace_context.py -k containment -v`）

### 退出、清理和 Session

- [ ] **Worktree AC10**：存在未提交修改时普通 remove 抛错并保留目录。（验证：运行 `pytest tests/worktrees/test_manager.py -k changed_refuse -v`）
- [ ] **Worktree AC11**：显式 discard 删除目录、分支和 manifest。（验证：运行 `pytest tests/worktrees/test_manager.py -k discard -v`）
- [ ] **Worktree AC12**：manual Worktree 永远 keep；临时干净 Worktree 自动 remove。（验证：运行 `pytest tests/worktrees/test_manager.py -k auto_cleanup -v`）
- [ ] **Worktree AC17**：`/worktree create/list` 可创建并显示 alice。（验证：运行 `pytest tests/commands/test_builtins.py -k worktree -v`）
- [ ] **Worktree AC18**：`/worktree exit --remove` 有修改时报错，追加 `--discard` 后删除。（验证：运行命令测试并在临时 Git 仓库手动复现）
- [ ] **Worktree AC19**：stale sweep 只处理合法临时命名和超过 cutoff 的实例，并跳过当前、有变更或未推送 commit 的实例。（验证：运行 `pytest tests/worktrees/test_manager.py -k stale -v`）
- [ ] **Worktree AC20**：session 可恢复；外部删除目录后启动会清空 session 并 warning。（验证：运行 `pytest tests/worktrees/test_manager.py -k session -v`）

### SubAgent 与 Worktree 集成

- [ ] **Worktree AC15**：`isolation:"worktree"` 自动执行 create→notice→cwd→run→cleanup。（验证：运行 `pytest tests/integration/test_subagent_worktree.py -k isolation -v`）
- [ ] **Worktree AC16**：子 Agent 写入只出现在 Worktree，主目录对应文件不变。（验证：运行 `pytest tests/integration/test_subagent_worktree.py -k isolation -v`）
- [ ] **Worktree AC23**：后台 Worktree Job 立即返回 job_id，JobGet 可见 preparing→running→completed，主 Agent 可继续输入。（验证：运行 `pytest tests/integration/test_subagent_worktree.py -k background -v`）
- [ ] **Worktree AC24**：preparing/running 时 JobStop 进入 cancelled；干净资源回收，修改资源保留且通知含 path/branch/base_commit。（验证：运行 `pytest tests/integration/test_subagent_worktree.py -k cancel -v`）
- [ ] **Worktree AC25**：分支冲突、坏 manifest、git 失败和取消均不删除非本 Job 资源，且只产生一个终态通知。（验证：运行 `pytest tests/integration/test_subagent_worktree.py -k failure_safety -v`）

### Worktree 质量门与 E2E

- [ ] **Worktree AC21**：项目启动、Worktree 单测和 lint 通过。（验证：运行 `python3 -m Arkcode --version && ruff check src tests && pytest tests/worktrees tests/tools -q`）
- [ ] **Worktree AC22**：真实 tmux 中触发隔离子 Agent 后主文件未变、Worktree 文件已变，留盘/清理符合变更状态。（验证：按 E2E-W1 场景执行并记录路径与 diff）

## 3. Agent Team 验收

### Team 模型、生命周期与恢复

- [ ] **Team AC1**：teams 根目录缺失时自动创建，已有目录可扫描恢复。（验证：运行 `pytest tests/teams/test_manager.py -k bootstrap -v`）
- [ ] **Team AC2**：`refactor auth` sanitize 为 `refactor-auth`，config 含 backend、独立 lead_agent_id 和空 members。（验证：运行 `pytest tests/teams/test_manager.py -k create -v`）
- [ ] **Team AC3**：同名第二个 Team 使用 `-2` 后缀且路径一致。（验证：运行 `pytest tests/teams/test_manager.py -k suffix -v`）
- [ ] **Team AC4**：有活跃 teammate 时非 force delete 被拒绝且目录保留。（验证：运行 `pytest tests/teams/test_manager.py -k active_delete -v`）
- [ ] **Team AC5**：force delete 按 kill→Worktree/session→config_dir 顺序清理。（验证：运行 `pytest tests/teams/test_manager.py -k force_delete -v`）

### Backend、spawn 与 cwd

- [ ] **Team AC6**：后端检测严格遵循 TMUX→iTerm2+it2→PATH tmux→in-process。（验证：运行 `pytest tests/teams/test_backends.py -k detect -v`）
- [ ] **Team AC7**：Team spawn 创建 Worktree；backend.spawn 入口已能从 config 看到最终 member/agent_id，返回后 pane_id 被回写。（验证：运行 `pytest tests/teams/test_spawner.py -k ordering -v`）
- [ ] **Team AC8**：in-process teammate 二次 team spawn 被明确拒绝。（验证：运行 `pytest tests/teams/test_backends.py -k nested -v`）
- [ ] **Team AC23**：tmux spawn 后新 pane 存在且 worker 连接指定 Team。（验证：运行 `pytest tests/integration/test_team_tmux.py -k spawn -v`）
- [ ] **Team AC24**：SendMessage 对 tmux pane 执行 send-keys 并触发收件。（验证：运行 `pytest tests/integration/test_team_tmux.py -k wake -v`）
- [ ] **Team AC25**：in-process teammate 使用独立 workspace context，主进程 cwd 始终不变且 os.chdir 未调用。（验证：运行 `pytest tests/teams/test_backends.py -k inprocess -v`）
- [ ] **Team AC25a**：Pane worker 只在创建 task/Agent 前 chdir 一次，多轮续派后次数仍为 1。（验证：运行 `pytest tests/teams/test_worker.py -k chdir -v`）

### 共享任务与消息

- [ ] **Team AC9**：Task* 只对 teammate 可见；SendMessage 只对 Lead/teammate 可见；普通 SubAgent 不可见。（验证：运行 `pytest tests/teams/test_coordinator.py tests/teams/test_shared_tasks.py -k visibility -v`）
- [ ] **Team AC10**：TaskCreate 持久化，TaskUpdate 双向维护 blocked_by/blocks。（验证：运行 `pytest tests/teams/test_shared_tasks.py -k dependency -v`）
- [ ] **Team AC11**：TaskList pending 结果的 is_ready 正确反映 blocker 状态。（验证：运行 `pytest tests/teams/test_shared_tasks.py -k ready -v`）
- [ ] **Team AC12**：发给 alice 的消息写入其 agent_id mailbox 且 unread。（验证：运行 `pytest tests/teams/test_mailbox.py -k direct -v`）
- [ ] **Team AC13**：Lead 广播到所有 members；teammate 广播到其他 members 和 lead_agent_id。（验证：运行 `pytest tests/teams/test_mailbox.py -k broadcast -v`）
- [ ] **Team AC14**：10 个并发 mailbox write 无丢失、截断或非法 JSON。（验证：运行 `pytest tests/teams/test_mailbox.py -k concurrent -v`）
- [ ] **Team AC15**：超过 10 秒的 mailbox lock 被清理后写入成功。（验证：运行 `pytest tests/teams/test_mailbox.py -k stale -v`）
- [ ] **Team AC15a**：两个进程并发 config 更新无丢失；等待超过 5 秒明确失败。（验证：运行 `pytest tests/teams/test_storage.py -k multiprocess -v`）
- [ ] **Team AC16**：未读消息在 LLM 前以 `<incoming-messages>` 注入，调用后标 read。（验证：运行 `pytest tests/teams/test_worker.py -k incoming -v`）
- [ ] **Team AC17**：teammate 完成后 config 标 inactive，Lead 收到 `[idle] <member>`。（验证：运行 `pytest tests/integration/test_team_inprocess.py -k idle -v`）
- [ ] **Team AC18**：向已停止 in-process teammate 发消息会从 session 恢复 Conversation 并重新 Running。（验证：运行 `pytest tests/integration/test_team_inprocess.py -k resume -v`）

### Plan 审批与 Coordinator

- [ ] **Team AC19**：plan_mode_required teammate 初始权限为 plan。（验证：运行 `pytest tests/teams/test_worker.py -k plan_initial -v`）
- [ ] **Team AC19a**：计划完成后 Lead 收到带非空 request_id 的 plan_approval_request，teammate 保持 plan 并等待。（验证：运行 `pytest tests/teams/test_worker.py -k plan_request -v`）
- [ ] **Team AC20**：匹配的 approve=True 响应使 teammate 下一轮切回 default。（验证：运行 `pytest tests/teams/test_worker.py -k plan_approve -v`）
- [ ] **Team AC21**：Coordinator 双锁开启后 allowed tools 精确等于 Agent/SendMessage/JobStop/TeamDelete，其他工具均拒绝，状态栏显示标签。（验证：运行 `pytest tests/teams/test_coordinator.py -k enabled -v`）
- [ ] **Team AC22**：Coordinator 关闭时普通 Lead 的 write/edit 等原工具保持可用。（验证：运行 `pytest tests/teams/test_coordinator.py -k disabled -v`）
- [ ] **Team AC30**：Coordinator 中 write_file 和 Bash merge 均拒绝；重启普通模式恢复 Team 后 merge 可用。（验证：运行 Coordinator E2E-C1）

### 命令、质量门与 E2E

- [ ] **Team AC26**：`/team list/info/delete` 显示和调用行为正确。（验证：运行 `pytest tests/commands/test_builtins.py -k team -v`）
- [ ] **Team AC27**：项目启动、Ruff、mypy 和完整 pytest 均通过。（验证：运行第 5 节质量门命令）
- [ ] **Team AC28**：tmux 端到端完成 TeamCreate→spawn alice→写 hello→SendMessage 续写 world→force delete。（验证：运行 E2E-T1 并记录 pane/config/worktree 状态）
- [ ] **Team AC29**：in-process 端到端完成 TeamCreate→spawn bob→idle→session resume。（验证：运行 `pytest tests/integration/test_team_inprocess.py -v` 并执行 E2E-I1）

## 4. 架构与集成检查

- [ ] 只有现有 Agent loop 执行 ReAct，SubAgent/teammate 未复制第二套循环。（验证：架构依赖测试 + `pytest tests/architecture -q`）
- [ ] `agents` 不反向导入 `subagents/worktrees/teams`，领域包依赖方向符合 Plan。（验证：运行 `pytest tests/architecture/test_dependencies.py -v`）
- [ ] 每个 Agent 的 Runtime、Conversation、Registry discovered 状态和 PermissionLedger 相互隔离。（验证：运行对应并发隔离测试）
- [ ] 基础 system prompt 不可被 Definition 覆盖，所有角色/teammate instructions 只追加。（验证：捕获 provider request 的 system 内容并断言顺序）
- [ ] 主进程和 in-process 路径没有 os.chdir；Pane worker 只有一次启动调用。（验证：运行 `rg -n 'os\.chdir' src/Arkcode` 并结合 worker 测试审计）
- [ ] Worktree setup 没有 hooks 配置实现。（验证：运行 `rg -n 'core\.hooksPath|\.husky' src/Arkcode`，期望无命中）
- [ ] Team config/tasks/mailbox 的完整 read-modify-write 都位于 FileLock 临界区，backend spawn/kill 不持锁。（验证：并发测试 + timeout 测试）
- [ ] TeamSpawner 在 backend 前预注册，失败回滚不留下 member/name/Worktree/session 残骸。（验证：运行 `pytest tests/teams/test_spawner.py -v`）
- [ ] Coordinator RegistryView 无法通过 deferred tools、ToolSearch、MCP 或 Skill 绕过白名单。（验证：运行 Coordinator filtering 测试）
- [ ] Runtime shutdown 后没有存活 asyncio task、pending approval Future 或遗留 Pane。（验证：运行 Application shutdown 测试并检查 task/pane 列表）

## 5. 语法、静态检查与完整测试

- [ ] Python 模块全部可编译。（验证：`python3 -m compileall src/Arkcode`，退出码 0）
- [ ] Ruff 无错误。（验证：`ruff check src tests`，退出码 0）
- [ ] mypy strict 无错误。（验证：`mypy src/Arkcode`，退出码 0）
- [ ] 全部测试通过。（验证：`pytest -q`，记录 passed/failed/skipped 总数；failed 必须为 0）
- [ ] tmux/iTerm2 缺失时只有显式条件集成测试 skip，不得把功能失败误报为 skip。（验证：查看 pytest skip reason）

## 6. 端到端场景

### E2E-S1：SubAgent 前台、后台与续派

- [ ] 启动 Arkcode，调用 explore 前台任务，观察最终文本返回；再启动后台任务，观察立即返回 job_id、JobList/JobGet 可查、完成后出现 `<task-notification>`；最后 JobSend 续派并得到新 job_id。（证据：终端日志与两个 job_id）

### E2E-W1：隔离 Worktree

- [ ] 在临时 Git 仓库让 `isolation:worktree` 子 Agent 修改 `server.py`；确认主目录文件未变、Worktree 文件已变，Job 通知包含保留或清理结果。（证据：主目录/Worktree `git diff` 对比）

### E2E-I1：in-process Team

- [ ] 强制无 tmux/iTerm2 环境，创建 Team 和 bob；确认主 cwd 不变、bob 在独立 Worktree 完成任务、Lead 收到 idle、SendMessage 后从原 Conversation 续派。（证据：config.json、mailbox、session journal）

### E2E-T1：tmux Team

- [ ] 在 tmux 内创建 Team 和 alice；确认新 pane、初始任务执行、消息 wake、再次执行及 force delete 全链路。（证据：pane 列表、worktree、team 目录和输出文件）

### E2E-C1：Coordinator 与收敛

- [ ] 双锁开启 Coordinator，确认只剩四个工具且 Bash merge 被拒绝；保留 Team/Worktree 后退出，普通模式重启恢复 Team，执行 merge，最后 TeamDelete。（证据：拒绝结果、重启前后工具列表、merge log、清理结果）

## 7. 最终验收报告要求

- [ ] 报告按“通过 / 未通过 / 跳过 / 端到端”分类，每项引用本 Checklist 编号和实际证据。（验证：检查最终报告的四个固定小节和证据链接）
- [ ] 任一失败项必须记录预期、实际、复现命令和修复后复验结果。（验证：抽查所有失败条目字段完整）
- [ ] 未运行的项目不得标记通过；环境不具备只能标记跳过并说明原因。（验证：对照命令执行日志与报告状态）
