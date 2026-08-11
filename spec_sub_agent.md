# SubAgent 机制 Spec

## 背景

ArkCode 目前是单 Agent 架构：所有任务在同一个对话上下文里执行。这导致两个问题：

1. **上下文污染**：长任务后再做无关任务,前序中间结果(读过的文件、diff、错误回放)成为后续任务的噪声,token 飙升、响应质量下降
2. **无法并行**：没有把独立子任务分发出去并行执行的机制,主对话被长任务阻塞

Arkcode 已经有「子 Agent 雏形」：

- ch11 Skill fork 模式通过 `agent.with_allowed_tools` 创建受限子 Agent(`tui/skill_fork.py` 的 `run_sub_agent`),走 `sub_agent.run(...)` 跑完一轮
- `Conversation.from_messages` / `replace_messages` 已支持深拷贝消息列表

但还缺：
- 没有统一的、可被主 Agent 主动调用的 **Agent 工具**——子 Agent 只能由 Skill fork 触发
- 没有 **角色定义文件** 加载机制(Agent 角色全部写死在 fork 闭包里)
- 没有 **后台任务管理**——所有子 Agent 当前都是阻塞前台模式
- 没有 **工具过滤多层防线**——子 Agent 理论上可以无限嵌套
- Skill fork 与未来 SubAgent 工具两套代码并存

本章把上述能力补齐,让 Arkcode 从单 Agent 进化到可分发任务的主从架构。

## 目标

- **G1**:提供统一的 Agent 工具,主 Agent 通过 `subagent_type` 参数选择预定义角色或留空走 Fork 路径;工具列表对模型始终稳定(不因角色定义增减而变化)
- **G2**:子 Agent 拥有独立的运行时状态——**消息**、**临时权限账本**、**文件读缓存**、**token 计数**;共享基础设施——LLM 客户端、Hook 引擎、文件系统、`tool.Registry` 与带作用域的长期权限规则来源;共享规则来源不等于共享临时授权
- **G3**:支持两种创建模式:
  - **定义式**:指定 `subagent_type`,从空白对话 + 预定义角色 prompt 启动
  - **Fork 式**:不指定 `subagent_type`,克隆父对话历史并注入 Fork Boilerplate,借 prompt cache 降首次请求成本
- **G4**:角色定义为 Markdown + YAML frontmatter 文件;支持多来源加载,优先级:项目级 > 用户级 > 内置 > 插件;同名定义按 source 优先级覆盖,前者覆盖后者
- **G5**:子 Agent 以 **RunToCompletion** 模式执行——任务直接注入对话,模型不再调工具即结束,返回最后一条 assistant 文本作为结果
- **G6**:子 Agent 在工具调用时遇到权限判定,按统一顺序处理:① 系统安全约束与受保护路径 → ② 匹配当前 Agent 作用域的长期规则 → ③ 当前子 Agent 自己的临时权限账本 → ④ 角色 frontmatter 的 `permission_mode` → ⑤ 仍无法决定时升级到主 TUI 询问用户(子 Agent 暂停、用户响应、子继续)
- **G7**:支持后台任务:三种进入方式——① 显式 `run_in_background:true`、② 前台超时 120 秒自动切后台、③ ESC 手动切后台;Fork 路径无条件后台;Fork Boilerplate 注入到子 Agent 首条消息约束其行为
- **G8**:后台执行跑完通过 `<task-notification>` 自动注入主对话(主 Agent 下次 turn 即看到);主 Agent可通过 `JobList`/`JobGet`/`JobStop` 工具主动查询和操控,可通过 `JobSend` 给已跑完且上下文仍保留的 SubAgent 续派任务;`Task*` 与 `SendMessage` 名称保留给 Agent Team 的共享任务板和团队邮箱
- **G9**:工具过滤多层防线阻断子 Agent 无限嵌套——定义式 SubAgent 从工具列表移除 Agent;Fork 为保持父工具 schema 与 prompt cache 只保留 Agent 定义,但执行入口、调用来源与 Boilerplate 标记三层都拒绝真正启动;后台白名单与定义层 `tools`/`disallowed_tools` 继续收窄业务能力
- **G10**:复用 SubAgent 底座统一 Skill fork 路径——`tui/skill_fork.py` 的 `run_sub_agent` 改为调用 SubAgent 公共启动函数,两条路径走同一段 agent 构造逻辑
- **G11**:内置 3 个角色——`general-purpose`(全工具)、`explore`(只读探索,haiku)、`plan`(只读规划);所有角色名统一只允许小写字母、数字和连字符;插件级保留接口占位但本期不实现真插件加载,加载顺序里插件来源恒为空

## 功能需求

### Agent 工具

- **F1**:新建 `Agent` 工具,参数(JSON Schema):
  - `prompt`(string,必填):交给子 Agent 的任务指令
  - `description`(string,必填):一句话描述任务,供 UI 展示
  - `subagent_type`(string,可选):指定预定义角色名,留空时走 Fork 路径
  - `model`(string,可选):模型覆盖,取值 `haiku` / `sonnet` / `opus` / `inherit`;留空沿用 Agent 定义的 model
  - `run_in_background`(bool,可选):true 时强制后台启动;Fork 路径忽略此字段(无条件后台)
  - `name`(string,可选):给本次启动的子 Agent 命名,供 JobSend 用;同名后启动的覆盖前面的弱引用
- **F2**:Agent 工具的 `execute`:
  - subagent_type 非空:`catalog.resolve(name)` 取定义;不存在则返回结构化错误「未知 subagent_type: X」
  - subagent_type 为空:走 Fork 路径,从 `catalog` 取「fork 默认基础定义」(prompt body=Fork Boilerplate)
  - 按 `run_in_background` 与 Fork 强制规则,选择 inline 跑(阻塞返回 final_text)或 background 跑(返回 `{job_id, status:"async_launched"}`)
- **F3**:Agent 工具被全局禁止列表 `ALL_AGENT_DISALLOWED_TOOLS` 标记——定义式 SubAgent 构造工具集时看不到 Agent 工具;Fork 是唯一例外,为保持 schema 稳定保留 Agent 定义但执行入口始终拒绝调用

### Agent 定义文件

- **F4**:Agent 定义文件是 Markdown,以 `---` frontmatter 块开头、紧跟正文(角色 instructions);frontmatter YAML 字段:
  - `name`(必填):角色名,长度 1-32 且必须匹配 `^[a-z0-9-]+$`;大写字母、下划线、空格与其他符号一律拒绝
  - `description`(必填):一句话描述,用于 Agent 工具的 `subagent_type` 文档与 UI 列表
  - `tools`(可选,list[str]):工具白名单
  - `disallowedTools`(可选,list[str]):工具黑名单
  - `model`(可选):`haiku` / `sonnet` / `opus` / `inherit`,缺省 `inherit`
  - `maxTurns`(可选,int):最大迭代轮数,缺省继承全局 `max_iterations=25`
  - `permissionMode`(可选):`default` / `acceptEdits` / `plan` / `bypassPermissions` / `dontAsk`,缺省 `default`;`dontAsk` 是子 Agent 专属——自动批准所有规则未命中的工具
  - `background`(可选,bool):缺省 false;true 时 Agent 工具忽略 `run_in_background` 参数、强制后台
- **F5**:Catalog 三层加载(本期插件级恒为空),顺序:
  1. 项目级:`<root>/.Arkcode/agents/*.md`
  2. 用户级:`~/.Arkcode/agents/*.md`
  3. 内置级:随包发布的 `Arkcode/subagent/builtin/*.md`(通过 `importlib.resources` 读取)
- **F6**:同名定义按 source 优先级覆盖——项目级 > 用户级 > 内置级;`resolve(name)` 返回优先级最高的版本
- **F7**:Catalog 启动期加载,加载失败的单个文件(frontmatter 不合法、name 重名以外的字段错)走 stderr 警告并跳过,不阻断启动
- **F8**:本章不引入插件加载器——`SourcePlugin` 常量保留供未来扩展;加载顺序里第四层恒为空列表

### 子 Agent 运行时

- **F9**:扩展 `agent.Agent` 增加 `async def run_to_completion(self, conv, task) -> str` 方法:
  - 把 `task` 作为 user 消息追加到 conv
  - 进入 ReAct 循环,max_turns 由 `Agent.max_turns` 决定(子 Agent 用 frontmatter,主 Agent 不变=25)
  - 模型不再调工具时结束循环,取末尾 assistant 文本返回
  - 触达 max_turns 时进入独立 `limit_reached` 终态,保留最后一条 assistant 文本并记录明确原因;不得同时返回成功又抛 `MaxTurnsReached`
  - 同一段循环代码与主对话 `run` 共用,不重复实现
- **F10**:新增 Agent 构造选项(通过 `Agent.__init__` 关键字参数 / `dataclass` 字段):
  - `instructions_content: str`:角色定义正文。子 Agent 启动时将其追加到 Arkcode 不可替换的基础 system prompt 之后;不得覆盖基础协议、安全约束、工具说明或环境上下文
  - `provider: Provider`:让子 Agent 用与父不同的 provider(model 覆盖时切换)
  - `max_turns: int`:限制本 Agent 的最大迭代轮数
  - `permission_mode: PermissionMode`:子 Agent 启动模式
  - `permission_scope: PermissionScope`:当前 Agent 的长期规则匹配作用域;由启动器根据主 Agent / subagent type / subagent instance 构造
  - `permission_ledger: PermissionLedger`:当前 Agent 独立的临时授权账本,不得引用父 Agent 或其他 SubAgent 的账本
- **F11**:子 Agent 的运行时状态隔离——独立 `SessionRuntime`、独立 `Conversation`、独立 token 计数、独立临时权限账本;共享 `Provider`(除非 `provider` 覆盖)、`Registry`、长期权限规则存储与 `HookEngine`;共享 Registry 时不得共享会导致跨 Agent 污染的可变工具状态

### 权限决策

- **F12**:长期权限规则支持 `global / main-agent / subagent-type:<type> / subagent-instance:<agent-id>` 四类作用域。主 Agent 与 SubAgent 可共享规则存储,但只匹配适用于当前身份的规则。工具调用权限决策顺序为:
  1. 系统安全约束、危险命令与受保护路径;deny 永远优先,`bypassPermissions` / `dontAsk` 也不能绕过
  2. 匹配当前 `permission_scope` 的长期规则
  3. 当前 SubAgent 自己的临时权限账本;主 Agent 的单次/会话授权、`main-agent` 规则和其他 SubAgent 的临时授权均不适用
  4. 子角色 `permission_mode` 兜底——`dontAsk` 自动放行系统约束未拒绝且长期规则未判为 deny 的 Ask 类操作;`acceptEdits` 放行写;`bypassPermissions` 放行普通权限检查;其他模式走原 `mode_fallback`
  5. 仍是 Ask 时升级到主 TUI:子 Agent 暂停,主 TUI 弹审批框(标注 `[来自 SubAgent X]`),用户响应后子 Agent 继续
- **F12a**:SubAgent 审批结果至少支持 `Deny Once / Allow Once / Allow for This SubAgent / Save as Project Rule`;前三项只写当前 SubAgent 临时账本,保存项目规则必须单独确认并明确写入的作用域
- **F13**:升级到主 TUI 的通信机制——子 Agent 把 `ApprovalRequest` 推到自己的事件队列(`asyncio.Queue`),队列被 TaskManager / SkillFork host 转发到主 TUI 的 Approval 弹窗;主 TUI 响应后 Outcome 通过 `respond` `asyncio.Future` 回传

### 后台任务管理

- **F14**:新建 `task.Manager`,持有 `dict[str, BackgroundTask]`,内部继续复用 mewCode 风格的 TaskManager 命名;对模型暴露的是 Job 语义。提供 `launch(ctx, agent, task_text)`、`get(id)`、`list()`、`stop(id)`、`adopt_running(...)`、`subscribe_done() -> asyncio.Queue[str]`
- **F15**:`BackgroundTask` 字段:
  - `id`(str,manager 生成)
  - `name`(str,可选,F1 的 `name` 字段)
  - `sub_agent`(Agent)
  - `conv`(Conversation,子对话)
  - `task`(str,初始任务)
  - `status`(`preparing` / `running` / `completed` / `failed` / `cancelled`);需要异步准备 Worktree 等运行环境时先进入 preparing
  - `result`(str,跑完后填)
  - `err`(Exception | None)
  - `start_time` / `end_time`
  - `cancel`(`asyncio.Event` 或 `asyncio.Task.cancel`)
  - `usage`(`TokenUsage`,token 计数)
  - `tool_count`(int,工具调用次数计数器)
  - `last_activity`(str,最近一次工具名)
  - `worktree_name` / `worktree_path` / `worktree_branch` / `worktree_base_commit`(可选,`isolation:worktree` 后台任务在准备完成后填入)
- **F16**:`launch` 内部 `asyncio.create_task`:`sub_agent.run_to_completion(conv, task)` → status 终态 → 推内部 `task_id` 到 `done` 队列 → TUI 消费后以对外 `job_id` 注入 `<task-notification>`
  - 若任务带异步环境准备器(如 Worktree),runner 先以 `preparing` 执行 prepare,成功后转 `running`;prepare/run/cleanup 共用一个任务所有权与 finally 清理链
- **F17**:三种进入后台的方式:
  1. **显式**:Agent 工具 `run_in_background:true` → 直接调 `launch`,工具 result 立刻返回 `{job_id, status:"async_launched"}`
  2. **超时自动**:Agent 工具默认前台 inline 跑,但前台 run 启动后开计时器(120 秒,常量 `AUTO_BACKGROUND_MS`),超时则:
     - 取消前台事件消费协程
     - 调 `manager.adopt_running(agent, conv, task_handle, cancel_event, events, partial)` 接管事件流继续后台跑
     - Agent 工具 result 改返回 `{job_id, status:"timed_out_to_background"}`
  3. **ESC 手动切**:用户在前台子 Agent 跑动期间按 ESC → TUI 调 `manager.adopt_running(...)`,与超时路径走同一逻辑
- **F18**:Fork 路径 `run_in_background` 字段被强制视为 true(代码内 override)
- **F19**:后台执行完成时,Manager 把内部 `task_id` push 到 `done` 队列;对外统一称为 `job_id`;TUI 在主事件循环消费,把如下文本作为 system reminder 拼到主对话下一次 reminder 区(不打断当前对话):
  ```
  <task-notification>
  Job X (name="Y"): completed
  Result: <最终文本>
  </task-notification>
  ```

### 后台任务工具

- **F20**:新增 4 个内置工具:
  - `JobList`:无参,返回当前 manager 中所有仍保留的执行实例简要列表(`job_id`、name、status、tool_count、last_activity)
  - `JobGet`:`{job_id}`,返回指定执行实例的完整状态(含 result / err)
  - `JobStop`:`{job_id}`,调 `manager.stop` 触发取消;返回 `{status:"cancellation_requested"}`
  - `JobSend`:`{name, message}`,按 name 找到已终止但 Agent/Conversation 仍保留的 SubAgent,把 message 作为新 user 消息追加到 conv 并启动新一轮执行;新一轮创建新的 `job_id`,复用原 Agent 与 Conversation;运行中 Agent 不允许重入,找不到或上下文已释放则返回错误
- **F21**:本模块不实现任何 `Task*` 或团队版 `SendMessage`;这些名称和 schema 由 Agent Team 模块独占。Hook subagent stub 本期也可暂未对接

### Fork 路径

- **F22**:`build_forked_messages(parent_conv)` 做三件事:
  1. 深拷贝 parent_conv 的全部消息
  2. 把末尾 assistant 中未完成的 `tool_use`(无对应 ToolResult)包装为 placeholder ToolResult,使消息格式合法
  3. 在末尾追加 user 消息,内容 = Fork Boilerplate + 任务文本
- **F23**:Fork Boilerplate 是一段 `<fork_boilerplate>` 包裹的指令,核心约束:
  - 不能再 Fork(再 Fork 会被 QuerySource 拦截 / Boilerplate 标记扫描兜底)
  - 不要对话 / 提问 / 请求确认
  - 直接使用工具
  - 严格限制在分配的任务范围内
  - 最终报告以 `Scope:` 开头,500 字以内
- **F24**:Fork 子 Agent 嵌套阻断三道闸:
  1. **工具列表层**:Fork 子 Agent 的工具列表保留 Agent 工具(继承自父),但调用 Agent 工具时
  2. **QuerySource 检测**:Agent 工具入口检测 caller 来源(检查父链),若 caller 是 Fork 路径产生,直接 `is_error=True` 返回「Fork 子 Agent 不能再启动 Agent」
  3. **Boilerplate 标记扫描**:对话历史里如果含 `<fork_boilerplate>` 标记(QuerySource 失效兜底),也认定是 Fork 嵌套
- **F25**:定义式子 Agent 不走 Boilerplate(从空白启动);嵌套阻断靠 `ALL_AGENT_DISALLOWED_TOOLS` 全局禁止 Agent 工具

### 工具过滤多层防线

- **F26**:全局禁止列表 `ALL_AGENT_DISALLOWED_TOOLS = ["Agent"]`(本期范围最小,后续可加 AskUserQuestion / JobStop);定义式 SubAgent 启动时从工具列表中剔除这些;Fork 按 F24 克隆父 schema 后在运行时拒绝
- **F27**:自定义 Agent 额外限制 `CUSTOM_AGENT_DISALLOWED_TOOLS`:本期为空,接口预留(用于将来用户自定义 Agent 一律不可访问某些核心工具)
- **F28**:后台 Agent 白名单 `ASYNC_AGENT_ALLOWED_TOOLS`,只列基础工具:
  `read_file, write_file, edit_file, glob, grep, bash, load_skill, install_skill`
  以及所有 MCP / Skill 工具。Fork/run_in_background 任意一种成立的子 Agent 工具集再叠加此白名单交集。
- **F29**:Agent 定义层 `tools`(白名单)与 `disallowed_tools`(黑名单)组合应用——白名单先确定范围,黑名单再排除
- **F30**:定义式 SubAgent 的工具过滤合并执行顺序(在 Agent 工具的 `execute` 内构造时;Fork 使用 F24 的专用克隆路径):
  1. 起点 = registry 的全部工具
  2. 去掉 `ALL_AGENT_DISALLOWED_TOOLS`
  3. 如果是后台 → 取交集 `ASYNC_AGENT_ALLOWED_TOOLS`
  4. 应用定义的 `disallowed_tools` 黑名单
  5. 应用定义的 `tools` 白名单(空白名单 = 不再收窄)
  6. 注入到子 Agent 的 `Agent(allowed_tools=allowed)`
- **F31**:工具列表对模型稳定——以上过滤只发生在子 Agent 构造时,主 Agent 看到的工具列表不变

### 内置角色与 Skill fork 改造

- **F32**:内置 3 个角色文件,随包发布:
  - `general-purpose.md`:无 disallowedTools,用 `inherit` 模型,maxTurns=30,permissionMode=default
  - `explore.md`:disallowedTools=[write_file, edit_file],model=haiku,maxTurns=30,permissionMode=default
  - `plan.md`:disallowedTools=[Agent, write_file, edit_file],maxTurns=15,permissionMode=plan(plan 是已有的权限模式)
- **F33**:Skill fork 改造——`tui/skill_fork.py` 的 `run_sub_agent` 改为:
  1. 构造一个临时 `subagent.Definition`(name="skill-fork-<skillname>",disallowed_tools=skill.allowed_tools 反推 / 等同 skill 自身的 allowed_tools),将其当 Fork 路径走
  2. 复用 `agent.run_to_completion` 与 SubAgent 的工具过滤、消息装填路径
  3. 返回 `final_text` 行为不变(`host.append_assistant_message` 仍由 Executor 调)

## 非功能需求

- **N1**:工具列表稳定——主 Agent 看到的工具集不因 `.Arkcode/agents/` 增减或 Agent 工具被调用而变化(防止 prompt cache 抖动)
- **N2**:Fork 路径首次请求命中 prompt cache——`build_forked_messages` 拼接的消息列表与父对话末尾完全一致,系统提示一致
- **N3**:子 Agent 崩溃不影响主程序——`manager.launch` 单独捕获 `asyncio.CancelledError` 并转 `cancelled`,捕获普通 `Exception` 并转 `failed` + 错误信息回灌;`KeyboardInterrupt` / `SystemExit` 等致命 `BaseException` 不伪装为普通任务失败
- **N4**:启动期 fail-fast——内置定义解析失败立刻 raise(代码 bug),用户/项目级定义文件解析失败仅 stderr 警告并跳过
- **N5**:与现有 ch11 Skill 系统、ch12 Hook 系统、ch08 权限系统、ch04 主 Agent loop 协同,不破坏既有测试
- **N6**:配置 `enable_subagent_background`(bool,默认 true)关闭后,Agent 工具的 `run_in_background:true` / 超时切后台 / ESC 切后台全部失效,所有 SubAgent 强制前台同步;Fork 路径在此模式下报错「后台禁用,无法 Fork」
- **N7**:`<task-notification>` 注入主对话不消耗主 Agent 的工具调用配额,不出现在用户视窗(只对模型可见)

## 不做的事

- Worktree 文件隔离(独立章节)
- 多 Agent 团队编排(CrewAI / AutoGen 平等协作风格)
- 后台任务跨会话持久化——主程序退出后任务全部丢失
- 真正的插件系统(`SourcePlugin` 占位)
- 子 Agent 输出 schema 强制结构化(返回纯文本即可)
- Verification Agent 内置开关(`enable_verification_agent` 不实现)
- Agent Team 的 `TaskCreate / TaskGet / TaskList / TaskUpdate / SendMessage` 协作工具(本期 SubAgent 仅提供 `JobList / JobGet / JobStop / JobSend`)
- 跨 SubAgent token 用量汇总到 /status(只在 Manager 内部记录)

## 验收标准

- **AC1**:Agent 工具注册成功,主 Agent 的工具列表里 schema 一致;定义式子 Agent 看不到 Agent 工具,Fork 子 Agent 仅保留 schema 但执行被拒绝(AC5)
- **AC2**:`Agent` 工具调用 `{prompt:"...",subagent_type:"explore"}` 时,主 Agent 看到的 tool_result 是 explore 子 Agent 的最后一条 assistant 文本
- **AC3**:`Agent` 工具调用 `{prompt:"...",subagent_type:"non-existent"}` 时,主 Agent 看到的 tool_result 是结构化错误「未知 subagent_type」
- **AC4**:`Agent` 工具调用不传 subagent_type 时,子 Agent 收到的首条 user 消息以 `<fork_boilerplate>` 起头,且消息列表前缀与父对话一致(可由测试断言)
- **AC5**:Fork 子 Agent 的工具列表里仍有 Agent 工具(F22 设计),但调用 Agent 工具会被 QuerySource 拦截,tool_result 含「Fork 子 Agent 不能再启动 Agent」
- **AC6**:定义式子 Agent 的工具列表里没有 Agent 工具(被 `ALL_AGENT_DISALLOWED_TOOLS` 剔除)
- **AC7**:子 Agent 角色 frontmatter 写 `permissionMode: dontAsk`,bash 等需要 Ask 的工具直接放行,无审批弹窗
- **AC8**:子 Agent 角色 frontmatter 不写 dontAsk,bash 工具触发审批,弹窗带 `[来自 SubAgent X]` 标识
- **AC9**:`run_in_background:true` 时 tool_result 立即返回 `{job_id, status:"async_launched"}`,主 Agent 不阻塞
- **AC10**:前台子 Agent 跑超过 120 秒,自动切后台,主 Agent 看到 tool_result 含 `status:"timed_out_to_background"`
- **AC11**:前台子 Agent 跑动期间用户按 ESC,切到后台,TUI 继续接收主 Agent 输入
- **AC12**:后台子 Agent 跑完,主 Agent 下次 run 的 reminder 区出现 `<task-notification>` 块,含 Result
- **AC13**:`JobList` 工具返回当前后台执行列表,字段含 job_id/name/status/tool_count
- **AC14**:`JobGet({job_id})` 返回 Result;`JobStop({job_id})` 触发取消,执行状态变 cancelled
- **AC15**:`JobSend({name,message})` 让一个已终止但上下文仍保留的 SubAgent 接到新任务,复用 Agent/Conversation 并创建新 job_id;跑完结果作为新 `<task-notification>` 注入主对话
- **AC16**:项目级 `.Arkcode/agents/explore.md` 覆盖内置 `explore`,`resolve("explore")` 返回项目级版本
- **AC17**:Skill fork 模式调用走 SubAgent 底座——`tui/skill_fork.py` 的 `run_sub_agent` 内部只是装饰参数后调 `subagent.launch_fork(...)`(或同等公共函数)
- **AC18**:N6 配置开关 `enable_subagent_background:false` 时,Fork 路径调用 Agent 工具返回结构化错误
- **AC19**:`<fork_boilerplate>` 出现在对话历史里 + Agent 工具被调用 → 拦截(QuerySource 失效兜底)
- **AC20**:子 Agent 普通异常 → status=failed,主 Agent 收到 `<task-notification>` 含错误描述,主程序不崩;取消单独进入 cancelled
- **AC20a**:`background + isolation:worktree` 立即返回 job_id,执行状态可观察 `preparing → running → 终态`;准备失败、运行取消和清理保留信息均通过同一条 `<task-notification>` 返回
- **AC21**:全新项目级自定义 Agent(`.Arkcode/agents/<name>.md`)被 Catalog 加载;`subagent_type=<name>` 调用时,frontmatter 的 disallowedTools / permissionMode / maxTurns 与正文 instructions 全部生效——子 Agent 看不到黑名单工具、按指定 mode 决策、不超 turns,且基础 Arkcode system prompt 保留、角色 instructions 追加在其后
- **AC22**:Agent 定义 frontmatter 的名称、字段类型、maxTurns 或 permissionMode 非法时,该文件 stderr warning 后跳过;名称 `explore-v2` 合法,`Explore` / `foo_bar` / `foo bar` 非法;model 标识不在加载期固定白名单校验,实际启动时 Provider 创建失败则本次调用明确失败且不静默回退父模型
