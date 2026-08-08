# Skill 系统 Spec

## 1. 背景

ArkCode 用户会反复输入一组类似的 prompt（commit message 规范、代码审查清单、跑测试的项目类型识别）。当前所有 prompt 要么写死在源码 Slash Command（`/review`）里，要么用户每次手敲，两个痛点：(1) 不能复用与分发，(2) 长流程任务缺少上下文隔离，中间状态会污染主对话。Skill 把可复用 SOP 装进可编辑的 Markdown 文件，配渐进式披露与执行模式，同时解决这两个问题。

## 2. 目标

把 `SKILL.md` 升级为「带 frontmatter + 资源」的能力包。启动时只把 `name + description` 注入对话给 Agent 看；Agent 通过 `LoadSkill` 工具按需把完整 SOP 钉到环境上下文。`inline` 模式 SOP 在主对话内执行，`fork` 模式独立子 Agent 隔离执行后把结果回流。`/` 显式触发与意图识别自动触发共用同一套执行器。

## 3. 功能需求

### 解析与加载
- F1: `SkillMeta`（`src/Arkcode/skills/parser.py`）字段：`name / description / prompt_body / mode / model / context / source_path / is_directory`；`mode` 取 `inline | fork`（默认 `inline`），`context` 取 `full | recent | none`（默认 `full`，仅 fork 模式生效）
- F2: 单文件 `*.md`（YAML frontmatter + body）与目录型（`/SKILL.md` + `references/*.py`）两种磁盘布局；`SkillLoader._scan_directory` 区分两类
- F3: 两级搜索路径加载（`src/Arkcode/skills/loader.py`），优先级 `项目 .Arkcode/skills/` > `~/.Arkcode/skills/`；首次出现的 name 占位，后续同名跳过；解析失败单条 `warning` 日志并跳过
- F4: 启动期 `SkillLoader.load_all` 解析所有 frontmatter+body 进内存；`SkillLoader.get(name)` 每次重读源文件实现热重载，失败回退缓存（`src/Arkcode/skills/loader.py`）

### 执行
- F5: `substitute_arguments(prompt_body, args)`（`src/Arkcode/skills/parser.py`）把 `$ARGUMENTS` 替换为参数；没有占位符则原样返回
- F6: inline 执行：`SkillExecutor.execute_inline`（`src/Arkcode/skills/executor.py`）渲染 body 后调用 `Agent.activate_skill(name, body)` 钉到 env context，主循环每轮迭代重建 environment 时 SOP 都注入
- F7: fork 执行：`SkillExecutor.execute_fork`（`src/Arkcode/skills/executor.py`）创建独立 `Conversation` 与 `SessionRuntime`，按 `context` 字段决定历史携带（`full` = 摘要 / `recent` = 最近 5 条 / `none` = 完全隔离），累计 `AgentEvent.text` 到 `done=True` 后回流

### LoadSkill 工具与 Skill Catalog 注入
- F10: `LoadSkill`（`src/Arkcode/tool/load_skill.py`）read-only 工具，输入 `{name: str}`；调用 `SkillLoader.get` 取 skill → `Agent.activate_skill` 钉 SOP → 返回简短确认（不返回完整 SOP，避免 tool_result 占用空间）
- F11: 启动期由 `src/Arkcode/prompt/builder.py` 构建「Available Skills」段（只含 name/description 与 LoadSkill 指引），通过 `Agent.set_skill_catalog` 注入 environment context

### 命令集成
- F12: 每个 skill 由 `register_skill_commands`（`src/Arkcode/command/skills.py`）注册为 `/` 短命令，描述末尾标注 `[skill]`；mode 字段决定运行时分支：inline 调 `execute_inline` 后再发送一次 user message 触发 loop，fork 则创建受 App 跟踪的后台任务并把结果作为 `<system-reminder>` 插入
- F13: `/skill list | info <name> | reload` 管理子命令（`src/Arkcode/command/skills.py`）：list 列出已加载 skill 与来源；info 显示规范化 frontmatter 与文件路径；reload 重新扫描两级目录并重新注册命令
- F14: skill 命令与已有 slash 命令同名时，skill 版本优先覆盖旧 handler

### 热更新与清理
- F17: `SkillLoader.get(name)` 每次调用都 `parse_skill_file(source_path)` 重读，文件修改即时生效；解析失败回退 `_cache` 中的旧版本并记 warning（`src/Arkcode/skills/loader.py`）
- F18: `/clear` 命令成功创建新会话后通过 `src/Arkcode/tui/commands.py` 调 `Agent.clear_active_skills()`，把激活 skill 列表清空

### 远程安装
- F19: `InstallSkillTool` 让用户把 URL 发给 Arkcode、由 Agent 自动安装到 `~/.Arkcode/skills/<name>/`
  - 支持三种 URL：`skills.sh` / `github.com tree` / `raw.githubusercontent.com`
  - 走 GitHub Contents API 递归拉取目录树（无需本地 git），单文件 ≤1 MiB、总大小 ≤8 MiB、文件数 ≤64、深度 ≤4
  - 暂存到兄弟 tempdir，验证含 SKILL.md 后 atomic rename 到位
  - 安装后自动 reload catalog + 重新注册斜杠命令，无需重启即可使用

### 来源标识
- F20: `SkillLoader.get_source_label`（`src/Arkcode/skills/loader.py`）按路径前缀返回 `project | user`

## 4. 非功能需求

- N1: 单个 skill 文件解析失败不能阻断其他 skill 加载，错误走 `logging.warning`
- N2: `LoadSkill` 工具调用不弹权限提示（read-only 类别）
- N3: fork 模式必须隔离 `Conversation` 与 `SessionRuntime`，主对话状态不被子 Agent 修改
- N5: 项目级与用户级同名 skill 冲突时，项目级优先

## 5. 设计概要

### 核心数据结构
- `SkillMeta`（`src/Arkcode/skills/parser.py`）：dataclass，含 `mode / model / context` 三个执行字段 + `source_path / is_directory` 元信息
- `SkillLoader`（`src/Arkcode/skills/loader.py`）：name → `SkillMeta`；持有 `_skills` 与 `_cache` 两份字典，热更新失败回退缓存
- `SkillExecutor`（`src/Arkcode/skills/executor.py`）：`execute_inline(skill, args) -> None` 与 `execute_fork(skill, args) -> str`
- `LoadSkillTool`（`src/Arkcode/tool/load_skill.py`）：实现 `Tool` 抽象类；持有 `SkillLoader` 与 `Agent` 引用
- Agent 新增字段与方法：`active_skills: dict[str, str]`、`_skill_catalog: str`、`activate_skill(name, body)`、`clear_active_skills()`、`set_skill_catalog(catalog)`（`src/Arkcode/agent/agent.py`）

### 主流程
1. 启动：`ArkCodeApp.__init__` → `SkillLoader(workspace).load_all()` → 注册 `LoadSkillTool/InstallSkillTool` → 构造 `Agent` → 注入 LoadSkill Agent → 构造 `SkillExecutor` → 写入 Catalog → 注册动态命令
2. system prompt 注入：`src/Arkcode/agent/agent.py` 每轮迭代重建 environment block，把 Catalog 与 Active Skills 渲染结果拼入动态环境段
3. 稳定 system 仍由 `src/Arkcode/prompt/builder.py` 构建；动态 SOP 不进入稳定缓存块
4. 显式调用（以 inline skill 为例，如用户自建的 `/commit`）：`register_skill_commands` 注册的 handler → `executor.execute_inline(skill, args)` → `agent.activate_skill(name, rendered_body)` → 再 `ctx.ui.send_user_message(trigger)` 触发 Agent loop
5. 意图识别：Agent 调 `LoadSkill({name: ""})` → `loader.get` → `agent.activate_skill` → 返回 `"Skill '' activated. SOP pinned to environment context."`
6. fork 调用（以 fork skill 为例，如用户自建的 `/review`）：handler 创建受 App 跟踪的 task → `executor.execute_fork` 新 Conversation/Runtime + 临时 Agent + 累计 `AgentEvent.text` 到 done → 把最终文本包装为 `<system-reminder>` 插入主对话
7. `/clear`：handler → reset conversation → `agent.clear_active_skills()` → 后续轮 environment 不再注入旧 SOP

### 调用链
- 启动：`src/Arkcode/tui/app.py` 的 `ArkCodeApp.__init__` → `SkillLoader.load_all` → Provider 激活后 `register_skill_commands`
- inline 显式（例如 `/commit`）：用户输入 skill 命令 → command handler → `executor.execute_inline` → `agent.activate_skill` → `ctx.ui.send_user_message` → Agent loop（每轮 env 注入 SOP）
- fork 显式（例如 `/review`）：用户输入 skill 命令 → handler → `asyncio.create_task(execute_fork)` → `system message`
- 意图触发：Agent 在某轮调用 `LoadSkill` → `loader.get` → `agent.activate_skill` → 下一轮 SOP 钉在 env 里
- 清理：用户 `/clear` → `handle_clear` → conversation reset + `agent.clear_active_skills`

### 与其他模块的交互
- 上行依赖：`src/Arkcode/tui/app.py`（组装 Loader、Tool、Executor 与命令）、`Agent`（`active_skills` + env 注入）、`Conversation`/`SessionRuntime`（fork 独立实例）
- 下行：`SkillExecutor` 使用当前 `Arkcode.agent.Agent`、`Arkcode.conversation.Conversation` 与 `Arkcode.tool.Registry` 公共协议

## 7. 完成定义

见 [checklist.md](checklist.md)，所有条目勾上即完成。
