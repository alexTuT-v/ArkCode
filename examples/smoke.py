"""以真实 provider 验证系统提示缓存用量。"""

import asyncio
from pathlib import Path

from Arkcode import __version__
from Arkcode.agent import new_agent
from Arkcode.config import load
from Arkcode.conversation import Conversation
from Arkcode.llm import new_provider
from Arkcode.permission import Mode, new_engine
from Arkcode.tool import new_default_registry


async def main() -> None:
    """连发两轮请求，打印每次的输入、输出和缓存用量。"""

    config = load(".env")
    provider = new_provider(config.providers[0])
    conversation = Conversation()
    engine, _ = new_engine(str(Path.cwd().resolve()))
    agent = new_agent(provider, new_default_registry(), __version__, engine)
    for prompt in ("Reply with: ready", "Reply with: cached"):
        conversation.add_user(prompt)
        cancel = asyncio.Event()
        async with asyncio.timeout(60):
            async for event in agent.run(conversation, Mode.BYPASS, cancel):
                if event.err is not None:
                    print(f"error={event.err}")
                if event.usage is not None:
                    usage = event.usage
                    print(
                        f"input={usage.input} output={usage.output} "
                        f"cache_write={usage.cache_write} "
                        f"cache_read={usage.cache_read}"
                    )


if __name__ == "__main__":
    asyncio.run(main())
