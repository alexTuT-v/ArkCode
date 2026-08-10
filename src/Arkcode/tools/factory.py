"""内置工具集装配。"""

from .registry import Registry


def new_default_registry() -> Registry:
    """按稳定顺序注册六个内置工具。"""

    from .builtins.bash import BashTool
    from .builtins.edit_file import EditFileTool
    from .builtins.glob import GlobTool
    from .builtins.grep import GrepTool
    from .builtins.read_file import ReadFileTool
    from .builtins.write_file import WriteFileTool

    registry = Registry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ):
        registry.register(tool)
    return registry
