from datetime import datetime
from typing import Awaitable, Callable, List, cast
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelCallResult,
    ModelRequest,
    ModelResponse,
    OmitFromInput,
)
from langchain.messages import SystemMessage
from .memos_client import MemosClient
from langchain_core.messages.base import BaseMessage
from langchain.tools import tool

SEARCH_MEMO_TOOL_DESCRIPTION = """
This tool is your access to the User's Long-Term Memory (facts, preferences, past projects).
Use this to retrieve context that is NOT in the current conversation window.
## Args:
- query: The text content to be queried in the memory
- memory_limit: The number of factual memories to be returned, with a default value of 10
- includePreference: Whether to enable the recall of preferred memories, with a default value of True
- preference_limit: The number of preferred memories to be returned, with a default value of 6

## Effective Query Strategy
- **DO NOT** use generic queries like "user history" or "preferences".
- **DO** extract specific entities or topics. 
  - *Bad*: "What did the user say?"
  - *Good*: "spicy food tolerance", "Python project config", "trip to Guangzhou"
- **Multiple Queries**: If the user asks complex questions, you can call this tool multiple times with different focus topics.

## When to Skip
- Do not search for simple greetings ("Hello").
- Do not search for general knowledge ("What is Python?").
- Do not search if the info was just mentioned 2 turns ago (it's in short-term context).
"""

MEMO_SYSTEM_PROMPT = """## 🧠 Long-term Memory Architecture

You are paired with a **MemOS Memory System** that stores the user's personal context.
This differentiates you from a generic AI. You "know" the user.

### 1. The "Recall First" Rule
Before answering ANY question involving choices, recommendations, or personal context, you MUST:

1.  **Analyze & Decompose**: Does this request touch on multiple aspects of the user's life? 
    -   Example: For coding questions like "Help me write simple a neural network FFN", you can search like ("User coding Language and Style", "User recent Projects" etc.).
    -   Example: For "Plan a trip", launch `search_memos("user travel preference")`,`search_memos("Where the user has traveled")`, `search_memos("user travel budget")`, and `search_memos("user dietary restriction")` simultaneously.
2.  **Parallel Search (CRITICAL)**: **DO NOT** limit yourself to a single search query.
    -   You MUST call `search_memos` **multiple times in parallel** if the context is multi-dimensional.
    -  **DO NOT** search for:
        -  simple greetings ("Hello"), or general knowledge ("What is Python?"). 
        -  if the info was just mentioned 8 turns ago (it's in short-term context).
        -   the same information multiple times, or information that is not relevant to the current conversation.
        -   the information that is too broad or general in nature.
3.  **Synthesize**: Combine all retrieved memory fragments with new info to generate a personalized response.
4.  **Evaluate**: Evaluate the relevance of the memory to the current task.


### 2. Natural Integration (Crucial)
When you call `search_memos` in your response, **DO NOT** say: "I need to check my memory..." or "let's search my memory...".
When you find a memory, **DO NOT** say: "According to the database..." or "I found a record...".
**DO** speak naturally, like an old friend remembering a fact.
- *Bad*: "I need find my memory to ensure your food preferences."
- *Good*: "Let me think for a moment about what you like to eat."
- *Bad*: "Found memory: User likes spicy food. I recommend hotpot."
- *Good*: "Since I know you enjoy spicy food, how about trying that hotpot place?"

### 3. Handling "No Memory"
If `search_memos` returns nothing:
- Proceed normally.
- **DO NOT** apologize for not knowing.
- **DO NOT** hallucinate a memory.

### 4. Conflict Resolution
- **Present > Past**: If the user's current statement contradicts a memory (e.g., Memory: "Hates cilantro", User: "I love cilantro now"), **TRUST THE USER'S CURRENT STATEMENT**.
- The **MemOS Memory System** will automatically update the memory later. You just follow the current instruction.
"""


class MemOSMiddleware(AgentMiddleware):
    memo_client = MemosClient()

    def __init__(self):
        super().__init__()
        self.system_prompt = MEMO_SYSTEM_PROMPT
        @tool(description=SEARCH_MEMO_TOOL_DESCRIPTION)
        def search_memos(
            query: str,
            memory_limit: int = 10,
            include_preference: bool = True,
            preference_limit: int = 6,
            runtime=None
        ) -> str:
            """
            Search user's long-term memory.
            Returns a clean, summarized text for the AI to read.
            """
            # 1. 获取 ID (假设你已经解决了 runtime 注入问题，或者使用闭包捕获了 user_id)
            user_id = getattr(runtime.context, "user_id", "default_user") if runtime else "default_user"
            conversation_id = getattr(runtime.context, "thread_id", None) if runtime else None
            
            # 2. 调用 API
            try:
                raw_result = self.memo_client.search_memory(
                    user_id,
                    query,
                    conversation_id,
                    memory_limit,
                    include_preference,
                    preference_limit,
                )
            except Exception as e:
                return f"Error retrieving memory: {str(e)}"

            # 3. 数据清洗与格式化 (Core Logic)
            if not raw_result:
                return "No relevant memories found."

            memories = raw_result.get("memory_detail_list", [])
            preferences = raw_result.get("preference_detail_list", [])
            
            output_lines = []

            # --- A. 处理偏好 (Preferences) ---
            if include_preference and preferences:
                output_lines.append("### ❤️ User Preferences (High Priority)")
                
                for p in preferences:
                    # 提取核心字段
                    pref_text = p.get("preference", "").strip()
                    reason = p.get("reasoning", "").strip()
                    p_type = p.get("preference_type", "implicit")
                    
                    # 格式化
                    # [Explicit] 用户喜欢辣... (Reason: ...)
                    line = f"- [{p_type.capitalize()}] {pref_text}"
                    if reason:
                        line += f"\n  (Context: {reason})"
                    output_lines.append(line)
                
                output_lines.append("") # 空行分隔

            # --- B. 处理事实记忆 (Fact Memories) ---
            if memories:
                output_lines.append("### 📝 Relevant Facts & Context")
                
                # 去重逻辑 (可选)：有时候向量检索会返回重复内容
                seen_values = set()
                
                for m in memories:
                    val = m.get("memory_value", "").strip()
                    
                    # 1. 过滤掉无意义的系统日志或 Raw Chat
                    # 你的数据里有一些 "user: [time]: ...", 这种最好清洗一下或者直接展示
                    # 如果 memory_key 是 "assistant:" 或 "user:" 开头，且内容很短，可能价值不高
                    if len(val) < 5 or val in seen_values:
                        continue
                    
                    seen_values.add(val)
                    
                    # 2. 提取元数据
                    m_type = m.get("memory_type", "General")
                    confidence = m.get("confidence", 0)
                    key = m.get("memory_key", "")
                    
                    # 3. 智能格式化
                    # 如果 Key 很有意义（不是自动生成的 user:xxx），就展示 Key
                    prefix = f"[{key}] " if key and not key.startswith(("user:", "assistant:")) else ""
                    
                    # 4. 时间处理 (如果有 create_time)
                    # create_time 是毫秒级时间戳 -> 转可读时间
                    ts = m.get("create_time")
                    time_str = ""
                    if ts:
                        try:
                            dt = datetime.fromtimestamp(ts / 1000)
                            time_str = f" ({dt.strftime('%Y-%m-%d')})"
                        except:
                            pass

                    output_lines.append(f"- {prefix}{val}{time_str}")

            # --- C. 最终组装 ---
            if not output_lines:
                return "No relevant memories found."
            
            # 添加头部提示，强化 LLM 的注意力
            final_output = "\n".join(output_lines)
            return f"[MemOS] retrieved the following context from long-term memory:\n\n{final_output}"

        self.tools = [search_memos]

    def before_agent(self, state, runtime):
        user_id = getattr(runtime.context, "user_id", "default_user")
        conversation_id = getattr(runtime.context, "thread_id", "default_conversation")
        self.memo_client.add_messages(
            user_id, conversation_id, self.messages_to_dicts(state["messages"][-1:])
        )

    def after_model(self, state, runtime):
        user_id = getattr(runtime.context, "user_id", "default_user")
        conversation_id = getattr(runtime.context, "thread_id", "default_conversation")
        self.memo_client.add_messages(
            user_id, conversation_id, self.messages_to_dicts(state["messages"][-1:])
        )

    def messages_to_dicts(self, messages: List[BaseMessage]):
        """将消息列表转换为 dict 列表"""
        convert_dict = {
            "human": "user",
            "ai": "assistant",
        }
        return [
            {
                "role": convert_dict.get(msg.type, "user"),
                "content": msg.content,
                "chat_time": msg.response_metadata.get(
                    "timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
            }
            for msg in messages
        ]

    def add_timestamp_to_state(self, state):
        if not state.get("messages"):
            return None
        messages_without_timestamp = self.rfind_messages_without_timestamp(
            state["messages"]
        )
        return {"messages": self.add_timestamp_to_messages(messages_without_timestamp)}

    def add_timestamp_to_messages(self, messages):
        for message in messages:
            if hasattr(message, "response_metadata"):
                # 创建新的 metadata 副本并添加时间戳
                if "timestamp" not in message.response_metadata:
                    updated_metadata = dict(message.response_metadata or {})
                    updated_metadata["timestamp"] = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    message.response_metadata = updated_metadata

        return messages

    def rfind_messages_without_timestamp(self, messages):
        messages_without_timestamp = []
        for message in reversed(messages):
            if "timestamp" not in message.response_metadata:
                messages_without_timestamp.append(message)
            else:
                break
        messages_without_timestamp = list(reversed(messages_without_timestamp))
        self.new_messages.extend(messages_without_timestamp)
        return messages_without_timestamp

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """Update the system message to include the todo system prompt."""
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(
            content=cast("list[str | dict[str, str]]", new_system_content)
        )
        return handler(request.override(system_message=new_system_message))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """Update the system message to include the todo system prompt (async version)."""
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(
            content=cast("list[str | dict[str, str]]", new_system_content)
        )
        return await handler(request.override(system_message=new_system_message))
