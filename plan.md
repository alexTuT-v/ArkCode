# Skill 系统 Plan

> 本设计以 `spec.md + task.md + checklist.md` 为权威需求来源，并按当前仓库的
> `src/Arkcode/` 包结构、Tool 协议、Agent 事件与 Textual TUI 实际接口落地。

## 1. 架构概览

新增 `Arkcode.skills` 包，使用 `SkillMeta / SkillLoader / SkillExecutor` 三个核心组件：

- `SkillMeta`：保存 frontmatter、正文、执行模式与来源路径。
- `SkillLoader`：扫描项目级和用户级目录，处理优先级、缓存、热重载与来源标识。
- `SkillExecutor`：渲染 `$ARGUMENTS`，执行 inline 或 fork Skill。

现有模块只承担各自边界内的集成职责：

- `Arkcode.agent` 保存 Active Skills 与 Catalog 文本，每轮 Agent 迭代重建动态 environment。
- `Arkcode.tool` 提供 `LoadSkillTool` 和 `InstallSkillTool`。
- `Arkcode.command` 支持参数化命令、Skill 命令覆盖与 `/skill` 管理命令。
- `Arkcode.tui` 负责组装 Loader、Executor、工具与命令，并把 fork 结果回流到主会话。
- `Arkcode.prompt` 只负责渲染 Catalog 和 Active Skills，不反向依赖 `skills` 包。

依赖方向保持单向：

```text
parser <- loader <- executor
   ^         ^          |
   |         |          v
 tools -----+       agent / conversation
   ^                    ^
   |                    |
 command <----------- tui
```

## 2. 统一后的行为决策

| 决策点 | 统一选择 |
|--------|----------|
| 核心模型 | `SkillMeta + SkillLoader + SkillExecutor` |
| 磁盘布局 | 同时支持顶层 `*.md` 与目录型 `*/SKILL.md` |
| 默认执行模式 | `mode=inline` |
| fork 默认上下文 | `context=full` |
| 非法 frontmatter | 抛 `SkillParseError`；Loader warning 后跳过该 Skill |
| 参数替换 | 只替换 `$ARGUMENTS`；无占位符时正文保持原样 |
| 项目/用户冲突 | 项目级优先；扫描项目后扫描用户，首次 name 保留 |
| 激活状态 | `Agent.active_skills: dict[str, str]`，重复激活覆盖同名正文 |
| inline 触发职责 | Executor 只激活；命令 handler 再发送一次触发消息 |
| fork 隔离 | 独立 `Conversation + SessionRuntime + Agent` |
| fork 回流 | 通过 provider-neutral 的 `<system-reminder>` 上下文消息写回主会话并展示 |
| 远程安装 | GitHub Contents API；不调用本地 git，不接收任意 ZIP |
| Skill 命令冲突 | Skill 命令覆盖已有 slash 命令；reload 后可恢复被移除的内置命令 |

## 3. 核心数据结构与接口

### 3.1 SkillMeta

文件：`src/Arkcode/skills/parser.py`

```python
@dataclass(frozen=True, slots=True)
class SkillMeta:
    name: str
    description: str
    prompt_body: str
    mode: Literal["inline", "fork"] = "inline"
    model: str | None = None
    context: Literal["full", "recent", "none"] = "full"
    source_path: Path = Path()
    is_directory: bool = False
```

公开接口：

```python
class SkillParseError(ValueError): ...

def parse_frontmatter(raw: str) -> tuple[dict[str, object], str]: ...
def parse_skill_file(path: Path, *, is_directory: bool = False) -> SkillMeta: ...
def substitute_arguments(prompt_body: str, args: str) -> str: ...
```

校验规则：

- frontmatter 必须由开头和结束 `---` 包围，且 YAML 根节点必须是 mapping。
- `name` 必须匹配 `^[a-z][a-z0-9-]*$`。
- `description` 必须是非空字符串。
- `mode` 只能是 `inline | fork`，缺省 `inline`。
- `context` 只能是 `full | recent | none`，缺省 `full`。
- `model` 缺省为 `None`；非空时必须是字符串。
- 正文允许为空；Loader 和 Executor 不额外改写正文。

### 3.2 SkillLoader

文件：`src/Arkcode/skills/loader.py`

```python
class SkillLoader:
    def __init__(self, work_dir: str | Path) -> None: ...
    def load_all(self) -> list[SkillMeta]: ...
    def reload(self) -> list[SkillMeta]: ...
    def get(self, name: str) -> SkillMeta | None: ...
    def get_catalog(self) -> list[tuple[str, str]]: ...
    def get_source_label(self, name: str) -> Literal["project", "user"] | None: ...
```

内部状态：

```python
self._project_dir = work_dir / ".Arkcode" / "skills"
self._user_dir = Path.home() / ".Arkcode" / "skills"
self._skills: dict[str, SkillMeta]
self._cache: dict[str, SkillMeta]
```

扫描规则：

1. 先扫描项目目录，再扫描用户目录。
2. 每层同时识别直接子文件 `*.md` 和直接子目录中的 `SKILL.md`。
3. 文件与目录按路径名字典序扫描，保证结果稳定。
4. name 首次出现即占位，后续同名跳过，因此项目级自然优先。
5. 单条解析失败只记录一次 warning，不阻断其他 Skill。
6. `load_all/reload` 成功解析后同时替换 `_skills` 和 `_cache`。
7. `get(name)` 每次重读其 `source_path`；成功时更新两份缓存，失败时 warning 并返回旧 `_cache`。
8. `get_catalog()` 按 name 字典序返回 name 与 description，不包含 SOP 正文。

### 3.3 SkillExecutor

文件：`src/Arkcode/skills/executor.py`

```python
SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})

class SkillExecutor:
    def __init__(
        self,
        agent: Agent,
        conversation: Conversation,
        provider_config: ProviderConfig,
        registry: ToolRegistry,
        engine: Engine | None,
        version: str,
        work_dir: Path,
    ) -> None: ...

    def execute_inline(self, skill: SkillMeta, args: str) -> None: ...
    async def execute_fork(self, skill: SkillMeta, args: str) -> str: ...
```

inline 路径：

1. `substitute_arguments(skill.prompt_body, args)`。
2. `agent.activate_skill(skill.name, rendered)`。
3. 返回，不直接调用 Provider。
4. Slash handler 通过 `ui.inject_and_send(label, trigger)` 启动主 Agent 回合。

fork 路径：

1. 渲染 `$ARGUMENTS`。
2. 创建无持久化回调的独立 `Conversation`。
3. 根据 `skill.context` 构造历史：
   - `none`：不携带主历史。
   - `recent`：复制主历史最近 5 条 user/assistant 消息，不复制 tool 消息。
   - `full`：用当前 Provider 和现有摘要 prompt 对主历史生成摘要，作为
     `## Previous conversation summary` 消息加入 fork Conversation。
4. 追加渲染后的 Skill 正文作为 fork 的 user 消息。
5. 创建独立 `SessionRuntime`；不复用主 Agent 的 compact/recovery/session 状态。
6. 默认复用当前 ProviderConfig；若 `skill.model` 非空，用
   `dataclasses.replace(provider_config, model=skill.model)` 构建 fork Provider。
7. fork Agent 复用工具对象，但从 Registry 视图中排除 `SYSTEM_TOOL_NAMES`，防止
   `LoadSkill` 修改主 Agent 的 Active Skills。
8. 消费当前 `AgentEvent`：累计 `event.text`，遇 `event.err` 形成可观察错误文本，
   `event.done` 时结束。
9. 返回累计文本；任何普通异常转换为 `[skill <name> failed: <error>]`。
10. `asyncio.CancelledError` 原样上抛，保证应用退出可取消后台任务。

### 3.4 Tool Registry 隔离视图

修改：`src/Arkcode/tool/registry.py`

新增接口：

```python
def without(self, names: Collection[str]) -> Registry: ...
```

返回一个保持原注册顺序、复用同一批 Tool 对象但排除指定名字的新 Registry。fork Agent
使用该视图排除 `LoadSkill`；主 Registry 不被修改。该方法不复制 Tool 内部状态，也不会
绕开既有 timeout、权限检查或 read-only 分类。

## 4. Prompt 与 Agent 集成

### 4.1 Prompt 渲染

修改：

- `src/Arkcode/prompt/builder.py`
- `src/Arkcode/prompt/modules.py`
- `src/Arkcode/prompt/__init__.py`

新增接口：

```python
def render_skill_catalog(items: list[tuple[str, str]]) -> str: ...
def render_active_skills(active: Mapping[str, str]) -> str: ...
```

Catalog 输出只包含：

```text
## Available Skills

- name: description

If the user's request matches a Skill, call LoadSkill to activate it.
```

Active Skills 输出：

```text
## Active Skills

### Skill: name

<完整 SOP>
```

禁止把完整 SOP 放入 Catalog；Active Skills 为空时不输出标题。

### 4.2 Agent 状态

修改：`src/Arkcode/agent/agent.py`

新增字段与方法：

```python
self.active_skills: dict[str, str] = {}
self._skill_catalog = ""

def activate_skill(self, name: str, prompt_body: str) -> None: ...
def clear_active_skills(self) -> None: ...
def set_skill_catalog(self, catalog: str) -> None: ...
```

`_run_unlocked` 在每一次 ReAct iteration 调用 Provider 前重新构造 `System.environment`：

```text
基础 Environment
+ Skill Catalog
+ Active Skills
```

这样 `LoadSkill` 在 iteration N 激活的 SOP 会在 iteration N+1 立即出现。稳定 system
prompt 仍只包含固定模块、项目指令和长期记忆，不让热更新内容污染缓存稳定性。

`/clear` 除了重置 Conversation 和 SessionRuntime，还必须调用
`agent.clear_active_skills()`；Catalog 不清除。

## 5. Tool 集成

### 5.1 LoadSkillTool

文件：`src/Arkcode/tool/load_skill.py`

严格实现当前 `Tool` 抽象：

```python
class LoadSkillTool(Tool):
    read_only = True
    def name(self) -> str: return "LoadSkill"
    def description(self) -> str: ...
    def parameters(self) -> dict[str, object]: ...
    async def execute(self, args: str) -> Result: ...
```

执行流程：

1. JSON 解析 `{name: str}`，非法输入返回 `Result(..., is_error=True)`。
2. Loader 或 Agent 尚未注入时返回 `LoadSkill not properly initialized`。
3. `loader.get(name)` 触发热重读；未知 Skill 返回错误并列出可用 name。
4. `agent.activate_skill(name, prompt_body)`。
5. 只返回简短确认，不返回 SOP：
   `Skill '<name>' activated. SOP pinned to environment context.`

因为 `read_only=True`，Plan Mode 可见且权限引擎不会弹写操作确认。

### 5.2 InstallSkillTool

文件：

- `src/Arkcode/skills/install.py`
- `src/Arkcode/tool/install_skill.py`

`InstallSkillTool` 实现当前 Tool 协议，`name()` 返回 `InstallSkill`，
`read_only=False`，参数为 `{url: str}`。

安装核心接口：

```python
@dataclass(frozen=True, slots=True)
class SkillSource:
    owner: str
    repo: str
    ref: str
    path: str
    expected_name: str | None = None

def parse_skill_url(url: str) -> SkillSource: ...
async def install_skill(source: SkillSource, install_root: Path) -> str: ...
```

支持：

- `https://skills.sh/<owner>/<repo>/<skill>`：解析 owner/repo 与目标 skill 名。
- `https://github.com/<owner>/<repo>/tree/<ref>/<path>`：安装明确目录。
- `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>/SKILL.md`：安装单文件 Skill。

下载统一使用 GitHub Contents API；可读取已有 `GITHUB_TOKEN`，但不要求配置。限制：

- 单文件最大 1 MiB。
- 总大小最大 8 MiB。
- 最多 64 个文件。
- 递归深度最大 4。
- 只接受 API 返回的 file/directory 节点；拒绝 `..`、绝对路径和越出 staging 的路径。

先下载到用户 skills 目录内的兄弟临时目录，完成后验证唯一的 Skill 根目录包含
`SKILL.md` 且能被 parser 解析。目标目录已存在时返回错误，不覆盖。最后用同文件系统
`Path.rename` 原子落位；任意失败清理 staging。

成功后 Tool 调 `loader.reload()`，再调用 `on_installed` 回调重建 Slash 命令与 Agent
Catalog，无需重启。

## 6. Slash Command 集成

### 6.1 参数化分发

修改：

- `src/Arkcode/command/command.py`
- `src/Arkcode/command/dispatch.py`
- `src/Arkcode/command/registry.py`
- 现有 builtin handlers 与测试

Handler 统一为：

```python
Handler = Callable[[UI, str], Awaitable[None]]
```

Parser 统一为：

```python
def parse(input_text: str) -> tuple[str, str, bool]: ...
```

返回 `(name, args, is_slash)`；命令名小写，args 去除首尾空白但保留内部内容。
现有 12 条命令忽略 args，`/skill` 与动态 Skill 命令消费 args。空 `/` 仍为已识别但
未命中命令，普通消息仍返回 `is_slash=False`。

Registry 新增：

```python
def register(self, command: Command, *, replace: bool = False) -> None: ...
def clear(self) -> None: ...
```

默认仍冲突即抛错；Skill 注册使用 `replace=True`。替换时移除被替换 Command 的 name
及 aliases，保持 `_by_name` 与 `_visible` 一致。

### 6.2 动态命令注册

文件：`src/Arkcode/command/skills.py`

```python
def register_skill_management(registry: Registry, loader: SkillLoader) -> None: ...
def register_skill_commands(
    registry: Registry,
    loader: SkillLoader,
    executor: SkillExecutor,
) -> None: ...
```

TUI 提供 `_rebuild_command_registry()`：

1. 对现有 Registry 调 `clear()`，保持对象引用稳定。
2. 注册 12 条 builtins。
3. 注册 `/skill` 管理命令。
4. 按 name 字典序注册所有 Skill，描述追加 `[skill]`，并使用 `replace=True`。

因此 Skill 可以覆盖 `/review` 等内置命令；Skill 被删除并 reload 后，内置命令会恢复。

动态 Skill handler 每次执行先 `loader.get(name)`，确保热重载：

- inline：`executor.execute_inline(skill, args)`，再调用
  `ui.inject_and_send(f"/{name}", 原始触发文本)`。
- fork：创建受 TUI 跟踪的后台任务；执行完成后调用
  `ui.append_system_message(name, result)`，不启动主 Agent。

### 6.3 `/skill` 管理命令

参数语法：

- `/skill` 与 `/skill list`：按 name 排序输出 name、description、source。
- `/skill info <name>`：热重读并显示规范化 frontmatter、绝对路径、目录型标记。
- `/skill reload`：`loader.reload()`，重建命令 Registry，更新 Agent Catalog。
- 其它参数：输出用法，不触发 LLM。

UI Protocol 新增：

```python
def skill_list(self) -> list[tuple[str, str, str]]: ...
def skill_info(self, name: str) -> str | None: ...
def reload_skills(self) -> None: ...
def append_system_message(self, name: str, result: str) -> None: ...
def clear_active_skills(self) -> None: ...
```

NopUI 提供无副作用默认实现。

## 7. TUI 与启动组装

修改：

- `src/Arkcode/tui/app.py`
- `src/Arkcode/tui/commands.py`
- `src/Arkcode/cli.py`（只传递明确的 workspace；不承载 Skill 业务）

`ArkCodeApp.__init__`：

1. 用 workspace 创建 `SkillLoader` 并 `load_all()`。
2. 创建 `LoadSkillTool`、`InstallSkillTool` 并注册到 Tool Registry。
3. 注册 builtins 与 `/skill`；Provider 尚未选择时暂不注册动态 Skill handler。

`_activate_provider`：

1. 按现有流程创建 Provider 与 Agent。
2. 把 Loader 与 Agent 注入 `LoadSkillTool`。
3. 创建绑定当前 Agent/Provider/Conversation 的 `SkillExecutor`。
4. 构造 Catalog 文本并 `agent.set_skill_catalog(...)`。
5. 调 `_rebuild_command_registry()` 注册动态 Skill 命令。

reload/install 共用 `_reload_skills()`，原子执行：Loader reload → 重建 Registry → 更新
Agent Catalog。单条坏 Skill 只 warning，不阻断其余命令。

fork 后台任务由 App 集合持有，完成后自动移除；退出时取消并 await，避免悬空任务。
fork 结果通过 `append_system_message` 包装为 `<system-reminder>` 写入主 Conversation，
同时写入 RichLog。由于当前 Provider-neutral Message 只支持 user/assistant/tool，该包装作为
系统语义适配层，不新增供应商不兼容的历史 role。

`/clear` 路径在新会话创建成功后清除 Active Skills；若创建新会话失败，不清除旧状态。

## 8. 模块交互

### 8.1 启动与渐进式披露

```text
CLI -> ArkCodeApp
    -> SkillLoader.load_all
    -> register LoadSkill / InstallSkill
    -> select Provider
    -> Agent + SkillExecutor
    -> set_skill_catalog(name + description only)
    -> rebuild slash commands
```

### 8.2 自动激活

```text
Agent iteration N
  -> model calls LoadSkill({"name": "commit"})
  -> loader.get("commit") hot reloads SKILL.md
  -> agent.activate_skill("commit", body)
  -> short tool result
Agent iteration N+1
  -> environment rebuilt
  -> full commit SOP appears under Active Skills
```

### 8.3 显式 inline

```text
/commit arguments
  -> slash parse(name="commit", args="arguments")
  -> loader.get hot reload
  -> execute_inline activates rendered SOP
  -> ui.inject_and_send triggers main Agent
  -> every iteration sees Active Skills
```

### 8.4 显式 fork

```text
/review arguments
  -> loader.get hot reload
  -> background execute_fork
  -> isolated Conversation + Runtime + Agent
  -> final text
  -> <system-reminder> result appended to main conversation and TUI
```

### 8.5 安装与热注册

```text
InstallSkill({url})
  -> parse allowlisted URL
  -> GitHub Contents API recursive staging download
  -> limits + SKILL.md parse validation
  -> atomic rename
  -> loader.reload
  -> rebuild commands
  -> refresh Agent catalog
```

## 9. 文件组织

```text
src/Arkcode/
├── skills/
│   ├── __init__.py          # 导出 SkillMeta / SkillLoader / SkillExecutor
│   ├── parser.py            # frontmatter、SkillMeta、参数替换
│   ├── loader.py            # 两级扫描、优先级、缓存、热重载
│   ├── executor.py          # inline / fork
│   └── install.py           # URL 解析、Contents API 下载、原子安装
├── tool/
│   ├── load_skill.py        # LoadSkillTool（read-only）
│   ├── install_skill.py     # InstallSkillTool（write）
│   ├── registry.py          # fork 使用的 without 隔离视图
│   └── __init__.py          # 公共导出
├── command/
│   ├── command.py           # Handler 增加 args
│   ├── dispatch.py          # parse 返回 name + args
│   ├── registry.py          # replace / clear
│   ├── skills.py            # /skill + 动态 Skill commands
│   ├── ui.py                # Skill UI 能力
│   └── builtins.py          # 现有命令兼容新 Handler
├── agent/
│   └── agent.py             # Active Skills、Catalog、逐 iteration environment
├── prompt/
│   ├── builder.py           # Catalog / Active Skills 渲染入口
│   ├── modules.py           # Skills catalog 槽位
│   └── __init__.py
├── tui/
│   ├── app.py               # 生命周期、组装、后台 fork task
│   └── commands.py          # AppUI Skill 方法与分发
└── cli.py                   # workspace 传递

tests/
├── test_skills_parser.py
├── test_skills_loader.py
├── test_skills_executor.py
├── test_skills_install.py
├── test_skill_tools.py
├── test_command_skills.py
├── test_prompt_skills.py
├── test_agent.py
└── test_tui.py
```

## 10. 错误处理与安全

- 本地解析错误：warning + 跳过；热重载失败回退最后成功版本。
- 未知 Skill：返回可观察错误和可用列表，不激活、不触发 LLM。
- fork 异常：错误文本回流；取消信号不吞掉。
- 安装只允许 `skills.sh`、`github.com`、`raw.githubusercontent.com` 的 HTTPS URL。
- GitHub API 响应、base64、节点类型、路径、文件数、深度和大小全部在写入前校验。
- staging 与目标处于同一父目录，确保 rename 原子性；失败不留下半安装目录。
- 目标已存在时拒绝覆盖，避免不可恢复的数据损失。
- `LoadSkillTool.read_only=True`；`InstallSkillTool.read_only=False`，沿用现有权限审批。
- Skill SOP 属于外部内容，只进入 Catalog/Active Skills 边界，不获得额外权限。

## 11. 测试策略

### 单元测试

- Parser：frontmatter 边界、YAML、字段校验、两种布局、参数替换。
- Loader：两级扫描、项目覆盖、稳定排序、坏文件隔离、热重载与缓存回退。
- Executor：inline 激活、三种 fork context、model override、事件累计、错误与取消。
- Tools：JSON schema、未知/未初始化、read-only、安装回调。
- Installer：三种 URL、host 拒绝、四项限额、路径逃逸、staging 清理、atomic rename。
- Command：参数解析、覆盖/恢复、管理子命令、inline/fork 分支。
- Prompt/Agent：Catalog 不含正文、Active Skills 每 iteration 更新、clear 清理。

### 集成与回归

- 现有 12 条 Slash Command 行为与补全回归。
- `LoadSkill` 在一次 Agent run 的相邻 iteration 中生效。
- `/clear` 保留 Catalog、清除 Active Skills。
- 安装/reload 后 `/help` 与补全无需重启即时更新。
- fork 不修改主 Conversation，完成后只新增一条回流消息。
- 全量 pytest、ruff、format、mypy 与 compileall。

### 端到端

在真实 TUI 中创建 inline/fork/bad 三类测试 Skill，验证 `/help`、`/skill`、参数替换、
热重载、自动 LoadSkill、fork 回流、`/clear`、坏文件隔离和权限提示。远程安装使用本地
mock GitHub API 做确定性测试；真实网络安装作为可选人工验收，不作为离线 CI 硬依赖。

## 12. Spec 覆盖

| Spec | 设计归属 |
|------|----------|
| F1, F2, F3, F4, F5 | Parser + Loader |
| F6, F7 | SkillExecutor |
| F10, F11 | LoadSkillTool + Prompt/Agent |
| F12, F13, F14 | 参数化 Slash + 动态注册与覆盖 |
| F17, F18 | Loader.get 热重载 + `/clear` |
| F19 | Installer + InstallSkillTool + reload callback |
| F20 | SkillLoader.get_source_label |
| N1 | Loader 单条错误隔离 |
| N2 | LoadSkillTool.read_only |
| N3 | 独立 Conversation/Runtime/Agent |
| N5 | project-first / first-wins 扫描 |

## 13. 技术决策

| 决策 | 理由 |
|------|------|
| 不引入第二套 Catalog/ActiveSkills 类型 | 避免与已批准的 `SkillMeta/SkillLoader` 基准冲突 |
| 修改 Slash Handler 支持 args | `/skill info` 与 `$ARGUMENTS` 无法在零参数 dispatcher 上实现 |
| Registry 原地 clear + 重建 | reload 可恢复曾被 Skill 覆盖的内置命令，且不破坏补全持有的引用 |
| Active Skills 留在 Agent | 符合 Spec；`/clear` 显式清理，fork runtime 不会共享该字典 |
| 动态内容放 System.environment | 同一 run 的下一 iteration 即可看到 LoadSkill 结果，且不影响稳定缓存块 |
| fork 结果使用 system-reminder 适配 | 当前跨 Provider Message 不支持 system 历史角色，避免扩大协议变更面 |
| 安装使用 Contents API | 符合 Spec，无需本地 git，便于逐文件执行限额与路径检查 |
| 新增 `httpx` 依赖 | 安装器需要异步 HTTP；其余 Skill 核心逻辑不依赖网络 |
