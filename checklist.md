# Skill 系统 Checklist

> 每项必须通过运行代码、测试或真实 TUI 观察获得证据后才能勾选。代码重构但行为不变时，
> 行为项仍应成立。操作目录为仓库根 `/Users/inception/learning/ArkCode`。

## 1. SkillMeta 与解析

- [x] 合法 `SKILL.md` 能解析出 name、description 和完整正文（验证：
  `pytest -q tests/test_skills_parser.py -k defaults`）
- [x] 元数据类型统一命名为 `SkillMeta`，公开接口没有旧类型名（验证：
  `rg "class SkillMeta" src/Arkcode/skills && ! rg "class SkillD[e]f" src/Arkcode`）
- [x] `mode` 缺省为 `inline`，`context` 缺省为 `full`（验证：Parser 默认值测试）
- [x] `mode` 只接受 `inline/fork`，`context` 只接受 `full/recent/none`（验证：非法枚举
  表驱动测试）
- [x] name 只接受 `^[a-z][a-z0-9-]*$`，name/description 缺失或为空时拒绝（验证：
  Parser 校验测试）
- [x] 缺少 opening delimiter、缺少 closing delimiter、非法 YAML、YAML 根节点非 mapping
  均产生 `SkillParseError`（验证：Parser 错误测试）
- [x] 不存在的源文件产生可识别解析错误，不泄漏无关异常（验证：nonexistent 测试）
- [x] 单文件布局把 `is_directory` 设为 False，目录型 `SKILL.md` 设为 True（验证：两种
  布局测试）
- [x] `source_path` 是实际 `SKILL.md/*.md` 的绝对路径（验证：路径断言测试）
- [x] `$ARGUMENTS` 的每次出现都会被替换（验证：multiple placeholders 测试）
- [x] 正文没有 `$ARGUMENTS` 时，即使提供 args 也逐字保持不变（验证：no placeholder 测试）

## 2. 两级加载、优先级与热重载

- [x] 项目 `.Arkcode/skills/*.md` 可被加载（验证：Loader project file 测试）
- [x] 项目 `.Arkcode/skills/*/SKILL.md` 可被加载且目录资源不被误当成独立 Skill
  （验证：Loader directory 测试）
- [x] 用户 `~/.Arkcode/skills/` 的两种布局均可加载（验证：monkeypatch home 的 user 测试）
- [x] 项目与用户出现同名 Skill 时只保留项目版本（验证：project overrides user 测试）
- [x] Catalog 始终按 name 字典序返回，且只含 name/description（验证：catalog 测试）
- [x] `get_source_label` 对项目、用户、未知 Skill 分别返回 project、user、None（验证：
  source label 测试）
- [x] 单条坏 Skill 只记录 warning，其他合法 Skill 继续加载（验证：`caplog` 隔离测试）
- [x] `get(name)` 每次重读磁盘，修改正文后无需 reload/restart 即时生效（验证：hot reload
  success 测试）
- [x] 热重读失败时返回最后一次成功缓存并记录 warning（验证：hot reload fallback 测试）
- [x] `reload()` 能发现新增 Skill、移除已删除 Skill，并刷新 Catalog（验证：reload 测试）
- [x] 缺少项目目录或用户目录时返回空结果，不抛异常（验证：missing directories 测试）

## 3. Catalog、Active Skills 与 Agent

- [x] Available Skills 只列 name/description 和 LoadSkill 指引，不包含任何完整 SOP（验证：
  `pytest -q tests/test_prompt_skills.py -k catalog`）
- [x] 没有 Skill 时不输出空的 Available Skills 标题（验证：empty catalog 测试）
- [x] 激活 Skill 后 environment 出现 `## Active Skills`、Skill 名和完整 SOP（验证：active
  render 测试）
- [x] Active Skills 为空时 environment 不出现对应标题（验证：empty active 测试）
- [x] 同名 Skill 重复激活会原位置更新正文，不产生重复段（验证：reactivate 测试）
- [x] 同时激活多个 Skill 时保持激活顺序（验证：ordering 测试）
- [x] Agent iteration N 内调用 LoadSkill 后，iteration N+1 的 system.environment 立即包含
  SOP（验证：`pytest -q tests/test_agent.py -k skill_iteration`）
- [x] 动态 Skill 正文不进入稳定 system block（验证：捕获 Request.system 的断言）
- [x] `clear_active_skills()` 清空 Active Skills，但不改变 Catalog（验证：Agent clear 测试）

## 4. LoadSkill 工具

- [x] Tool Registry 中可按精确名字 `LoadSkill` 找到工具（验证：工具注册集成测试）
- [x] LoadSkill 的 JSON Schema 只要求字符串字段 `name`（验证：schema 测试）
- [x] LoadSkill 被判定为 read-only，Plan Mode 可见且不进入权限确认（验证：Registry
  read-only definitions + Agent permission 测试）
- [x] Loader/Agent 尚未注入时返回 `is_error=True` 和初始化错误（验证：uninitialized 测试）
- [x] 非法 JSON、缺 name、name 非字符串均返回可观察错误（验证：参数表驱动测试）
- [x] 未知 Skill 返回错误并列出可用名称，不激活任何内容（验证：unknown 测试）
- [x] 成功调用会热重读并调用 `activate_skill(name, body)`（验证：mock 调用断言）
- [x] 成功结果只含简短确认，不包含完整 SOP（验证：结果内容断言）
- [x] `Registry.without({"LoadSkill"})` 不包含 LoadSkill、保持其他工具顺序，且不修改源
  Registry（验证：Tool Registry 隔离测试）

## 5. inline 与 fork 执行

### inline

- [x] inline 执行替换 `$ARGUMENTS` 后激活对应 Skill（验证：
  `pytest -q tests/test_skills_executor.py -k inline`）
- [x] inline 正文无占位符时保持原样（验证：inline no-placeholder 测试）
- [x] inline Executor 自身不调用 Provider、不修改 Conversation（验证：mock 与历史断言）
- [x] inline Slash handler 激活后只触发一个主 Agent 用户回合（验证：Command/TUI 集成测试）

### fork

- [x] `context=none` 的子 Conversation 只含渲染后的 Skill 请求（验证：fork none 测试）
- [x] `context=recent` 只携带最近 5 条 user/assistant 消息，不携带 tool 消息（验证：fork
  recent 测试）
- [x] `context=full` 先生成历史摘要，再追加 Skill 请求（验证：fork full 测试）
- [x] fork 使用独立 Conversation、SessionRuntime、compact/recovery/session 状态（验证：
  对象身份与主状态前后对比）
- [x] fork Agent 看不到 LoadSkill，但其他允许工具仍保持原注册顺序（验证：fork registry 测试）
- [x] 未配置 model 时沿用当前 ProviderConfig，配置 model 时只替换 model（验证：provider
  factory mock）
- [x] fork 累计 AgentEvent.text 直到 done，并返回完整文本（验证：事件序列测试）
- [x] fork 普通异常返回 `[skill <name> failed: ...]`，CancelledError 保持取消语义（验证：
  error/cancel 测试）
- [x] fork 执行前后主 Conversation 和主 Agent Active Skills 完全不变（验证：隔离测试）
- [x] fork 完成后主会话只新增一条 `<system-reminder>` 回流结果，子执行过程不回流（验证：
  TUI fork integration 测试）

## 6. Slash Command 与管理命令

- [x] Parser 能把 `/skill info review` 分为 name=`skill`、args=`info review`（验证：
  `pytest -q tests/test_command_dispatch.py -k arguments`）
- [x] 普通文本、空白、空 `/`、大小写命令和内部多空格按 Plan 分类（验证：parse 表驱动测试）
- [x] 原有 12 条命令在 Handler 增加 args 后行为保持不变（验证：既有 command/TUI 测试）
- [x] Registry 默认仍在 name/alias 冲突时立即失败（验证：既有冲突测试）
- [x] `replace=True` 能覆盖旧命令并清理旧 aliases/visible 索引（验证：replace 测试）
- [x] Registry clear 后 lookup/visible/prefix_match 全部为空（验证：clear 测试）
- [x] `/skill` 与 `/skill list` 按 name 排序显示 name、description、project/user 来源（验证：
  管理命令测试）
- [x] `/skill info <name>` 显示规范化 frontmatter、绝对 source path 和目录型标记（验证：
  info 测试）
- [x] `/skill reload` 刷新 Loader、Slash Registry 和 Agent Catalog，不触发 LLM（验证：
  reload 集成测试）
- [x] `/skill` 非法子命令打印用法，不触发 LLM（验证：invalid usage 测试）
- [x] 每个 Skill 自动成为 `/name` 命令，描述末尾包含 `[skill]`（验证：动态注册测试）
- [x] 动态 Skill handler 每次调用 Loader.get，因此无需 reload 即可读取正文修改（验证：
  command hot reload 测试）
- [x] Skill 名与 `/review` 等内置命令冲突时 Skill 优先（验证：override 测试）
- [x] 删除冲突 Skill 并 reload 后，被覆盖的内置命令恢复（验证：restore builtin 测试）
- [x] `/help` 与补全菜单随 install/reload 即时新增或移除 Skill（验证：TUI integration 测试）

## 7. `/clear` 与生命周期

- [x] App 初始化时加载 Loader，并在 Agent 创建前注册 LoadSkill（验证：TUI construction 测试）
- [x] Provider 激活后完成 LoadSkill Agent 注入、Executor 构造和 Catalog 设置（验证：provider
  activation 测试）
- [x] 多 Provider 选择路径与单 Provider 自动激活路径都能完成 Skills 组装（验证：两类 TUI
  测试）
- [x] `/clear` 成功创建新会话后清除 Active Skills，Catalog 保留（验证：clear integration）
- [x] 新会话创建失败时旧 Conversation、Active Skills 和 Writer 保持可用（验证：clear failure）
- [x] fork 后台任务由 App 持有，完成后从集合移除（验证：task lifecycle 测试）
- [x] App 退出时取消并等待未完成 fork tasks，无 pending-task warning（验证：unmount 测试）
- [x] Skill 相关本地命令和管理命令不增加 token 计数（验证：TUI usage 前后对比）

## 8. 远程安装安全

- [x] 接受 `https://skills.sh/<owner>/<repo>/<skill>`（验证：URL parser 测试）
- [x] 接受 `https://github.com/<owner>/<repo>/tree/<ref>/<path>`（验证：URL parser 测试）
- [x] 接受指向 SKILL.md 的 `https://raw.githubusercontent.com/...`（验证：URL parser 测试）
- [x] 拒绝 HTTP、未知 host、缺 owner/repo/ref/path 和非 SKILL.md raw URL（验证：invalid URL
  表驱动测试）
- [x] 下载只访问 GitHub Contents API，不调用本地 git、不解压 ZIP（验证：MockTransport 请求
  URL 与代码扫描）
- [x] 单文件超过 1 MiB 时在落盘前拒绝（验证：file-size limit 测试）
- [x] 总大小超过 8 MiB 时拒绝并清理 staging（验证：total-size limit 测试）
- [x] 文件数超过 64 时拒绝并清理 staging（验证：file-count limit 测试）
- [x] 递归深度超过 4 时拒绝并清理 staging（验证：depth limit 测试）
- [x] base64 非法、API 错误、未知节点类型和路径逃逸均拒绝（验证：安全错误测试）
- [x] 缺 SKILL.md 或下载后的 SKILL.md 解析失败时拒绝（验证：post-download validation）
- [x] 目标 Skill 目录已存在时不覆盖任何文件（验证：existing target 测试）
- [x] 成功安装只通过同文件系统 atomic rename 暴露完整目录（验证：rename spy + 文件断言）
- [x] 任意失败不留下 staging 或半安装目标（验证：参数化 cleanup 测试）
- [x] 如果环境已有 GITHUB_TOKEN 则作为认证使用；缺失时仍支持公共仓库（验证：header 测试）

## 9. InstallSkill 工具与热注册

- [x] Tool Registry 中可按精确名字 `InstallSkill` 找到工具（验证：工具注册测试）
- [x] InstallSkill Schema 只要求字符串字段 `url`（验证：schema 测试）
- [x] InstallSkill 是 write 工具，默认权限模式会进入审批，Plan Mode 拒绝执行（验证：权限
  集成测试）
- [x] 非法 JSON/URL 和网络/安装失败返回 `is_error=True`（验证：Tool 错误测试）
- [x] 安装成功后依次 reload Loader、调用 on_installed 并返回 Skill 名（验证：mock 顺序断言）
- [x] on_installed 失败时不报告假成功（验证：callback failure 测试）
- [x] 安装完成无需重启，Agent Catalog、`/help` 与补全同时出现新 Skill（验证：TUI 集成测试）

## 10. 编译、静态检查与测试

- [x] `python -m compileall -q src/Arkcode` 通过
- [x] `ruff check .` 无告警
- [x] `ruff format --check .` 通过
- [x] `mypy src/Arkcode` 通过
- [x] Parser/Loader/Executor/Installer/Tools/Command/Prompt 的 Skills 专项测试全部通过
- [x] `pytest -q tests/test_agent.py tests/test_tui.py tests/test_tool.py` 集成回归通过
- [ ] `pytest -q` 全量通过；若存在任务前已记录的无关基线失败，保留未勾选并附对比证据
- [x] `git diff --check` 通过
- [x] `rg "SkillD[e]f" src tests` 无旧类型定义或引用

## 11. 真实 TUI 端到端场景

> 使用 `mktemp -d /tmp/arkcode-skills-e2e.XXXXXX` 创建隔离 workspace；使用合法测试
> Provider 配置。按 `AGENT.md` 优先在 tmux 中运行并保存 capture；tmux 或真实 Provider
> 不可用时，对应条目保持未勾选并记录环境限制。

### 场景 A：启动、Catalog 与管理命令

- [ ] **A1** 创建项目 inline Skill `test-skill/SKILL.md` 后启动 ArkCode，启动过程无异常
- [ ] **A2** `/help` 同时显示 `/skill` 与 `/test-skill`，动态命令描述带 `[skill]`
- [ ] **A3** 输入 `/` 后补全包含动态 Skill；输入 `/test` 后只保留匹配候选
- [ ] **A4** `/skill list` 显示 test-skill、description、project 来源
- [ ] **A5** `/skill info test-skill` 显示 mode/context/path/directory 信息
- [ ] **A6** 上述纯本地操作前后 token 计数不变

### 场景 B：inline、参数与热重载

- [ ] **B1** Skill 正文含 `Target: $ARGUMENTS`，执行 `/test-skill first` 后 Agent environment
  出现 `Target: first`
- [ ] **B2** 主 Agent 只收到一次触发回合，没有重复 user 消息
- [ ] **B3** 不退出 TUI，修改正文为新版本后再次执行，environment 出现新版本且旧版本消失
- [ ] **B4** 修改成非法 YAML 后再次执行，日志有 warning，仍使用最后成功版本

### 场景 C：LoadSkill 自动激活

- [ ] **C1** 用户自然语言请求与 test-skill description 明确匹配时，Agent 调用 LoadSkill
- [ ] **C2** LoadSkill 调用不出现权限审批
- [ ] **C3** tool result 只有简短确认，不显示完整 SOP
- [ ] **C4** 同一 Agent run 的下一 iteration environment 出现完整 SOP

### 场景 D：fork 隔离与回流

- [ ] **D1** 创建 `mode: fork` 的 fork-skill，分别验证 none/recent/full 至少各一次
- [ ] **D2** fork 运行期间主 Conversation 消息数和 Active Skills 不变化
- [ ] **D3** fork 完成后 TUI 显示完整结果，主历史只新增一条 `<system-reminder>` 回流消息
- [ ] **D4** 退出正在运行 fork 的 TUI，进程正常结束且错误日志无 pending task warning

### 场景 E：reload、覆盖与 clear

- [ ] **E1** 创建 name=`review` 的 Skill 并 `/skill reload`，`/review` 执行 Skill 版本
- [ ] **E2** 删除该 Skill 并 reload，内置 `/review` 恢复
- [ ] **E3** 激活 test-skill 后执行 `/clear`，新会话 environment 不再含 Active Skills
- [ ] **E4** `/clear` 后 `/skill list` 仍包含 Catalog，旧会话仍可通过 `/resume` 找到
- [ ] **E5** 添加坏 Skill 后 reload，日志出现单条 warning，test-skill 仍正常可用

### 场景 F：安装与权限

- [ ] **F1** 模型调用 InstallSkill 时出现写操作权限审批；Plan Mode 下直接拒绝
- [ ] **F2** 使用 MockTransport 的集成场景安装成功后，不重启即可在 `/help` 和补全看到新 Skill
- [ ] **F3** 模拟超限或缺 SKILL.md，TUI 显示错误，用户目录没有半安装文件

### 场景 G：收尾

- [ ] **G1** `/exit` 正常结束 ArkCode/tmux 会话
- [ ] **G2** capture 与测试输出整理到本次验收报告，每个场景至少一份可复核证据
- [ ] **G3** 删除隔离 workspace；不删除或修改用户原有 Skill、会话及测试外文件

## 12. 文档一致性

- [x] spec.md 的每条 F/N 需求至少对应上面一个验收项
- [x] plan.md、task.md、checklist.md 全部使用 `SkillMeta/SkillLoader/SkillExecutor`
- [x] 四份文档中的源码路径全部指向当前 `src/Arkcode/` 结构
- [ ] task.md 的 T1-T13 均有真实验证证据并勾选
- [x] checklist 所有未通过项都有实际结果、原因和后续动作，不用推断标记通过

## 完成准则

- 上述所有非可选 checkbox 均已获得运行或观察证据。
- 全量质量门禁无本功能引入的失败。
- 真实 TUI 的核心链路至少覆盖：加载 → Catalog → 显式 inline → LoadSkill → fork →
  reload → clear。
- 工作区没有测试 staging、临时 Skill 或冲突检测残留。

## 验收证据（2026-08-08）

- Skills 相关定向回归：182 passed；包含权限、隔离、认证、回滚与热注册证据。
- 质量门：compileall、ruff check、ruff format --check、mypy、git diff --check 均通过。
- 全量 pytest：384 passed、1 failed；失败为任务开始前已记录的
  `tests/test_mcp_config.py::test_documented_example_is_a_valid_three_server_config`，
  原因是仓库缺少 `docs/mcp/mcp-servers.example.yaml`，与 Skills 改动无关。后续动作：
  补回该 MCP 示例文件后重跑全量测试。
- 真实 TUI：当前环境未安装 tmux，且没有可用于真实模型调用的测试 Provider 凭据。
  按 T13.8，场景 A-G 保持未勾选；后续动作是在具备 tmux 与隔离测试凭据的环境中按
  T13.1-T13.7 执行并保存 capture。
- 自动化测试使用 pytest `tmp_path` 隔离项目/用户 Skill 与 session；未创建或删除用户
  原有 Skill，也未在仓库留下安装 staging。
- Spec 映射：F1-F5 → §1-2；F6-F7 → §5；F10-F11 → §3-4；
  F12-F14 → §6；F17-F18 → §2/§7；F19 → §8-9；F20 → §2；
  N1/N5 → §2；N2 → §4；N3 → §5。
