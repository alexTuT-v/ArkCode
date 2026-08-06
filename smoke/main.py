"""以 bypass 模式运行真实 provider 冒烟流程。"""

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
    config = load(".env")
    provider = new_provider(config.providers[0])
    engine, _ = new_engine(str(Path.cwd().resolve()))
    agent = new_agent(provider, new_default_registry(), __version__, engine)
    conversation = Conversation()
    conversation.add_user("Reply with: ready")
    async with asyncio.timeout(60):
        async for event in agent.run(conversation, Mode.BYPASS, asyncio.Event()):
            if event.err is not None:
                raise event.err
            if event.text:
                print(event.text, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
