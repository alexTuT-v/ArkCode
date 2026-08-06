"""稳定系统提示的组装逻辑。"""

from .modules import Module, fixed_modules, optional_modules


def assemble_system(modules: list[Module]) -> str:
    """按优先级稳定组装非空模块。"""

    return "\n\n".join(
        module.content
        for module in sorted(modules, key=lambda item: item.priority)
        if module.content
    )


def build_system_prompt() -> str:
    """构造跨轮逐字节稳定的系统提示。"""

    return assemble_system(fixed_modules() + optional_modules())
