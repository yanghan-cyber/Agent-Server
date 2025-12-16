from agents.agent import agent
from api.event_handler import LangGraphAgent
from api.models.types import RunAgentInput
from api.models.events import (
    EventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallResultEvent,
    RunStartedEvent,
    RunFinishedEvent,
    StepStartedEvent,
    StepFinishedEvent
)
import json
import httpx
import asyncio

# 创建事件处理器实例
langgraph_agent = LangGraphAgent("test-agent", agent)

def format_event_for_display(event):
    """格式化事件以便更好地显示"""
    if event is None:
        return "None"
    
    event_type = event.type
    timestamp = event.timestamp
    
    # 根据事件类型提取关键信息
    if event_type == EventType.TEXT_MESSAGE_START:
        return f"[{timestamp}] 📝 文本消息开始: ID={event.message_id}, 角色={event.role}"
    
    elif event_type == EventType.TEXT_MESSAGE_CONTENT:
        # 特别处理文本内容，确保显示完整
        content = event.delta
        return f"[{timestamp}] 💬 文本内容: ID={event.message_id}, 内容='{content}'"
    
    elif event_type == EventType.TEXT_MESSAGE_END:
        return f"[{timestamp}] ✅ 文本消息结束: ID={event.message_id}"
    
    elif event_type == EventType.TOOL_CALL_START:
        return f"[{timestamp}] 🔧 工具调用开始: ID={event.tool_call_id}, 工具={event.tool_call_name}"
    
    elif event_type == EventType.TOOL_CALL_RESULT:
        # 特别处理工具结果，确保显示完整
        content = event.content
        return f"[{timestamp}] ✅ 工具调用结果: ID={event.tool_call_id}, 内容='{content}'"
    
    elif event_type == EventType.RUN_STARTED:
        return f"[{timestamp}] 🚀 运行开始: ID={event.run_id}, 线程ID={event.thread_id}"
    
    elif event_type == EventType.RUN_FINISHED:
        return f"[{timestamp}] 🏁 运行结束: ID={event.run_id}, 结果={event.result}"
    
    elif event_type == EventType.STEP_STARTED:
        return f"[{timestamp}] ➡️ 步骤开始: {event.step_name}"
    
    elif event_type == EventType.STEP_FINISHED:
        return f"[{timestamp}] ✅ 步骤结束: {event.step_name}"
    
    else:
        # 对于其他事件类型，显示完整信息
        # return f"[{timestamp}] 📋 事件类型: {event_type}, 数据: {event.model_dump_json(exclude_none=True, indent=2)}"
        return 
async def test_direct_event_handler(query):
    """直接测试事件处理器"""
    print("=" * 60)
    print("直接测试事件处理器")
    print("=" * 60)
    
    input_data = RunAgentInput(
        messages=[
            {"role": "user", "content": query, "id": "m_123"}
        ],
        run_id="run_id_123",
        thread_id="thread_id_123",
        parent_run_id="parent_123",
        tools=[],
        context=[],
        state={},
        forwarded_props={}
    )
    
    print(f"用户查询: {query}")
    print("\n事件流:")
    print("-" * 40)
    
    full_text_content = ""
    
    async for event in langgraph_agent.run(input_data):
        if event.type != EventType.TEXT_MESSAGE_CONTENT:
            formatted_event = format_event_for_display(event)
            if formatted_event:
                print(formatted_event)
        
        # 收集文本内容
        if event.type == EventType.TEXT_MESSAGE_CONTENT:
            print(event.delta, end="", flush=True)
    
    return 


async def test_http_api(query):
    """通过HTTP API测试"""
    print("\n" + "=" * 60)
    print("通过HTTP API测试")
    print("=" * 60)
    
    # 启动服务器（在实际使用中，服务器应该已经在运行）
    # 这里我们假设服务器已经在 http://localhost:8000 运行
    
    url = "http://localhost:8000/"
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }
    
    data = {
        "messages": [
            {"role": "user", "content": query, "id": "m_123"}
        ],
        "run_id": "run_id_123",
        "thread_id": "thread_id_123",
        "parent_run_id": "parent_123",
        "tools": [],
        "context": [],
        "state": {},
        "forwarded_props": {}
    }
    
    print(f"发送请求到: {url}")
    print(f"查询: {query}")
    print("\n事件流:")
    print("-" * 40)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=data, headers=headers) as response:
                if response.status_code == 200:
                    full_text_content = ""
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                event_data = json.loads(line[6:])  # 去掉 "data: " 前缀
                                # 根据事件类型创建一个简单的事件对象用于显示
                                event_type = event_data.get("type", "UNKNOWN")
                                timestamp = event_data.get("timestamp", 0)
                                
                                # 创建一个简单的事件对象用于显示
                                class SimpleEvent:
                                    def __init__(self, data):
                                        self.type = data.get("type", "UNKNOWN")
                                        self.timestamp = data.get("timestamp", 0)
                                        self.data = data
                                    
                                    def __getattr__(self, name):
                                        return self.data.get(name)
                                
                                simple_event = SimpleEvent(event_data)
                                formatted_event = format_event_for_display(simple_event)
                                print(formatted_event)
                                
                                # 收集文本内容
                                if event_type == "TEXT_MESSAGE_CONTENT" and "delta" in event_data:
                                    full_text_content += event_data["delta"]
                                    
                            except json.JSONDecodeError:
                                print(f"无法解析的事件数据: {line}")
                else:
                    print(f"请求失败，状态码: {response.status_code}")
                    print(f"响应内容: {await response.aread()}")
    except httpx.ConnectError:
        print("无法连接到服务器。请确保服务器在 http://localhost:8000 运行。")
    except Exception as e:
        print(f"发生错误: {str(e)}")

async def main():
    query = "查看一下多久过春节"
    
    # 测试1: 直接测试事件处理器
    await test_direct_event_handler(query)
    
    # 测试2: 通过HTTP API测试（需要服务器运行）
    # await test_http_api(query)

if __name__ == "__main__":
    asyncio.run(main())
    
