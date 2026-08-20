"""稳定系统提示的组装逻辑。"""

from collections.abc import Mapping

from .modules import Module, fixed_modules, optional_modules


def assemble_system(modules: list[Module]) -> str:
    """按优先级稳定组装非空模块。"""

    return "\n\n".join(
        module.content
        for module in sorted(modules, key=lambda item: item.priority)
        if module.content
    )


def build_system_prompt(instructions: str = "", memory: str = "") -> str:
    """构造跨轮逐字节稳定的系统提示。"""

    return assemble_system(fixed_modules() + optional_modules(instructions, memory))


def render_agent_catalog(items: list[tuple[str, str]]) -> str:
    """渲染供主模型选择定义式 SubAgent 的角色元数据。"""

    if not items:
        return ""
    lines = [
        "## Available Sub-Agent Types",
        "",
        "Use the Agent tool with subagent_type to delegate tasks:",
        "",
    ]
    lines.extend(f"- {name}: {description}" for name, description in items)
    lines.extend(
        (
            "",
            "Leave subagent_type empty to fork the current conversation.",
        )
    )
    return "\n".join(lines)


def render_skill_catalog(items: list[tuple[str, str]]) -> str:
    """只渲染可用于渐进披露的 Skill 元数据。"""

    if not items:
        return ""
    lines = ["## Available Skills", ""]
    lines.extend(f"- {name}: {description}" for name, description in items)
    lines.extend(
        (
            "",
            "If the user's request matches a Skill, call LoadSkill to activate it.",
        )
    )
    return "\n".join(lines)


def render_active_skills(active: Mapping[str, str]) -> str:
    """渲染已激活 Skill 的完整 SOP。"""

    if not active:
        return ""
    sections = ["## Active Skills"]
    for name, body in active.items():
        sections.append(f"### Skill: {name}\n\n{body}")
    return "\n\n".join(sections)
