import inspect
import json
import time
from typing import Any, Dict, List, Literal, Optional, Union
import uuid
from langgraph.types import Command

# 假设这些类已经从 events.py 导入
from api.models.events import (
    Event,
    RawEvent,
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    StepStartedEvent,
    StepFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageChunkEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallChunkEvent,
    ToolCallResultEvent,
    StateSnapshotEvent,
    StateDeltaEvent,
    MessagesSnapshotEvent,
)


# 用于类型检查辅助
from langchain_core.messages import  ToolMessage, SystemMessage, BaseMessage

from api.models.types import RunAgentInput, State
from api.utils import agui_messages_to_langchain, get_stream_payload_input, make_json_safe
from langgraph.graph.state import CompiledStateGraph
from langchain_core.runnables import RunnableConfig
from utils.logger import get_logger

logger = get_logger()
class LangGraphAgent:
    def __init__(self,name, graph: CompiledStateGraph,  description: Optional[str] = None, config:  Union[Optional[RunnableConfig], dict] = None):
        # 定义需要忽略的内部链名称，避免生成过多无意义的 Step 事件
        self.tool_calls = {}
        self.messages_id = set()
        self.graph = graph
        self.name = name
        self.description = description
        self.config = config  
        self.ignored_chains = []
        
        self.active_run = None
        self.constant_schema_keys = ['messages', 'tools']

        
    async def run(self, input_data: RunAgentInput):
        async for event in self._handle_stream_events(input_data):
            yield event
    
    def _dispatch_event(self, event: Event):
        """
        这里应该是将事件发送到前端、存入数据库或通过 SSE/WebSocket 发出的逻辑
        """
        if event.type == EventType.RAW:
            event.event = make_json_safe(event.event)
        elif event.raw_event:
            event.raw_event = make_json_safe(event.raw_event)

        return event

    def _extract_content(self, chunk: Any) -> str:
        """辅助方法：从 LangChain Chunk 中提取纯文本"""
        if hasattr(chunk, "content"):
            return str(chunk.content)
        elif isinstance(chunk, dict):
            return str(chunk.get("content", ""))
        elif isinstance(chunk, str):
            return chunk
        return ""

    async def _process_event(self, event: Dict[str, Any]):
        """
        处理 LangGraph v2 协议的事件，并转换为 Agent Protocol 事件
        使用 yield 生成事件，以便在 _handle_stream_events 中使用 async for 处理
        """
        event_type = event["event"]
        name = event["name"]
        data = event["data"]
        run_id = event["run_id"]
        # parent_ids 是 v2 协议的关键，用于判断层级
        parent_ids = event.get("parent_ids", [])
        metadata = event.get("metadata", {})
        # 获取当前时间戳
        ts = int(time.time() * 1000)

        match event_type:
            # --- 1. Chain/Graph 生命周期 ---
            case "on_chain_start":
                # 如果没有父级 ID，说明是整个 Graph (Run) 的开始
                logger.debug(f"STEP Start: [{name}]")
                if not parent_ids:
                    yield self._dispatch_event(
                        RunStartedEvent(
                            timestamp=ts,
                            run_id=run_id,
                            thread_id=metadata.get("thread_id"),
                            input=None
                        )
                    )
                # 否则，如果是具体的节点（Node）或 Chain，且不在忽略列表中
                elif name not in self.ignored_chains:
                    if self.active_run['node_name'] != name:
                        yield self._dispatch_event(
                            StepStartedEvent(
                                timestamp=ts,
                                step_name=name
                            )
                        )
                self.active_run['node_name'] = name
                

            case "on_chain_end":
                logger.debug(f"STEP END: [{name}]")
                output = data.get("output")
                # 根节点结束 -> RunFinished
                if not parent_ids:
                    # 获取最终输出结果
                    yield self._dispatch_event(
                        RunFinishedEvent(
                            timestamp=ts,
                            run_id=run_id,
                            thread_id=metadata.get("thread_id"),
                            result=str(output) if output else None
                        )
                    )
                # 子节点结束 -> StepFinished
                elif name not in self.ignored_chains:
                    yield self._dispatch_event(
                        StepFinishedEvent(
                            timestamp=ts,
                            step_name=name
                        )
                    )
                self.active_run['node_name'] = name
                if output is not None and isinstance(
                    output, dict
                ):
                    self.active_run['current_graph_state'].update(output)

            case "on_chain_error":
                # 如果是根节点报错
                if not parent_ids:
                    yield self._dispatch_event(
                        RunErrorEvent(
                            timestamp=ts,
                            message=str(data.get("error", "Unknown Error")),
                            code="500"
                        )
                    )

            # --- 2. Chat Model (LLM) 交互 ---
            case "on_chat_model_start":
                # LLM 开始思考/生成
                return
            
            case "on_chat_model_stream":
                # LLM 流式输出 (打字机效果)
                chunk = data.get("chunk")
                content = self._extract_content(chunk)
                tool_call_datas = event["data"]["chunk"].tool_call_chunks
                if tool_call_datas:
                    for tool_call_data in tool_call_datas:
                        self._add_tool_call_data(tool_call_data)
                
                if chunk.id not in self.messages_id:
                    self.messages_id.add(chunk.id)
                    yield self._dispatch_event(
                        TextMessageStartEvent(
                            timestamp=ts,
                            message_id=chunk.id,
                            raw_event=event,
                        )
                    )

                if content:
                    yield self._dispatch_event(
                        TextMessageContentEvent(
                            timestamp=ts,
                            message_id=chunk.id,
                            delta=content,
                            raw_event=event,
                        )
                    )

            case "on_chat_model_end":
                # LLM 生成结束
                yield self._dispatch_event(
                    TextMessageEndEvent(
                        timestamp=ts,
                        message_id=data['output'].id,
                        raw_event=event,

                    )
                )

            # --- 3. Tool (工具) 调用 ---
            case "on_tool_start":
                # 工具开始执行
                args = data.get("input", {})
                name = event.get("name")
                tool_call_data = self._get_tool_call_data(name, args)
                yield self._dispatch_event(
                    ToolCallStartEvent(
                        timestamp=ts,
                        tool_call_id=tool_call_data['id'],
                        tool_call_name=name,
                        parent_message_id=parent_ids[-1] if parent_ids else None,
                        raw_event=event,

                    )
                )
                
                # 如果需要发送参数细节，也可以在这里发送 ToolCallArgsEvent
                yield self._dispatch_event(
                    ToolCallArgsEvent(
                        timestamp=ts,
                        tool_call_id=tool_call_data['id'],
                        delta=json.dumps(args, ensure_ascii=False),
                        raw_event=event
                    )
                )

            case "on_tool_end":
                # 工具执行完毕，返回结果
                output = data.get("output")

                
                if isinstance(output, Command):
                    messages = output.update.get('messages', [])
                    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
                    for tool_msg in tool_messages:
                        yield self._dispatch_event(
                            ToolCallResultEvent(
                                timestamp=ts,
                                message_id=str(uuid.uuid4()),
                                tool_call_id=tool_msg.tool_call_id,
                                content=tool_msg.content,
                            )
                        )
                        yield self._dispatch_event(
                            ToolCallEndEvent(
                                timestamp=ts,
                                tool_call_id=tool_msg.tool_call_id,
                                raw_event=event,
                            )
                        )
                else:
                    # 序列化输出内容
                    args = data.get("input", {})
                    name = event.get("name")
                    tool_call_data = self._get_tool_call_data(name, args)
                    yield self._dispatch_event(
                        ToolCallResultEvent(
                            timestamp=ts,
                            message_id=str(uuid.uuid4()), # 通常结果绑定在调用 ID 上
                            tool_call_id=tool_call_data['id'],
                            content=output.content,
                        )
                    )
                    yield self._dispatch_event(
                        ToolCallEndEvent(
                            timestamp=ts,
                            tool_call_id=tool_call_data['id'],
                            raw_event=event,
                        )
                    )
                
            
            case _:
                # 其他事件，忽略
                yield RawEvent(timestamp=ts, event=event)
    
    def _add_tool_call_data(self, tool_call_data: Dict[str, Any]):
        tool_name = tool_call_data["name"]
        tool_args = tool_call_data.get("args", "{}")
        tool_args = json.dumps(json.loads(tool_args))
        self.tool_calls[f"{tool_name}-{tool_args}"] = tool_call_data
    def _get_tool_call_data(self, tool_name: str, tool_args: Dict[str, Any]):
        return self.tool_calls.get(f"{tool_name}-{json.dumps(tool_args)}", None)

    async def _handle_stream_events(self, input: RunAgentInput):
        thread_id = input.thread_id or str(uuid.uuid4())
        INITIAL_ACTIVE_RUN = {
            "id": input.run_id,
            "thread_id": thread_id,
            "thinking_process": None,
            "node_name": None,
            "has_function_streaming": False,
        }
        self.active_run = INITIAL_ACTIVE_RUN
        
        forwarded_props = input.forwarded_props

        node_name_input = forwarded_props.get('node_name', None) if forwarded_props else None
        config = self.config.copy() if self.config else {}
        config["configurable"] = {**(config.get('configurable', {})), "thread_id": thread_id}
        
        # 从forwarded_props中提取user_id并添加到config中
        if forwarded_props and "user_id" in forwarded_props:
            config["configurable"]["user_id"] = forwarded_props["user_id"]
            logger.info(f"Extracted user_id from forwarded_props: {forwarded_props['user_id']}")
        
        agent_state = await self.graph.aget_state(config)

        resume_input = forwarded_props.get('command', {}).get('resume', None)
        if resume_input is None and thread_id and self.active_run.get("node_name") != "__end__" and self.active_run.get("node_name"):
            self.active_run["mode"] = "continue"
        else:
            self.active_run["mode"] = "start"
        prepared_stream_response = await self.prepare_stream(input=input, agent_state=agent_state, config=config)

        state = prepared_stream_response["state"]
        stream = prepared_stream_response["stream"]
        config = prepared_stream_response["config"]
        
        async for event in stream:
            if event["event"] == "error":
                yield self._dispatch_event(
                    RunErrorEvent(type=EventType.RUN_ERROR, message=event["data"]["message"], raw_event=event)
                )
                break
            # 使用 async for 处理 _process_event 生成的事件
            async for processed_event in self._process_event(event):
                if processed_event is not None:
                    yield processed_event
    async def prepare_stream(self, input: RunAgentInput, agent_state: State, config: RunnableConfig):
        state_input = input.state or {}
        messages = input.messages or []
        forwarded_props = input.forwarded_props or {}
        thread_id = input.thread_id
        
        state_input["messages"] = agent_state.values.get("messages", [])

        self.active_run["current_graph_state"] = agent_state.values.copy()
        langchain_messages = agui_messages_to_langchain(messages)
        state = self.langgraph_default_merge_state(state_input, langchain_messages, input)
        self.active_run["current_graph_state"].update(state)
        config["configurable"]["thread_id"] = thread_id
        interrupts = agent_state.tasks[0].interrupts if agent_state.tasks and len(agent_state.tasks) > 0 else []
        has_active_interrupts = len(interrupts) > 0
        resume_input = forwarded_props.get('command', {}).get('resume', None)
        self.active_run["schema_keys"] = self.get_schema_keys(config)
        payload_input = get_stream_payload_input(
            mode=self.active_run["mode"],
            state=state,
            schema_keys=self.active_run["schema_keys"],
        )
        stream_input = {**forwarded_props, **payload_input} if payload_input else None
        subgraphs_stream_enabled = input.forwarded_props.get('stream_subgraphs') if input.forwarded_props else False

        kwargs = self.get_stream_kwargs(
            input=stream_input,
            config=config,
            subgraphs=bool(subgraphs_stream_enabled),
            version="v2",
        )

        stream = self.graph.astream_events(**kwargs)
        return {
            "stream": stream,
            "state": state,
            "config": config
        }

    def get_schema_keys(self, config):
        try:
            input_schema = self.graph.get_input_jsonschema(config)
            output_schema = self.graph.get_output_jsonschema(config)
            config_schema = self.graph.config_schema().schema()

            input_schema_keys = list(input_schema["properties"].keys()) if "properties" in input_schema else []
            output_schema_keys = list(output_schema["properties"].keys()) if "properties" in output_schema else []
            config_schema_keys = list(config_schema["properties"].keys()) if "properties" in config_schema else []
            context_schema_keys = []

            if hasattr(self.graph, "context_schema") and self.graph.context_schema is not None:
                context_schema = self.graph.context_schema().schema()
                context_schema_keys = list(context_schema["properties"].keys()) if "properties" in context_schema else []


            return {
                "input": [*input_schema_keys, *self.constant_schema_keys],
                "output": [*output_schema_keys, *self.constant_schema_keys],
                "config": config_schema_keys,
                "context": context_schema_keys,
            }
        except Exception:
            return {
                "input": self.constant_schema_keys,
                "output": self.constant_schema_keys,
                "config": [],
                "context": [],
            }
        
    def langgraph_default_merge_state(self, state: State, messages: List[BaseMessage], input: RunAgentInput) -> State:
        
        if messages and isinstance(messages[0], SystemMessage):
            messages = messages[1:]

        existing_messages = state.get("messages", [])
        existing_message_ids = {msg.id for msg in existing_messages}

        new_messages = [msg for msg in messages if msg.id not in existing_message_ids]

        tools = input.tools or []
        tools_as_dicts = []
        if tools:
            for tool in tools:
                if hasattr(tool, "model_dump"):
                    tools_as_dicts.append(tool.model_dump())
                elif hasattr(tool, "dict"):
                    tools_as_dicts.append(tool.dict())
                else:
                    tools_as_dicts.append(tool)

        all_tools = [*state.get("tools", []), *tools_as_dicts]

        # Remove duplicates based on tool name
        seen_names = set()
        unique_tools = []
        for tool in all_tools:
            tool_name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
            if tool_name and tool_name not in seen_names:
                seen_names.add(tool_name)
                unique_tools.append(tool)
            elif not tool_name:
                # Keep tools without names (shouldn't happen, but just in case)
                unique_tools.append(tool)
        
        return {
            **state,
            "messages": new_messages,
            "tools": unique_tools,
        }
    def get_stream_kwargs(
            self,
            input: Any,
            subgraphs: bool = False,
            version: Literal["v1", "v2"] = "v2",
            config: Optional[RunnableConfig] = None,
            context: Optional[Dict[str, Any]] = None,
            fork: Optional[Any] = None,
    ):
        kwargs = dict(
            input=input,
            subgraphs=subgraphs,
            version=version,
        )

        # Only add context if supported
        sig = inspect.signature(self.graph.astream_events)
        if 'context' in sig.parameters:
            base_context = {}
            if isinstance(config, dict) and 'configurable' in config and isinstance(config['configurable'], dict):
                base_context.update(config['configurable'])
            if context:  # context might be None or {}
                base_context.update(context)
            if base_context:  # only add if there's something to pass
                kwargs['context'] = base_context

        if config:
            kwargs['config'] = config

        if fork:
            kwargs.update(fork)

        return kwargs
