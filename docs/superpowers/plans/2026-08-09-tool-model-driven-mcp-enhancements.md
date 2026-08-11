# 工具层模型驱动与 MCP 增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ArkCode 工具层与配置层改为 pydantic 模型驱动，并补齐 MCP 增强（富内容结果、instructions 注入、懒重连/按需连接、工具懒加载与 ToolSearch）。

**Architecture:** 四个 phase 按依赖顺序实施：Phase 1 工具层模型驱动（`Tool.params_model` + `execute(params)` + registry 统一 `model_validate`）；Phase 2 配置层模型驱动（config / mcp config / permissions settings，错误消息与宽容行为逐字保留）；Phase 3 MCP 增强（富内容、instructions 注入、懒重连）；Phase 4 工具懒加载（`should_defer` + ToolSearch）。Agent 与 ToolExecutor 全程零改动。

**Tech Stack:** Python 3.12+、pydantic>=2、asyncio、pytest、pytest-asyncio、Ruff、strict mypy。

## Global Constraints

- 按用户要求**不自动 git commit**：每任务验证全绿即可，提交由用户手动执行。
- 不改变 6 个内置工具的名称、注册顺序与只读分类；`tests/integration/test_behavior_contracts.py` 必须保持通过。
- 不改变 `.env` 字段名、provider 选择行为与 `ConfigError` 错误消息；`tests/config/`、`tests/application/test_cli.py` 的现有断言不改。
- 不改变权限 yaml 语义与"忽略非字符串项"的宽容行为；`tests/permissions/` 现有断言不改。
- 不改变会话 JSONL 磁盘格式（第四档不碰）。
- 不改变 `McpTool` 的 `call_timeout=30`、工具命名 `mcp__server__tool` 与 read-only hint 分类。
- 新增依赖 `pydantic>=2`（`pyproject.toml`）。
- 工具参数错误消息可变化（无测试冻结）；现有测试断言的"缺少必填参数"类消息若存在则同步更新。
- Phase 1 中途（Task 1 完成后）未迁移工具在 registry 执行时会缺 `params_model`——每任务跑**定向测试**，Phase 1 结束时全量 `pytest -q` 全绿。
- 每个 Phase 末：`pytest -q`、`ruff check .`、`ruff format --check .`、`mypy src/Arkcode` 全绿。
- 遵循现有代码风格：Ruff line-length 88、`from __future__ import annotations`、类型注解完整。

---

### Task 1: 工具契约与 registry 收口 + read_file 迁移

**Files:**
- Modify: `src/Arkcode/tools/base.py`
- Modify: `src/Arkcode/tools/registry.py`
- Modify: `src/Arkcode/tools/builtins/read_file.py`
- Test: `tests/tools/test_model_driven.py`（新建）

**Interfaces:**
- Consumes: 现有 `Tool` ABC 与 `Registry.execute(name, args, timeout)`。
- Produces: `Tool.params_model: type[BaseModel]`、`Tool.get_schema()`、
  `Tool.execute(params: BaseModel) -> Result`（签名变化）、
  `Registry.execute` 统一 `model_validate_json` 与 `ValidationError` 分类。
  Task 2–6 依赖该契约逐个迁移其余工具。

- [ ] **Step 1: 写失败测试**

新建 `tests/tools/test_model_driven.py`：

```python
import pytest

from Arkcode.tools import new_default_registry


def test_read_file_schema_comes_from_model() -> None:
    registry = new_default_registry()
    schema = registry.get("read_file").get_schema()
    assert schema["name"] == "read_file"
    assert schema["input_schema"]["properties"]["path"]["description"] == "要读取的文件路径"
    assert schema["input_schema"]["required"] == ["path"]


@pytest.mark.asyncio
async def test_registry_validation_error_is_classified(tmp_path) -> None:
    registry = new_default_registry()
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")

    result = await registry.execute(
        "read_file",
        '{"path": 123}',
    )

    assert result.is_error is True
    assert "参数校验失败" in result.content
    # 类型错误不执行工具
    result2 = await registry.execute("read_file", '{"path": 123}')
    assert result2.is_error is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py -q`
Expected: FAIL（`Tool` 无 `get_schema`、`read_file` 无 `params_model`、registry 无校验分类）

- [ ] **Step 3: 改造 base.py**

`src/Arkcode/tools/base.py`：

```python
from pydantic import BaseModel


class Tool(ABC):
    """所有模型可调用工具的统一抽象基类。"""

    params_model: type[BaseModel]
    should_defer: bool = False

    @property
    @abstractmethod
    def read_only(self) -> bool: ...

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def description(self) -> str: ...

    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name(),
            "description": self.description(),
            "input_schema": schema,
        }

    @abstractmethod
    async def execute(self, params: BaseModel) -> Result:
        """执行已解析的参数模型并返回结果。"""
```

删除 `parameters()` 抽象方法。

- [ ] **Step 4: 改造 registry.py**

`src/Arkcode/tools/registry.py` 顶部加 `from pydantic import ValidationError`；
`execute` 改为：

```python
    async def execute(
        self,
        name: str,
        args: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Result:
        tool = self.get(name)
        if tool is None:
            return Result(content=f"未知工具: {name}", is_error=True)
        try:
            params = tool.params_model.model_validate_json(args)
        except ValidationError as exc:
            return Result(content=f"参数校验失败: {exc}", is_error=True)
        try:
            return await asyncio.wait_for(tool.execute(params), timeout=timeout)
        except TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return Result(content=f"工具 {name} 异常: {exc}", is_error=True)
```

`definitions()` 与 `read_only_definitions()` 的 `input_schema` 改为
`self._tools[name].get_schema()["input_schema"]`。

- [ ] **Step 5: 迁移 read_file**

`src/Arkcode/tools/builtins/read_file.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    path: str = Field(description="要读取的文件路径")


class ReadFileTool(Tool):
    """读取文件并返回带行号的内容。"""

    read_only = True
    params_model = Params
```

`execute` 签名改为 `async def execute(self, params: Params) -> Result:`，删除
`json.loads` 与 `data.get("path")` 解析，直接用 `params.path`；保留其余读取逻辑
与 `Result` 返回。删除不再使用的 `json` import（若文件内无其他使用）。

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py tests/tools/test_tool.py -q`
Expected: 新增测试 PASS；`test_tool.py` 中 read_file 相关用例 PASS（经 registry 传入 JSON 字符串，不感知签名变化）

- [ ] **Step 7: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/tools tests/tools && .venv/bin/mypy src/Arkcode`
Expected: 无输出（未迁移工具暂缺 `params_model` 是类属性声明，mypy 不强制子类实现）

---

### Task 2: glob / grep 迁移

**Files:**
- Modify: `src/Arkcode/tools/builtins/glob.py`
- Modify: `src/Arkcode/tools/builtins/grep.py`
- Test: `tests/tools/test_model_driven.py`（追加）

**Interfaces:**
- Consumes: `Tool.params_model` / `execute(params)`（Task 1）。
- Produces: glob / grep 的 `Params` 模型与模型化 execute。

- [ ] **Step 1: 写失败测试**

`tests/tools/test_model_driven.py` 追加：

```python
@pytest.mark.asyncio
async def test_glob_and_grep_validate_parameters(tmp_path) -> None:
    registry = new_default_registry()
    (tmp_path / "a.py").write_text("import os", encoding="utf-8")

    assert await registry.execute("glob", '{"pattern": "*.py", "path": 5}') is not None
    missing = await registry.execute("grep", '{"pattern": 1}')
    assert missing.is_error is True
    assert "参数校验失败" in missing.content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py -q`
Expected: FAIL（glob/grep 无 `params_model`）

- [ ] **Step 3: 迁移 glob**

`src/Arkcode/tools/builtins/glob.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    pattern: str = Field(description="glob 模式")
    path: str | None = Field(default=None, description="搜索根目录，默认当前目录")
```

`GlobTool.params_model = Params`；`execute(params: Params)` 用 `params.pattern` /
`params.path`，删除 `json.loads` 与手写校验。

- [ ] **Step 4: 迁移 grep**

`src/Arkcode/tools/builtins/grep.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    pattern: str = Field(description="Python 正则表达式")
    path: str | None = Field(default=None, description="搜索根目录或文件")
    glob: str | None = Field(default=None, description="可选文件名 glob")
```

`GrepTool.params_model = Params`；`execute(params: Params)` 用 `params.pattern` /
`params.path` / `params.glob`，删除 `json.loads` 与手写校验。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py tests/tools/test_tool.py -q`
Expected: PASS

- [ ] **Step 6: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/tools tests/tools && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 3: write_file / edit_file 迁移

**Files:**
- Modify: `src/Arkcode/tools/builtins/write_file.py`
- Modify: `src/Arkcode/tools/builtins/edit_file.py`
- Test: `tests/tools/test_model_driven.py`（追加）

**Interfaces:**
- Consumes: `Tool.params_model` / `execute(params)`（Task 1）。
- Produces: write_file / edit_file 的 `Params` 模型与模型化 execute。

- [ ] **Step 1: 写失败测试**

`tests/tools/test_model_driven.py` 追加：

```python
@pytest.mark.asyncio
async def test_write_and_edit_require_fields(tmp_path) -> None:
    registry = new_default_registry()
    target = tmp_path / "out.txt"

    missing_content = await registry.execute(
        "write_file",
        '{"path": "%s"}' % target,
    )
    assert missing_content.is_error is True
    assert "参数校验失败" in missing_content.content

    missing_old = await registry.execute(
        "edit_file",
        '{"path": "%s", "old_string": "x"}' % target,
    )
    assert missing_old.is_error is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py -q`
Expected: FAIL（write/edit 无 `params_model`）

- [ ] **Step 3: 迁移 write_file**

`src/Arkcode/tools/builtins/write_file.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    path: str = Field(description="目标文件路径")
    content: str = Field(description="要写入的完整内容")
```

`WriteFileTool.params_model = Params`；`execute(params: Params)` 用
`params.path` / `params.content`，删除 `json.loads` 与手写校验。

- [ ] **Step 4: 迁移 edit_file**

`src/Arkcode/tools/builtins/edit_file.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    path: str = Field(description="要编辑的文件路径")
    old_string: str = Field(description="必须在文件中唯一出现的原文")
    new_string: str = Field(description="替换后的文本")
```

`EditFileTool.params_model = Params`；`execute(params: Params)` 用三个字段，
删除 `json.loads` 与手写校验；保留文件替换逻辑。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py tests/tools/test_tool.py -q`
Expected: PASS

- [ ] **Step 6: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/tools tests/tools && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 4: bash 迁移

**Files:**
- Modify: `src/Arkcode/tools/builtins/bash.py`
- Modify: `tests/tools/test_bash_sandbox.py`
- Test: `tests/tools/test_model_driven.py`（追加）

**Interfaces:**
- Consumes: `Tool.params_model` / `execute(params)`（Task 1）、`BashTool` 沙箱注入（已有）。
- Produces: bash 的 `Params` 模型；退出码/超时/进程树逻辑保持。

- [ ] **Step 1: 写失败测试**

`tests/tools/test_model_driven.py` 追加：

```python
@pytest.mark.asyncio
async def test_bash_requires_command() -> None:
    registry = new_default_registry()

    result = await registry.execute("bash", "{}")

    assert result.is_error is True
    assert "参数校验失败" in result.content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_model_driven.py -q`
Expected: FAIL（bash 无 `params_model`）

- [ ] **Step 3: 迁移 bash**

`src/Arkcode/tools/builtins/bash.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
```

`BashTool.params_model = Params`；`execute(params: Params)` 用 `params.command`，
删除 `json.loads` 与手写 command 校验；`actual_command` 的沙箱 wrap 逻辑、
`create_subprocess_shell`、退出码语义、超时与进程树处理全部保持。

- [ ] **Step 4: 适配直接调用测试**

`tests/tools/test_bash_sandbox.py` 中 `await tool.execute('{"command": "echo hello"}')`
改为 `await tool.execute(Params(command="echo hello"))`（顶部 import `Params`）。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools -q`
Expected: PASS

- [ ] **Step 6: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/tools tests/tools && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 5: load_skill / install_skill 迁移

**Files:**
- Modify: `src/Arkcode/tools/skill_tools/load_skill.py`
- Modify: `src/Arkcode/tools/skill_tools/install_skill.py`
- Modify: `tests/tools/test_skill_tools.py`
- Modify: `tests/tui/test_tui_skills.py`

**Interfaces:**
- Consumes: `Tool.params_model` / `execute(params)`（Task 1）。
- Produces: load_skill / install_skill 的 `Params` 模型。

- [ ] **Step 1: 写失败测试**

`tests/tools/test_skill_tools.py` 追加：

```python
from Arkcode.tools.skill_tools.load_skill import LoadSkillTool, Params as LoadParams


def test_load_skill_params_model_validates() -> None:
    assert LoadSkillTool.params_model.model_validate({"name": "x"}).name == "x"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_skill_tools.py -q`
Expected: FAIL（LoadSkillTool 无 `Params` / `params_model`）

- [ ] **Step 3: 迁移 load_skill**

`src/Arkcode/tools/skill_tools/load_skill.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    name: str = Field(description="Skill 名称")
```

`LoadSkillTool.params_model = Params`；`execute(params: Params)` 用 `params.name`，
删除 `json.loads`。

- [ ] **Step 4: 迁移 install_skill**

`src/Arkcode/tools/skill_tools/install_skill.py`：

```python
from pydantic import BaseModel, Field


class Params(BaseModel):
    url: str = Field(description="Skill 仓库 URL")
```

`InstallSkillTool.params_model = Params`；`execute(params: Params)` 用 `params.url`，
删除 `json.loads`。

- [ ] **Step 5: 适配直接调用测试**

`tests/tools/test_skill_tools.py` 与 `tests/tui/test_tui_skills.py` 中
`await tool.execute('{"name": ...}')` / `await app.install_skill_tool.execute(
'{"url": ...}')` 改为传入对应 `Params(...)`。

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools tests/tui/test_tui_skills.py -q`
Expected: PASS

- [ ] **Step 7: Phase 1 全量验证**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src/Arkcode`
Expected: 全绿（9 个工具全部模型化；`tests/agents`、`tests/integration` 经 registry 路径不受影响）

---

### Task 6: McpTool 动态参数模型

**Files:**
- Modify: `src/Arkcode/mcp/tool_adapter.py`
- Modify: `tests/mcp/test_mcp_tool.py`
- Modify: `tests/mcp/test_manager_status.py`

**Interfaces:**
- Consumes: `Tool.params_model`（Task 1）、远端 `input_schema`。
- Produces: `_build_params_model(tool_name, input_schema) -> type[BaseModel]`；
  `McpTool.params_model` 动态生成；execute 用 `model_validate_json` 与
  `model_dump(exclude_none=True)`。

- [ ] **Step 1: 写失败测试**

`tests/mcp/test_mcp_tool.py` 追加：

```python
import pytest

from Arkcode.mcp.tool_adapter import _build_params_model


def test_build_params_model_maps_types_and_required() -> None:
    model = _build_params_model(
        "demo",
        {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "name": {"type": "string"},
                "flag": {"type": "boolean"},
            },
            "required": ["name"],
        },
    )

    instance = model.model_validate({"name": "x", "count": "3", "flag": "true"})
    assert instance.model_dump(exclude_none=True) == {
        "name": "x",
        "count": 3,
        "flag": True,
    }

    with pytest.raises(Exception):
        model.model_validate({"count": 1})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/mcp/test_mcp_tool.py -q`
Expected: FAIL（`_build_params_model` 不存在）

- [ ] **Step 3: 实现动态模型与 execute 改造**

`src/Arkcode/mcp/tool_adapter.py`：

```python
from pydantic import BaseModel, create_model


def _build_params_model(tool_name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        py_type = _json_type_to_python(prop.get("type", "string"))
        if name in required:
            field_definitions[name] = (py_type, ...)
        else:
            field_definitions[name] = (py_type | None, None)
    return create_model(f"{tool_name}Params", **field_definitions)


def _json_type_to_python(json_type: str) -> type:
    mapping: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(json_type, str)
```

`McpTool` 增加字段：

```python
    params_model: type[BaseModel] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.params_model = _build_params_model(self.remote_name, self.input_schema)
```

`execute` 改为：

```python
    async def execute(self, args: str) -> Result:
        try:
            params = self.params_model.model_validate_json(args or "{}")
        except Exception as exc:
            return Result(content=f"参数校验失败: {exc}", is_error=True)
        arguments = params.model_dump(exclude_none=True) or None
        # 后续 call_tool 逻辑不变
```

（`json.loads` 与"参数 JSON 无效"分支删除；`call_timeout`、错误分类保持。）

- [ ] **Step 4: 适配 McpTool 直接调用测试**

`tests/mcp/test_mcp_tool.py` 中 `await tool.execute('{"value": "hello"}')` 等直接
调用：McpTool 的 `execute` 仍接收 JSON 字符串（`model_validate_json`），因此
**无需修改调用方式**；仅更新依赖 `execute` 解析语义的断言（如 `bad_json` 消息
从"参数 JSON 无效"变为"参数校验失败"）。

`tests/mcp/test_manager_status.py` 的 `_tool()` 构造 `McpTool` 后 `params_model`
由 `__post_init__` 生成，无需改动；如构造时 `input_schema` 为
`{"type": "object"}`（无 properties），模型字段为空，测试不受影响。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/mcp -q`
Expected: PASS

- [ ] **Step 6: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/mcp tests/mcp && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 7: config 模型 pydantic 化

**Files:**
- Modify: `src/Arkcode/config/models.py`
- Modify: `src/Arkcode/config/loader.py`
- Test: `tests/config/test_model_config.py`（新建）

**Interfaces:**
- Consumes: 现有 `ConfigError` 消息与 `load()` 业务校验。
- Produces: `ProviderConfig` / `Config` 为 pydantic BaseModel（frozen + extra="ignore"）；
  字段名、默认值、错误消息逐字不变。

- [ ] **Step 1: 写失败测试**

新建 `tests/config/test_model_config.py`：

```python
import pytest

from Arkcode.config import Config, ConfigError, ProviderConfig


def test_provider_config_is_frozen_and_repr_hides_key() -> None:
    config = ProviderConfig(
        name="Claude",
        protocol="anthropic",
        api_key="secret",
        model="claude-test",
    )

    assert config.base_url is None
    assert config.thinking is False
    assert config.context_window == 0
    assert "secret" not in repr(config)
    with pytest.raises(Exception):
        config.model = "other"  # type: ignore[misc]


def test_config_ignores_unknown_fields() -> None:
    config = Config.model_validate(
        {
            "providers": [],
            "unexpected": 1,
        }
    )
    assert config.providers == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/config/test_model_config.py -q`
Expected: FAIL（`ProviderConfig.model_validate` 不存在——dataclass 无该方法）

- [ ] **Step 3: models.py 改为 BaseModel**

`src/Arkcode/config/models.py`：

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProtocolName = Literal["anthropic", "openai"]


class ConfigError(Exception):
    """配置不可用时抛出的可读错误。"""


class ProviderConfig(BaseModel):
    """单个模型服务配置。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    protocol: ProtocolName
    api_key: str = Field(repr=False)
    model: str
    base_url: str | None = None
    thinking: bool = False
    context_window: int = 0


class Config(BaseModel):
    """应用配置。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    providers: list[ProviderConfig]
```

- [ ] **Step 4: 适配 loader.py 构造方式**

`src/Arkcode/config/loader.py`：所有 `ProviderConfig(...)` / `Config(...)` 构造点
语法不变（pydantic 与 dataclass 构造语法相同）；仅当 loader 用 `dataclasses.replace`
或 `asdict` 时需要改（如有则改为 `model_copy` / `model_dump`）。业务校验与
`ConfigError` 消息逐字保留。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/config tests/application/test_cli.py -q`
Expected: 现有错误消息断言全部 PASS（消息由 loader 保留）；新增结构测试 PASS

- [ ] **Step 6: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/config tests/config && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 8: mcp config 模型 pydantic 化

**Files:**
- Modify: `src/Arkcode/mcp/config.py`
- Test: `tests/mcp/test_mcp_config.py`（追加结构测试）

**Interfaces:**
- Consumes: 现有 `_warn` 消息与 `${VAR}` 展开逻辑。
- Produces: `ServerConfig` / `Config` 为 pydantic BaseModel（frozen + extra="ignore"）。

- [ ] **Step 1: 写失败测试**

`tests/mcp/test_mcp_config.py` 追加：

```python
from Arkcode.mcp.config import ServerConfig


def test_server_config_defaults_and_ignores_unknown() -> None:
    config = ServerConfig.model_validate(
        {
            "type": "stdio",
            "command": "npx",
            "extra": 1,
        }
    )
    assert config.args == []
    assert config.env == {}
    assert config.url == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/mcp/test_mcp_config.py -q`
Expected: FAIL（`ServerConfig.model_validate` 不存在）

- [ ] **Step 3: models 改 BaseModel**

`src/Arkcode/mcp/config.py`：

```python
from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    """一个已经完成变量展开和字段校验的 MCP server。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class Config(BaseModel):
    """归一化后的 MCP 配置。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    servers: dict[str, ServerConfig] = Field(default_factory=dict)
```

`_RawServer`、`_warn` 消息、`${VAR}` 展开函数与加载流程全部保留；`ServerConfig`/
`Config` 构造点语法不变。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/mcp -q`
Expected: PASS（现有 `_warn` 消息断言不变）

- [ ] **Step 5: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/mcp tests/mcp && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 11: instructions 注入

**Files:**
- Modify: `src/Arkcode/mcp/manager.py`
- Modify: `src/Arkcode/application/session.py`
- Modify: `src/Arkcode/application/bootstrap.py`
- Test: `tests/mcp/test_instructions.py`（新建）、`tests/application/test_session_service.py`（追加）

**Interfaces:**
- Consumes: `Manager._sessions` / `_tools` / `_failures`（已有）。
- Produces: `Manager.instructions_text() -> str`；
  `SessionService(mcp_instructions: str = "")` 参数并注入 Agent 稳定指令。

- [ ] **Step 1: 写失败测试**

新建 `tests/mcp/test_instructions.py`：

```python
from Arkcode.mcp.manager import Manager, _Session
from Arkcode.mcp.tool_adapter import McpTool


class Caller:
    async def call_tool(self, name: str, arguments: dict | None = None):
        return None


def _tool(server: str) -> McpTool:
    return McpTool(
        full_name=f"mcp__{server}__echo",
        remote_name="echo",
        tool_description="echo",
        input_schema={"type": "object"},
        _read_only=True,
        caller=Caller(),
    )


def test_instructions_text_lists_tools_when_no_instructions() -> None:
    manager = Manager()
    manager._sessions.append(_Session(name="demo", session=object()))
    manager._tools.append(_tool("demo"))

    text = manager.instructions_text()

    assert "# MCP Server Instructions" in text
    assert "## demo" in text
    assert "mcp__demo__echo" in text
```

`tests/application/test_session_service.py` 追加：

```python
def test_mcp_instructions_merge_into_agent_instruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(tmp_path)
    provider = RecordingProvider()
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service._instruction_text = "base"
    service._mcp_instructions = "\n# MCP Server Instructions\n## demo\n..."

    service.activate_provider(config())

    assert service.agent is not None
    assert service.agent._instruction_text == (
        "base\n\n# MCP Server Instructions\n## demo\n..."
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/mcp/test_instructions.py tests/application/test_session_service.py -q`
Expected: FAIL（`instructions_text` 不存在、`_mcp_instructions` 属性不存在）

- [ ] **Step 3: 实现 manager.instructions_text**

`src/Arkcode/mcp/manager.py`：

```python
    def instructions_text(self) -> str:
        """按 server 名生成 MCP 指令段落；无 instructions 时列工具名。"""

        if not self._sessions:
            return ""
        parts: list[str] = []
        for session in sorted(self._sessions, key=lambda item: item.name):
            instructions = getattr(session.session, "mcp_instructions", "") or ""
            section = f"## {session.name}\n"
            if instructions:
                section += instructions
            else:
                tool_names = [
                    tool.full_name
                    for tool in self._tools
                    if tool.full_name.startswith(f"mcp__{session.name}__")
                ]
                if tool_names:
                    section += "Available tools: " + ", ".join(tool_names)
            parts.append(section)
        return "# MCP Server Instructions\n\n" + "\n\n".join(parts)
```

`_do_connect` 中 `await session.initialize()` 改为保存 instructions：

```python
        init_result = await session.initialize()
        session.mcp_instructions = getattr(init_result, "instructions", "") or ""
```

`_Session` dataclass 增加字段 `mcp_instructions: str = ""`。

- [ ] **Step 4: 实现 SessionService 注入**

`src/Arkcode/application/session.py`：

- `__init__` 增加参数 `mcp_instructions: str = ""`，存 `self._mcp_instructions`；
- `activate_provider` 创建 Agent 时 `instruction_text` 传：

```python
            instruction_text=(
                self._instruction_text
                + ("\n\n" + self._mcp_instructions if self._mcp_instructions else "")
            ),
```

- [ ] **Step 5: bootstrap 装配**

`src/Arkcode/application/bootstrap.py` 构造 `SessionService` 时增加
`mcp_instructions=mcp_manager.instructions_text()`。

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/mcp/test_instructions.py tests/application -q`
Expected: PASS

- [ ] **Step 7: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/mcp src/Arkcode/application && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 12: 懒重连 / 按需连接

**Files:**
- Modify: `src/Arkcode/mcp/manager.py`
- Modify: `src/Arkcode/mcp/tool_adapter.py`
- Test: `tests/mcp/test_reconnect.py`（新建）

**Interfaces:**
- Consumes: `_do_connect` / `_connect_one`（已有）、`McpTool`（Task 6）。
- Produces: `Manager.get_client(name)`、`Manager.call_server_tool(name, tool, args)`、
  `McpTool` 增加 `manager` / `server_name` 并由 manager 执行调用。

- [ ] **Step 1: 写失败测试**

新建 `tests/mcp/test_reconnect.py`：

```python
import asyncio

import pytest

from Arkcode.mcp.manager import Manager


class FlakyCaller:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, name: str, arguments: dict | None = None):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("broken")
        return object()


@pytest.mark.asyncio
async def test_call_server_tool_retries_once_after_reconnect(monkeypatch) -> None:
    manager = Manager()
    caller = FlakyCaller()

    async def fake_get_client(name: str):
        return caller

    monkeypatch.setattr(manager, "get_client", fake_get_client)
    async def fake_reconnect(name: str) -> None:
        return None

    monkeypatch.setattr(manager, "_reconnect_server", fake_reconnect)

    result = await manager.call_server_tool("demo", "echo", {})

    assert caller.calls == 2
    assert result is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/mcp/test_reconnect.py -q`
Expected: FAIL（`call_server_tool` 不存在）

- [ ] **Step 3: 实现 Manager 重连能力**

`src/Arkcode/mcp/manager.py`：

```python
    def get_client(self, name: str):
        """返回已连接会话；未连接时按需连接（返回 None 表示失败）。"""

        for session in self._sessions:
            if session.name == name:
                return session.session
        return None

    async def _reconnect_server(self, name: str) -> None:
        """关闭并重连单个 server；失败记录到 _failures。"""

        for task in self._tasks:
            if task.get_name() == f"mcp:{name}" and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._sessions = [item for item in self._sessions if item.name != name]
        self._tools = [item for item in self._tools if not item.full_name.startswith(f"mcp__{name}__")]
        server = self._configs.get(name)
        if server is None:
            self._failures[name] = "server config not found"
            return
        ready: asyncio.Future[Exception | None] = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(
            _connect_one(self, name, server, self._version, ready),
            name=f"mcp:{name}",
        )
        self._tasks.append(task)
        try:
            error = await asyncio.wait_for(asyncio.shield(ready), timeout=connect_timeout)
        except TimeoutError:
            error = RuntimeError("reconnect timeout")
        if error is not None:
            self._failures[name] = str(error)

    async def call_server_tool(self, name: str, tool_name: str, arguments: dict | None):
        """调用远端工具；连接断开时重连一次再重试。"""

        caller = self.get_client(name)
        if caller is None:
            await self._reconnect_server(name)
            caller = self.get_client(name)
            if caller is None:
                raise RuntimeError(self._failures.get(name, f"server {name} unavailable"))
        try:
            return await caller.call_tool(tool_name, arguments)
        except Exception as error:
            await self._reconnect_server(name)
            caller = self.get_client(name)
            if caller is None:
                raise error
            return await caller.call_tool(tool_name, arguments)
```

`Manager.__init__` 增加 `self._version: str = ""` 与 `self._configs: dict[str, ServerConfig] = {}`；
`new_manager` 创建 Manager 时传入 `version` 并把 `cfg.servers` 存入 `_configs`。

- [ ] **Step 4: McpTool 委托 manager**

`src/Arkcode/mcp/tool_adapter.py`：`McpTool` 增加字段
`server_name: str` 与 `manager: Any = None`（默认 None 兼容测试构造）；`execute`
中调用点改为：

```python
        if self.manager is not None:
            result = await asyncio.wait_for(
                self.manager.call_server_tool(self.server_name, self.remote_name, arguments),
                timeout=call_timeout,
            )
        else:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arguments),
                timeout=call_timeout,
            )
```

`adapt_tool` 增加 `server_name` 参数并透传；`_do_connect` 调用处传
`manager` 与 `name`。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/mcp -q`
Expected: PASS（现有测试兼容默认 manager=None 路径）

- [ ] **Step 6: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/mcp tests/mcp && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 13: registry 懒加载扩展

**Files:**
- Modify: `src/Arkcode/tools/registry.py`
- Test: `tests/tools/test_deferred.py`（新建）

**Interfaces:**
- Consumes: `Tool.should_defer`（Task 1）。
- Produces: `mark_discovered` / `is_discovered` / `get_deferred_tool_names` /
  `search_deferred` / `find_deferred_by_names`；`definitions()` /
  `read_only_definitions()` 过滤未发现的延迟工具。

- [ ] **Step 1: 写失败测试**

新建 `tests/tools/test_deferred.py`：

```python
from pydantic import BaseModel

from Arkcode.tools.base import Tool
from Arkcode.tools.registry import Registry


class _Params(BaseModel):
    pass


class DeferredTool(Tool):
    read_only = True
    should_defer = True
    params_model = _Params

    def name(self) -> str:
        return "deferred_demo"

    def description(self) -> str:
        return "demo"

    async def execute(self, params: object):
        return None


def test_deferred_tools_excluded_until_discovered() -> None:
    registry = Registry()
    registry.register(DeferredTool())

    assert [item.name for item in registry.definitions()] == []
    assert registry.get_deferred_tool_names() == ["deferred_demo"]

    registry.mark_discovered("deferred_demo")

    assert [item.name for item in registry.definitions()] == ["deferred_demo"]
    assert registry.get_deferred_tool_names() == []


def test_search_deferred_scores_by_name_and_description() -> None:
    registry = Registry()
    registry.register(DeferredTool())

    found = registry.search_deferred("demo", 5)

    assert found[0]["name"] == "deferred_demo"
    assert registry.find_deferred_by_names(["deferred_demo"])[0]["input_schema"] is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_deferred.py -q`
Expected: FAIL（`get_deferred_tool_names` 等方法不存在）

- [ ] **Step 3: 实现 registry 扩展**

`src/Arkcode/tools/registry.py`：

```python
    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}
        self._discovered: set[str] = set()

    def mark_discovered(self, name: str) -> None:
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        return name in self._discovered

    def _is_deferred(self, tool: Tool) -> bool:
        return bool(getattr(tool, "should_defer", False))

    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name in self._order
            if self._is_deferred(self._tools[name]) and name not in self._discovered
        ]

    def search_deferred(self, query: str, max_results: int) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[int, str, Tool]] = []
        for name in self._order:
            tool = self._tools[name]
            if not self._is_deferred(tool) or name in self._discovered:
                continue
            score = 0
            if query_lower in name.lower():
                score += 10
            if query_lower in (tool.description() or "").lower():
                score += 5
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            tool.get_schema() for _, name, tool in scored[:max_results]
        ]

    def find_deferred_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        return [
            self._tools[name].get_schema()
            for name in names
            if name in self._tools
            and self._is_deferred(self._tools[name])
            and name not in self._discovered
        ]
```

`definitions()` / `read_only_definitions()` 增加过滤：

```python
            for name in self._order
            if not self._is_deferred(self._tools[name]) or name in self._discovered
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools/test_deferred.py tests/tools -q`
Expected: PASS（内置工具 `should_defer=False`，行为不变）

- [ ] **Step 5: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/tools tests/tools && .venv/bin/mypy src/Arkcode`
Expected: 无输出

---

### Task 14: ToolSearch 工具与装配

**Files:**
- Create: `src/Arkcode/tools/builtins/tool_search.py`
- Modify: `src/Arkcode/tools/__init__.py`
- Modify: `src/Arkcode/tui/app.py`
- Modify: `tests/tools/test_tool_search.py`（新建）、`tests/tools/test_deferred.py`（追加）

**Interfaces:**
- Consumes: `Registry.search_deferred` / `find_deferred_by_names` /
  `mark_discovered` / `get_deferred_tool_names`（Task 13）。
- Produces: `ToolSearchTool(registry)`；`McpTool.should_defer = True`；
  `ArkCodeApp.__init__` 注册 ToolSearch。

- [ ] **Step 1: 写失败测试**

新建 `tests/tools/test_tool_search.py`：

```python
import pytest

from Arkcode.tools.builtins.tool_search import ToolSearchTool
from Arkcode.tools.builtins.tool_search import Params

from .test_deferred import DeferredTool


def make_registry_with_deferred():
    from Arkcode.tools.registry import Registry

    registry = Registry()
    registry.register(DeferredTool())
    return registry


@pytest.mark.asyncio
async def test_tool_search_select_loads_deferred_tool() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="select:deferred_demo"))

    assert result.is_error is False
    assert "deferred_demo" in result.content
    assert [item.name for item in registry.definitions()] == ["deferred_demo"]


@pytest.mark.asyncio
async def test_tool_search_keyword_lists_matches() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="demo"))

    assert "Found 1 tool" in result.content


@pytest.mark.asyncio
async def test_tool_search_no_match_lists_available() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="nothing"))

    assert "deferred_demo" in result.content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_tool_search.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 ToolSearch**

新建 `src/Arkcode/tools/builtins/tool_search.py`：

```python
"""按需发现延迟加载工具的 ToolSearch 内置工具。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..base import Result, Tool

if TYPE_CHECKING:
    from ..registry import Registry


class Params(BaseModel):
    query: str = Field(
        description="搜索关键词，或以 select:<name>[,<name>...] 精确加载"
    )
    max_results: int = Field(default=5, description="返回结果上限")


class ToolSearchTool(Tool):
    """搜索并加载未立即可用的延迟工具。"""

    read_only = True
    should_defer = False
    params_model = Params

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def name(self) -> str:
        return "ToolSearch"

    def description(self) -> str:
        return (
            "搜索并加载当前不可用的延迟工具；"
            "使用 select:<name>[,<name>...] 按名加载，或提供关键词搜索"
        )

    async def execute(self, params: Params) -> Result:
        query = params.query
        if query.startswith("select:"):
            names = [item.strip() for item in query[7:].split(",") if item.strip()]
            schemas = self._registry.find_deferred_by_names(names)
        else:
            schemas = self._registry.search_deferred(query, params.max_results)
        if not schemas:
            deferred = self._registry.get_deferred_tool_names()
            return Result(
                content=(
                    f'No matching deferred tools for "{query}". '
                    f"Available: {', '.join(deferred)}"
                )
            )
        for schema in schemas:
            if "name" in schema:
                self._registry.mark_discovered(schema["name"])
        return Result(
            content=(
                f"Found {len(schemas)} tool(s). Their full schemas are now loaded:\n\n"
                f"{json.dumps(schemas, indent=2, ensure_ascii=False)}"
            )
        )
```

- [ ] **Step 4: 导出、McpTool 标记与 App 装配**

- `src/Arkcode/tools/__init__.py` 导出 `ToolSearchTool`。
- `src/Arkcode/mcp/tool_adapter.py`：`McpTool` 增加类属性 `should_defer = True`。
- `src/Arkcode/tui/app.py`：`__init__` 中注册
  `self._tool_registry.register(ToolSearchTool(self._tool_registry))`
  （与 load/install skill 工具并列，import `ToolSearchTool`）。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools tests/tui tests/integration -q`
Expected: PASS（契约测试 6 工具不变——`new_default_registry()` 不含 ToolSearch）

- [ ] **Step 6: Phase 4 全量验证**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src/Arkcode`
Expected: 全绿

---

### Task 15: README 与最终验证

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`（pydantic 依赖若 Task 1 未加）

**Interfaces:**
- Consumes: 全部已完成任务。
- Produces: README 依赖与能力说明、最终验证记录。

- [ ] **Step 1: 更新 pyproject 与 README**

`pyproject.toml` 的 `dependencies` 增加 `"pydantic>=2"`。
README 依赖段增加 pydantic；MCP 段落补充：MCP 工具指令注入、延迟加载与
`ToolSearch` 说明（各一两句）。

- [ ] **Step 2: 全量验证**

Run: `.venv/bin/pytest -q`
Expected: 全绿

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src/Arkcode && .venv/bin/python -m Arkcode --version`
Expected: 全部通过，版本输出 `0.1.0`

- [ ] **Step 3: 行为契约复核**

Run: `.venv/bin/pytest tests/integration/test_behavior_contracts.py -q`
Expected: PASS（6 工具列表保持）

- [ ] **Step 4: 确认无未验证改动（不提交）**

Run: `git status --short`
Expected: 本次所有改动未提交（由用户手动提交）

---

### Task 9: permissions settings 模型 pydantic 化

**Files:**
- Modify: `src/Arkcode/permissions/settings.py`
- Test: `tests/permissions/test_settings_model.py`（新建）

**Interfaces:**
- Consumes: 现有 `SettingsError` 消息与"忽略非字符串项"宽容行为。
- Produces: `Settings` / `PermissionsBlock` 为 pydantic BaseModel（extra="ignore"）。

- [ ] **Step 1: 写失败测试**

新建 `tests/permissions/test_settings_model.py`：

```python
from pathlib import Path

from Arkcode.permissions.settings import load_settings


def test_settings_ignores_non_string_permission_items(tmp_path: Path) -> None:
    path = tmp_path / "permissions.yaml"
    path.write_text(
        "default_mode: default\n"
        "permissions:\n"
        "  allow:\n"
        "    - read_file\n"
        "    - 123\n",
        encoding="utf-8",
    )

    settings = load_settings(str(path))

    assert settings.permissions.allow == ["read_file"]
    assert settings.default_mode == "default"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/permissions/test_settings_model.py -q`
Expected: FAIL（当前 `_strings` 已满足该行为，测试会先 PASS——先确认现状；
若 PASS 则跳过 RED，直接进入 Step 3，测试作为冻结）

- [ ] **Step 3: models 改 BaseModel**

`src/Arkcode/permissions/settings.py`：

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermissionsBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)

    @field_validator("allow", "ask", "deny", mode="before")
    @classmethod
    def _ignore_non_strings(cls, value: object) -> object:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_mode: str = ""
    permissions: PermissionsBlock = Field(default_factory=PermissionsBlock)
```

`load_settings` 的 yaml 读取、`SettingsError` 与消息保留；构造 `Settings(...)` 处
改为 `Settings.model_validate(raw)`（`default_mode` 非字符串时为空字符串的现有
行为用 validator 或构造后归一化保留）。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/permissions -q`
Expected: PASS（现有行为断言不变）

- [ ] **Step 5: Phase 2 全量验证**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src/Arkcode`
Expected: 全绿

---

### Task 10: 富内容结果提取

**Files:**
- Modify: `src/Arkcode/mcp/tool_adapter.py`
- Test: `tests/mcp/test_tool_adapter.py`（追加）

**Interfaces:**
- Consumes: `McpTool.execute`（Task 6 已模型化）。
- Produces: `_extract_text(content) -> str` 处理 Text / Image / EmbeddedResource。

- [ ] **Step 1: 写失败测试**

`tests/mcp/test_tool_adapter.py` 追加：

```python
import mcp.types as mtypes

from Arkcode.mcp.tool_adapter import _extract_text


def test_extract_text_handles_rich_blocks() -> None:
    text = mtypes.TextContent(type="text", text="hello")
    image = mtypes.ImageContent(type="image", data="...", mimeType="image/png")
    resource = mtypes.EmbeddedResource(
        type="resource",
        resource=mtypes.TextResourceContents(
            uri="file:///a.txt",
            text="content",
        ),
    )

    assert _extract_text([text, image, resource]) == (
        "hello\n[image: image/png]\ncontent"
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/mcp/test_tool_adapter.py -q`
Expected: FAIL（`_extract_text` 不存在）

- [ ] **Step 3: 实现 _extract_text 并替换 execute 提取**

`src/Arkcode/mcp/tool_adapter.py`：

```python
def _extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if isinstance(block, mtypes.TextContent):
            parts.append(block.text)
        elif isinstance(block, mtypes.ImageContent):
            parts.append(f"[image: {block.mimeType}]")
        elif isinstance(block, mtypes.EmbeddedResource):
            resource = block.resource
            if hasattr(resource, "text"):
                parts.append(resource.text)
            else:
                parts.append(f"[binary resource: {resource.uri}]")
    return "\n".join(parts) if parts else "(no output)"
```

`McpTool.execute` 中删除 `texts` 列表、`dropped_non_text` 与
`_non_text_warn_once` 逻辑，改为 `content = _extract_text(result.content)`；
删除 `_non_text_warn_once` 模块级变量。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/mcp -q`
Expected: PASS

- [ ] **Step 5: 定向验证（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/mcp tests/mcp && .venv/bin/mypy src/Arkcode`
Expected: 无输出
