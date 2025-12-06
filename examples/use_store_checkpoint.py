import os
from deepagents import create_deep_agent, CompiledSubAgent
from langchain_openai import ChatOpenAI
from langgraph.store.memory import InMemoryStore
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend, FilesystemBackend
from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
import psycopg 


# Example 1
load_dotenv(override=True)
LANGGRAPH_DB_URL = os.getenv("LANGGRAPH_DB_URL")

SYSTEM_PROMPT = """
You are a helpful assistant.
"""

model = ChatOpenAI(model='glm-4.6')

if LANGGRAPH_DB_URL:
    with (
        PostgresSaver.from_conn_string(LANGGRAPH_DB_URL) as checkpointer,
        PostgresStore.from_conn_string(LANGGRAPH_DB_URL) as store,
    ):
        
        agent = create_deep_agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            store=store,
            backend= FilesystemBackend(
                "D:/ai_lab/langgraph-agents/agent_files_space",
                virtual_mode=True,
                max_file_size_mb=200
            ),
            checkpointer=checkpointer
        )


# Example 2

DB_URI = "postgresql://postgres:han8113261@192.168.31.3:5432/langgraph_db"

# 关键：设置 autocommit=True
conn = psycopg.connect(DB_URI, autocommit=True)

checkpointer = PostgresSaver(conn=conn)
store = PostgresStore(conn=conn)

# 现在可以成功运行 setup
checkpointer.setup()
store.setup()


load_dotenv(override=True)

SYSTEM_PROMPT = """
You are a helpful assistant.
"""

model = ChatOpenAI(model='glm-4.6')

agent = create_deep_agent(
    model=model,
    system_prompt=SYSTEM_PROMPT,
    store=store,
    backend= FilesystemBackend(
        "D:/ai_lab/langgraph-agents/agent_files_space",
        virtual_mode=True,
        max_file_size_mb=200
    ),
    checkpointer=checkpointer
)