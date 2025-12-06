import os
from langchain.agents import create_agent

from .middleware import WebAgentMiddleware

from langchain.agents.middleware import TodoListMiddleware
from .tools import web_fetch, web_search
from langchain_openai import ChatOpenAI
from .prompt import RESEARCHER_SYSTEM_PROMPT

web_agent = create_agent(
    model=ChatOpenAI(model=os.getenv("OPENAI_MODEL")),
    tools=[web_fetch, web_search],
    system_prompt=RESEARCHER_SYSTEM_PROMPT,
    middleware=[TodoListMiddleware(), WebAgentMiddleware()],
)



web_agent_config = {
    "name": "Web-Searcher",
    "description": "Specialized agent for web search. ",
    "system_prompt": RESEARCHER_SYSTEM_PROMPT,
    "tools": [web_search, web_fetch],
    "middleware": [WebAgentMiddleware()],
}


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(override=True)
    import asyncio

    async def main():
        async for mode, chunk in web_agent.astream(
            {"messages": "领益智造这支股票有投资的价值吗？"}, stream_mode=["values"]
        ):
            if "messages" in chunk:
                chunk["messages"][-1].pretty_print()
        async for mode, chunk in web_agent.astream(
            {"messages": "领益智造这支股票有投资的价值吗？"}, stream_mode=["values"]
        ):
            if "messages" in chunk:
                chunk["messages"][-1].pretty_print()

    asyncio.run(main())
