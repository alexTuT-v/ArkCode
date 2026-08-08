# Skill 系统 Implementation Tasks

> **执行要求：** 按顺序使用 TDD 完成。每个任务先运行失败测试，再写最小实现；任务验证
> 全绿后才能进入下一项。实现阶段使用 `superpowers:executing-plans`，直接在当前分支工作。

**目标：** 在 ArkCode 中实现可加载、热更新、inline/fork 执行、Slash 显式调用、
LoadSkill 自动激活和安全远程安装的完整 Skill 系统。

**架构：** `SkillMeta -> SkillLoader -> SkillExecutor` 是核心链路；Agent 每轮重建
Skills environment；Tool、Command 与 TUI 只做协议适配和生命周期组装。

**技术栈：** Python 3.12+、PyYAML、httpx、Textual、pytest、pytest-asyncio、ruff、mypy。

## 全局约束

- 源码路径统一使用 `src/Arkcode/`，测试路径统一使用 `tests/`。
- 项目 `.Arkcode/skills/` 优先于用户 `~/.Arkcode/skills/`。
- `mode` 默认 `inline`；`context` 默认 `full`。
- 无 `$ARGUMENTS` 占位符时正文必须保持不变。
- LoadSkill 必须是 read-only；InstallSkill 必须是 write。
- fork 不得修改主 Conversation、主 SessionRuntime 或主 Agent Active Skills。
- 安装限额固定为：1 MiB/文件、8 MiB 总量、64 文件、递归深度 4。
- 不覆盖用户已有 Skill 目录，不使用本地 git，不下载任意 ZIP。

---

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/Arkcode/skills/__init__.py` | Skill 公共导出 |
| 新建 | `src/Arkcode/skills/parser.py` | `SkillMeta`、frontmatter、参数替换 |
| 新建 | `src/Arkcode/skills/loader.py` | 两级扫描、优先级、缓存、热重载 |
| 新建 | `src/Arkcode/skills/executor.py` | inline/fork 执行 |
| 新建 | `src/Arkcode/skills/install.py` | URL 解析、Contents API 下载、原子安装 |
| 新建 | `src/Arkcode/tool/load_skill.py` | read-only LoadSkill 工具 |
| 新建 | `src/Arkcode/tool/install_skill.py` | write InstallSkill 工具 |
| 新建 | `src/Arkcode/command/skills.py` | `/skill` 与动态 Skill 命令 |
| 修改 | `src/Arkcode/agent/agent.py` | Active Skills、Catalog、逐轮 environment |
| 修改 | `src/Arkcode/tool/registry.py` | `without()` 隔离视图 |
| 修改 | `src/Arkcode/tool/__init__.py` | 新工具导出 |
| 修改 | `src/Arkcode/command/command.py` | Handler 接收 args |
| 修改 | `src/Arkcode/command/dispatch.py` | 返回 name/args/is_slash |
| 修改 | `src/Arkcode/command/registry.py` | replace、clear |
| 修改 | `src/Arkcode/command/ui.py` | Skill 管理与回流能力 |
| 修改 | `src/Arkcode/command/builtin_*.py` | 兼容参数化 Handler |
| 修改 | `src/Arkcode/command/builtins.py` | 注册 `/skill` 管理命令 |
| 修改 | `src/Arkcode/prompt/builder.py` | Skills 渲染函数 |
| 修改 | `src/Arkcode/prompt/modules.py` | Catalog 扩展槽位 |
| 修改 | `src/Arkcode/prompt/__init__.py` | 新渲染函数导出 |
| 修改 | `src/Arkcode/tui/app.py` | Loader/Tool/Executor 生命周期与后台任务 |
| 修改 | `src/Arkcode/tui/commands.py` | AppUI Skill 能力、clear 钩子 |
| 修改 | `src/Arkcode/cli.py` | 显式传入 workspace |
| 修改 | `pyproject.toml` | 新增 httpx 依赖 |
| 新建 | `tests/test_skills_parser.py` | Parser 单测 |
| 新建 | `tests/test_skills_loader.py` | Loader 单测 |
| 新建 | `tests/test_skills_executor.py` | inline/fork 单测 |
| 新建 | `tests/test_skills_install.py` | 安装器单测 |
| 新建 | `tests/test_skill_tools.py` | LoadSkill/InstallSkill 单测 |
| 新建 | `tests/test_command_skills.py` | 参数化 Slash 与 Skill 命令单测 |
| 新建 | `tests/test_prompt_skills.py` | Catalog/Active Skills 单测 |
| 修改 | `tests/test_agent.py` | 逐 iteration 激活集成测试 |
| 修改 | `tests/test_tui.py` | 启动、reload、clear、fork 回流测试 |

---

## T1：SkillMeta 与 frontmatter 解析

**文件：**

- 新建 `src/Arkcode/skills/parser.py`
- 新建 `src/Arkcode/skills/__init__.py`
- 新建 `tests/test_skills_parser.py`

**依赖：** 无

**产出接口：**

```python
class SkillParseError(ValueError): ...

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

def parse_frontmatter(raw: str) -> tuple[dict[str, object], str]: ...
def parse_skill_file(path: Path, *, is_directory: bool = False) -> SkillMeta: ...
def substitute_arguments(prompt_body: str, args: str) -> str: ...
```

- [x] **T1.1 写失败测试**：覆盖合法 frontmatter、缺开头、缺结束、非法 YAML、非
  mapping、缺 name/description、非法 name/mode/context/model、默认值、目录标记、文件
  不存在和 `$ARGUMENTS` 多次替换/无占位符原样返回。

```python
def test_parse_skill_defaults(tmp_path: Path) -> None:
    path = tmp_path / "commit.md"
    path.write_text("---\nname: commit\ndescription: Commit code\n---\nDo it")
    skill = parse_skill_file(path)
    assert (skill.mode, skill.context, skill.prompt_body) == ("inline", "full", "Do it")

def test_substitute_without_placeholder_is_unchanged() -> None:
    assert substitute_arguments("Do it", "extra") == "Do it"
```

- [x] **T1.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skills_parser.py
```

预期：因 `Arkcode.skills.parser` 不存在而失败。

- [x] **T1.3 实现最小 Parser**：使用 `yaml.safe_load`，按 Plan 的字段、默认值和正则
  校验；`source_path` 保存绝对路径。

- [x] **T1.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skills_parser.py
.venv/bin/ruff check src/Arkcode/skills tests/test_skills_parser.py
```

预期：全部通过。

---

## T2：SkillLoader 两级扫描与热重载

**文件：**

- 新建 `src/Arkcode/skills/loader.py`
- 修改 `src/Arkcode/skills/__init__.py`
- 新建 `tests/test_skills_loader.py`

**依赖：** T1

**产出接口：**

```python
class SkillLoader:
    def __init__(self, work_dir: str | Path) -> None: ...
    def load_all(self) -> list[SkillMeta]: ...
    def reload(self) -> list[SkillMeta]: ...
    def get(self, name: str) -> SkillMeta | None: ...
    def get_catalog(self) -> list[tuple[str, str]]: ...
    def get_source_label(self, name: str) -> Literal["project", "user"] | None: ...
```

- [x] **T2.1 写失败测试**：使用 `monkeypatch(Path, "home", ...)` 隔离用户目录，覆盖
  单文件、目录型、排序、项目覆盖用户、坏文件跳过、unknown、source label、reload
  新增/删除、get 热更新成功和失败回退缓存。

```python
def test_project_skill_overrides_user_skill(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    loader = SkillLoader(tmp_path / "project")
    # 测试 helper 分别写入 project/user 同名 Skill。
    loader.load_all()
    assert loader.get("review").description == "project"
    assert loader.get_source_label("review") == "project"
```

- [x] **T2.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skills_loader.py
```

- [x] **T2.3 实现 Loader**：project-first、first-wins；扫描结果字典序稳定；单条错误
  `logging.warning`；`get` 重读失败回退 `_cache`。

- [x] **T2.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skills_parser.py tests/test_skills_loader.py
.venv/bin/ruff check src/Arkcode/skills tests/test_skills_loader.py
```

---

## T3：Slash 参数与 Registry 覆盖能力

**文件：**

- 修改 `src/Arkcode/command/command.py`
- 修改 `src/Arkcode/command/dispatch.py`
- 修改 `src/Arkcode/command/registry.py`
- 修改 `src/Arkcode/command/builtin_local.py`
- 修改 `src/Arkcode/command/builtin_ui.py`
- 修改 `src/Arkcode/command/builtin_prompt.py`
- 修改 `src/Arkcode/tui/commands.py`
- 修改 `tests/test_command_dispatch.py`
- 修改 `tests/test_command_registry.py`
- 修改 `tests/test_command_builtins.py`
- 修改 `tests/test_tui.py`

**依赖：** 无

**接口变更：**

```python
Handler = Callable[[UI, str], Awaitable[None]]
def parse(input_text: str) -> tuple[str, str, bool]: ...
def Registry.register(command: Command, *, replace: bool = False) -> None: ...
def Registry.clear() -> None: ...
```

- [x] **T3.1 写失败测试**：`/skill info review` 返回
  `("skill", "info review", True)`；普通文本、空 `/`、大小写与内部空白符合 Plan；
  `replace=True` 同步清理旧 name/aliases/visible；`clear()` 清空全部索引。

```python
def test_parse_command_arguments() -> None:
    assert parse(" /SKILL   info review ") == ("skill", "info review", True)

def test_register_replace_removes_old_aliases() -> None:
    registry.register(old)
    registry.register(new, replace=True)
    assert registry.lookup(old.aliases[0]) is None
    assert registry.lookup(new.name) is new
```

- [x] **T3.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_command_dispatch.py tests/test_command_registry.py
```

- [x] **T3.3 修改 Handler 与所有调用方**：现有 builtin handler 增加未使用的 `args`
  参数；dispatch 把 args 传给 handler；保持 12 条既有命令行为不变。

- [x] **T3.4 验证 Slash 全回归**。

```bash
.venv/bin/pytest -q tests/test_command_dispatch.py tests/test_command_registry.py \
  tests/test_command_builtins.py tests/test_command_complete.py tests/test_tui.py
```

---

## T4：Skills Prompt 与 Agent 逐轮注入

**文件：**

- 修改 `src/Arkcode/prompt/builder.py`
- 修改 `src/Arkcode/prompt/modules.py`
- 修改 `src/Arkcode/prompt/__init__.py`
- 修改 `src/Arkcode/agent/agent.py`
- 新建 `tests/test_prompt_skills.py`
- 修改 `tests/test_agent.py`

**依赖：** T1

**产出接口：**

```python
def render_skill_catalog(items: list[tuple[str, str]]) -> str: ...
def render_active_skills(active: Mapping[str, str]) -> str: ...
def Agent.activate_skill(name: str, prompt_body: str) -> None: ...
def Agent.clear_active_skills() -> None: ...
def Agent.set_skill_catalog(catalog: str) -> None: ...
```

- [x] **T4.1 写失败测试**：Catalog 只含 name/description，不含 SOP；Active Skills
  按激活顺序输出且空集合不输出标题；重复激活覆盖正文；clear 清空；模拟一次 Agent run
  中 iteration 1 调 LoadSkill 后，iteration 2 的 `Request.system.environment` 出现新 SOP。

```python
def test_active_skills_render_full_sop() -> None:
    text = render_active_skills({"review": "Check bugs"})
    assert "## Active Skills" in text
    assert "### Skill: review" in text
    assert "Check bugs" in text
```

- [x] **T4.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_prompt_skills.py tests/test_agent.py -k skill
```

- [x] **T4.3 实现动态 environment**：基础环境可在 run 开头采集，但 Catalog 与 Active
  Skills 必须在每个 iteration 重新拼装；稳定 system 不含动态 Skill 正文。

- [x] **T4.4 验证 Prompt 与 Agent 回归**。

```bash
.venv/bin/pytest -q tests/test_prompt.py tests/test_prompt_skills.py tests/test_agent.py
```

---

## T5：LoadSkillTool 与 Tool Registry 隔离视图

**文件：**

- 新建 `src/Arkcode/tool/load_skill.py`
- 修改 `src/Arkcode/tool/registry.py`
- 修改 `src/Arkcode/tool/__init__.py`
- 新建 `tests/test_skill_tools.py`
- 修改 `tests/test_tool.py`

**依赖：** T2、T4

**产出接口：**

```python
class LoadSkillTool(Tool): ...
def Registry.without(names: Collection[str]) -> Registry: ...
```

- [x] **T5.1 写失败测试**：工具名、schema、`read_only=True`、未初始化、非法 JSON、
  unknown、成功激活、确认消息不含 SOP；`without({"LoadSkill"})` 保持顺序且不修改源
  Registry。

```python
@pytest.mark.asyncio
async def test_load_skill_activates_without_returning_body() -> None:
    result = await tool.execute('{"name":"review"}')
    agent.activate_skill.assert_called_once_with("review", "secret SOP")
    assert "secret SOP" not in result.content
```

- [x] **T5.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skill_tools.py tests/test_tool.py -k 'skill or without'
```

- [x] **T5.3 实现工具与隔离视图**：严格复用当前 `Tool.execute(args: str) -> Result`
  协议，不引入 `category/params_model` 第二套接口。

- [x] **T5.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skill_tools.py tests/test_tool.py
```

---

## T6：SkillExecutor inline 路径

**文件：**

- 新建 `src/Arkcode/skills/executor.py`
- 修改 `src/Arkcode/skills/__init__.py`
- 新建 `tests/test_skills_executor.py`

**依赖：** T1、T4、T5

**产出接口：**

```python
SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})
def SkillExecutor.execute_inline(skill: SkillMeta, args: str) -> None: ...
```

- [x] **T6.1 写失败测试**：有/无 `$ARGUMENTS`、多占位符；只调用
  `agent.activate_skill`，不调用 Provider，不修改 Conversation。

```python
def test_execute_inline_only_activates() -> None:
    executor.execute_inline(skill_with_arguments, "src")
    agent.activate_skill.assert_called_once_with("review", "Review src")
    assert conversation.messages() == []
```

- [x] **T6.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skills_executor.py -k inline
```

- [x] **T6.3 实现 inline 最小路径**。

- [x] **T6.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skills_executor.py -k inline
```

---

## T7：SkillExecutor fork 路径

**文件：**

- 修改 `src/Arkcode/skills/executor.py`
- 修改 `tests/test_skills_executor.py`

**依赖：** T5、T6

**产出接口：**

```python
async def SkillExecutor.execute_fork(skill: SkillMeta, args: str) -> str: ...
```

- [x] **T7.1 写失败测试**：none 空历史；recent 只取最近 5 条 user/assistant；full
  先摘要；fork Conversation 与 Runtime 不同于主对象；model override 使用替换后的配置；
  registry 排除 LoadSkill；累计 text 到 done；普通异常转错误文本；CancelledError 上抛。

```python
@pytest.mark.asyncio
async def test_fork_none_does_not_modify_main_conversation() -> None:
    before = main_conversation.messages()
    result = await executor.execute_fork(fork_skill(context="none"), "target")
    assert result == "fork result"
    assert main_conversation.messages() == before
```

- [x] **T7.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skills_executor.py -k fork
```

- [x] **T7.3 实现 fork**：使用当前 `Conversation`、`SessionRuntime`、`Agent.run` 和
  `AgentEvent`，不引入第二套会话或事件抽象。

- [x] **T7.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skills_executor.py
```

---

## T8：`/skill` 与动态 Skill 命令

**文件：**

- 新建 `src/Arkcode/command/skills.py`
- 修改 `src/Arkcode/command/__init__.py`
- 修改 `src/Arkcode/command/ui.py`
- 新建 `tests/test_command_skills.py`

**依赖：** T2、T3、T6、T7

**产出接口：**

```python
def register_skill_management(registry: Registry, loader: SkillLoader) -> None: ...
def register_skill_commands(
    registry: Registry,
    loader: SkillLoader,
    executor: SkillExecutor,
) -> None: ...
```

- [x] **T8.1 写失败测试**：`/skill`、list、info、reload、非法参数；source/path/
  directory 可观察；动态描述含 `[skill]`；inline 激活后触发主 Agent；fork 创建后台任务
  并回流；Skill 覆盖内置 `/review`。

```python
@pytest.mark.asyncio
async def test_inline_skill_command_uses_hot_reloaded_body() -> None:
    command = registry.lookup("commit")
    await command.handler(ui, "src")
    executor.execute_inline.assert_called_once()
    ui.inject_and_send.assert_called_once_with("/commit", "/commit src")
```

- [x] **T8.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_command_skills.py
```

- [x] **T8.3 扩展 UI/NopUI 并实现命令**：管理命令不触发 LLM；动态 handler 每次先
  `loader.get`；fork task 内部捕获普通异常并回流。

- [x] **T8.4 验证命令回归**。

```bash
.venv/bin/pytest -q tests/test_command_skills.py tests/test_command_builtins.py \
  tests/test_command_complete.py
```

---

## T9：TUI 生命周期、Catalog、clear 与 fork 回流

**文件：**

- 修改 `src/Arkcode/tui/app.py`
- 修改 `src/Arkcode/tui/commands.py`
- 修改 `src/Arkcode/cli.py`
- 修改 `tests/test_tui.py`

**依赖：** T2、T4-T8

**产出行为：** App 启动加载 Catalog；Provider 激活后组装 Agent/Executor；reload
原子重建命令与 Catalog；clear 清 Active Skills；退出取消 fork tasks。

- [x] **T9.1 写失败测试**：App 构造并注册 LoadSkillTool；Catalog 只注入 name/desc；
  `/help` 和补全出现 Skill；reload 新增/删除即时更新；inline 发送触发；fork 结果仅新增
  一条 `<system-reminder>` 回流消息；clear 成功后清 active，失败时保留；unmount 取消任务。

```python
@pytest.mark.asyncio
async def test_clear_removes_active_skills_after_new_session(monkeypatch) -> None:
    app.agent.activate_skill("review", "SOP")
    await app.submit("/clear")
    assert app.agent.active_skills == {}
    assert app.skill_loader.get_catalog()
```

- [x] **T9.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_tui.py -k skill
```

- [x] **T9.3 实现生命周期**：Loader 在 App 初始化；LoadSkillTool 在 Agent 前注册；
  Provider 激活后注入 Agent 和 Executor；Registry 原地重建。InstallSkillTool 留到 T11
  接入。

- [x] **T9.4 验证 TUI 与既有 Slash 回归**。

```bash
.venv/bin/pytest -q tests/test_tui.py tests/test_command_skills.py
```

---

## T10：远程安装解析与安全下载

**文件：**

- 新建 `src/Arkcode/skills/install.py`
- 修改 `src/Arkcode/skills/__init__.py`
- 修改 `pyproject.toml`
- 新建 `tests/test_skills_install.py`

**依赖：** T1

**产出接口：**

```python
MAX_FILE_SIZE = 1024 * 1024
MAX_TOTAL_SIZE = 8 * 1024 * 1024
MAX_FILE_COUNT = 64
MAX_RECURSION_DEPTH = 4

@dataclass(frozen=True, slots=True)
class SkillSource: ...
def parse_skill_url(url: str) -> SkillSource: ...
async def install_skill(source: SkillSource, install_root: Path) -> str: ...
```

- [x] **T10.1 写失败测试**：三种 URL；HTTP/未知 host/缺路径拒绝；mock
  `httpx.MockTransport` 覆盖目录递归、raw 单文件、base64 错误、API 错误、四项限额、
  路径逃逸、缺 SKILL.md、parse 失败、目标存在、成功 rename 和失败 staging 清理。

```python
def test_parse_github_tree_url() -> None:
    source = parse_skill_url(
        "https://github.com/acme/skills/tree/main/review"
    )
    assert (source.owner, source.repo, source.ref, source.path) == (
        "acme", "skills", "main", "review"
    )
```

- [x] **T10.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skills_install.py
```

- [x] **T10.3 添加 `httpx>=0.27` 并实现安装器**：网络只访问 GitHub API；写入前
  校验每个节点；staging 与目标同父目录；目标已存在不覆盖。

- [x] **T10.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skills_install.py
.venv/bin/ruff check src/Arkcode/skills/install.py tests/test_skills_install.py
```

---

## T11：InstallSkillTool 与安装后热注册

**文件：**

- 新建 `src/Arkcode/tool/install_skill.py`
- 修改 `src/Arkcode/tool/__init__.py`
- 修改 `src/Arkcode/tui/app.py`
- 修改 `tests/test_skill_tools.py`
- 修改 `tests/test_tui.py`

**依赖：** T9、T10

**产出接口：**

```python
class InstallSkillTool(Tool):
    read_only = False
```

- [x] **T11.1 写失败测试**：name/schema/write 分类、非法 JSON/URL、安装失败；成功时
  `loader.reload()` 与 `on_installed()` 各一次；TUI 回调更新 `/help`、补全和 Agent Catalog。

```python
@pytest.mark.asyncio
async def test_install_success_reloads_and_notifies() -> None:
    result = await tool.execute('{"url":"https://skills.sh/acme/repo/review"}')
    loader.reload.assert_called_once_with()
    on_installed.assert_called_once_with()
    assert result.is_error is False
```

- [x] **T11.2 运行失败测试**。

```bash
.venv/bin/pytest -q tests/test_skill_tools.py tests/test_tui.py -k install_skill
```

- [x] **T11.3 实现 Tool 与 callback**：不得把网络或写盘标记为 read-only；callback
  失败返回可观察错误，不报告假成功。

- [x] **T11.4 验证**。

```bash
.venv/bin/pytest -q tests/test_skill_tools.py tests/test_tui.py -k skill
```

---

## T12：公共导出、类型检查与全量回归

**文件：**

- 修改 `src/Arkcode/skills/__init__.py`
- 修改 `src/Arkcode/tool/__init__.py`
- 修改 `src/Arkcode/command/__init__.py`
- 修改 `tests/test_package_facades.py`

**依赖：** T1-T11

- [x] **T12.1 写公共导入测试**：从三个 package facade 导入新公开类型；确认唯一公开
  的 Skill 元数据类型名是 `SkillMeta`。

```python
def test_skill_public_facade() -> None:
    from Arkcode.skills import SkillExecutor, SkillLoader, SkillMeta
    assert SkillMeta.__name__ == "SkillMeta"
```

- [x] **T12.2 运行相关完整测试**。

```bash
.venv/bin/pytest -q tests/test_skills_parser.py tests/test_skills_loader.py \
  tests/test_skills_executor.py tests/test_skills_install.py \
  tests/test_skill_tools.py tests/test_command_skills.py \
  tests/test_prompt_skills.py tests/test_agent.py tests/test_tui.py
```

- [x] **T12.3 修复本功能引入的回归，不改动无关行为**。

- [x] **T12.4 执行质量门禁**。

```bash
.venv/bin/python -m compileall -q src/Arkcode
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
.venv/bin/pytest -q
git diff --check
```

预期：Skill 相关测试、compileall、ruff、format、mypy 全绿；若全量 pytest 存在任务前
已确认的无关基线失败，必须记录原始失败与对比证据，不得标记“全部通过”。

---

## T13：真实 TUI 端到端验收与文档收口

**文件：**

- 修改 `checklist.md`
- 如项目采用课程文档目录，同步 `docs/skills/`；否则以根目录四份文档为唯一权威来源

**依赖：** T1-T12

- [ ] **T13.1 创建隔离测试 workspace**：写入 inline、fork、bad 三个 Skill；不得污染
  仓库已有 `.Arkcode/skills` 或用户目录。

```bash
workspace="$(mktemp -d /tmp/arkcode-skills-e2e.XXXXXX)"
```

- [ ] **T13.2 在 tmux 启动真实 ArkCode**：使用合法测试配置，捕获启动页、`/help`、
  `/skill list/info`、补全菜单证据。

- [ ] **T13.3 验证 inline**：`/test-skill first` 后观察 Agent 请求 environment 含替换后的
  SOP；编辑文件后不重启，再执行并看到新正文。

- [ ] **T13.4 验证 LoadSkill**：自然语言触发工具，确认无权限弹窗，下一 iteration 出现
  Active Skills，tool result 不包含完整 SOP。

- [ ] **T13.5 验证 fork**：确认独立执行、主历史不含子过程，只新增最终
  `<system-reminder>` 回流结果。

- [ ] **T13.6 验证 clear/reload/bad file**：clear 后 Active Skills 消失但 Catalog 保留；
  reload 更新命令；坏 Skill 只 warning。

- [ ] **T13.7 验证安装权限和离线 mock 安装**：InstallSkill 出现写操作审批；安装成功后
  `/help` 与补全即时出现新 Skill。

- [x] **T13.8 按 checklist 逐项写证据并勾选**：tmux 不可用或无真实 Provider 凭据时，
  对应项保持未勾选并明确说明阻塞，不得用推断代替实际结果。

---

## 执行顺序

```text
T1 -> T2 ---------------------> T8 -> T9 -----> T11 -> T12 -> T13
 |                              ^     ^          ^
 +-> T4 -> T5 -> T6 -> T7 -----+-----+          |
                                              T10

T3 --------------------------------> T8
```

T3 与 T1-T2 可独立推进；T10 可在 T9 之前完成，但 T11 必须等待 T9 与 T10。

## 提交检查点

每个任务验证通过后，只暂存该任务文件并提交；不得顺带提交用户已有的无关改动：

```text
T1  feat(skills): add skill metadata parser
T2  feat(skills): add layered skill loader
T3  feat(commands): support parameterized slash commands
T4  feat(agent): inject active skills into environment
T5  feat(tools): add load skill tool
T6  feat(skills): add inline skill execution
T7  feat(skills): add isolated fork execution
T8  feat(commands): register skill slash commands
T9  feat(tui): integrate skill lifecycle
T10 feat(skills): add secure remote installer
T11 feat(tools): integrate install skill tool
T12 test(skills): close skill system regression suite
T13 docs(skills): record end-to-end acceptance
```

## 进度

- [x] T1：SkillMeta 与 Parser
- [x] T2：SkillLoader
- [x] T3：Slash 参数与 Registry 覆盖
- [x] T4：Prompt 与 Agent 注入
- [x] T5：LoadSkillTool 与 Registry 隔离
- [x] T6：inline Executor
- [x] T7：fork Executor
- [x] T8：Skill Commands
- [x] T9：TUI 生命周期与回流
- [x] T10：安全远程安装
- [x] T11：InstallSkillTool 与热注册
- [x] T12：全量质量门禁（384 passed；1 个已记录的无关 MCP 文档基线失败）
- [ ] T13：端到端验收
