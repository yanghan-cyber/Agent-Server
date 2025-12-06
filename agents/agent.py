from dataclasses import dataclass
import os
from deepagents import create_deep_agent, CompiledSubAgent
from langchain_openai import ChatOpenAI
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from deepagents.backends import (
    FilesystemBackend,
)
from dotenv import load_dotenv
from agents.web_agent.agent import web_agent_config

from agents.main_agent.middleware import MainAgentMiddleware
from agents.main_agent.prompt import MAIN_AGENT_SYSTEM_PROMPT
from memory.middleware import MemOSMiddleware

load_dotenv(override=True)

@dataclass
class Context:
    thread_id: str      
    user_id: str

default_model = ChatOpenAI(model="glm-4.6")

agent = create_deep_agent(
    model=default_model,
    system_prompt=MAIN_AGENT_SYSTEM_PROMPT,
    store=InMemoryStore(),
    backend=FilesystemBackend(
        "D:/ai_lab/langgraph-agents/agent-store-space",
        virtual_mode=True,
        max_file_size_mb=200,
    ),
    subagents=[web_agent_config],
    middleware=[MemOSMiddleware(), MainAgentMiddleware()],
    checkpointer=InMemorySaver(),
    context_schema=Context
)


if __name__ == "__main__":
    import asyncio
    context =  {"thread_id": "user_123", "user_id": "user_default"}
    config1 = {"configurable": context}
    async def main(user_input):
        async for mode, chunk in agent.astream({"messages": [{"role": "user", "content": user_input}]},
                                               config=config1, context=context,stream_mode=["values"]):
            if 'messages' in chunk:
                chunk['messages'][-1].pretty_print()

    asyncio.run(main("你记得我叫什么名字吗？"))
    
    asyncio.run(main("告诉你个新消息，我的出生日期在1997年11月7号。"))

    
