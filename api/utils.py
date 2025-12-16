import json
import re
from enum import Enum
from typing import List, Any, Dict, NotRequired, Optional, TypedDict, Union
from dataclasses import is_dataclass, asdict
from datetime import date, datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage

from api.models.types import BinaryInputContent, TextInputContent, State

from api.models.types import Message as AGUIMessage

DEFAULT_SCHEMA_KEYS = ["tools"]

SchemaKeys = TypedDict("SchemaKeys", {
    "input": NotRequired[Optional[List[str]]],
    "output": NotRequired[Optional[List[str]]],
    "config": NotRequired[Optional[List[str]]],
    "context": NotRequired[Optional[List[str]]]
})

def convert_agui_multimodal_to_langchain(content: List[Union[TextInputContent, BinaryInputContent]]) -> List[Dict[str, Any]]:
    """Convert AG-UI multimodal content to LangChain's multimodal format."""
    langchain_content = []
    for item in content:
        if isinstance(item, TextInputContent):
            langchain_content.append({
                "type": "text",
                "text": item.text
            })
        elif isinstance(item, BinaryInputContent):
            # LangChain uses image_url format (OpenAI-style)
            content_dict = {"type": "image_url"}

            # Prioritize url, then data, then id
            if item.url:
                content_dict["image_url"] = {"url": item.url}
            elif item.data:
                # Construct data URL from base64 data
                content_dict["image_url"] = {"url": f"data:{item.mime_type};base64,{item.data}"}
            elif item.id:
                # Use id as a reference (some providers may support this)
                content_dict["image_url"] = {"url": item.id}

            langchain_content.append(content_dict)

    return langchain_content

def agui_messages_to_langchain(messages: List[AGUIMessage]) -> List[BaseMessage]:
    langchain_messages = []
    for message in messages:
        role = message.role
        if role == "user":
            # Handle multimodal content
            if isinstance(message.content, str):
                content = message.content
            elif isinstance(message.content, list):
                content = convert_agui_multimodal_to_langchain(message.content)
            else:
                content = str(message.content)

            langchain_messages.append(HumanMessage(
                id=message.id,
                content=content,
                name=message.name,
            ))
        elif role == "assistant":
            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments) if hasattr(tc, "function") and tc.function.arguments else {},
                        "type": "tool_call",
                    })
            langchain_messages.append(AIMessage(
                id=message.id,
                content=message.content or "",
                tool_calls=tool_calls,
                name=message.name,
            ))
        elif role == "system":
            langchain_messages.append(SystemMessage(
                id=message.id,
                content=message.content,
                name=message.name,
            ))
        elif role == "tool":
            langchain_messages.append(ToolMessage(
                id=message.id,
                content=message.content,
                tool_call_id=message.tool_call_id,
            ))
        else:
            raise ValueError(f"Unsupported message role: {role}")
    return langchain_messages


def get_stream_payload_input(
    *,
    mode: str,
    state: State,
    schema_keys: SchemaKeys,
) -> Union[State, None]:
    input_payload = state if mode == "start" else None
    if input_payload and schema_keys and schema_keys.get("input"):
        input_payload = filter_object_by_schema_keys(input_payload, [*DEFAULT_SCHEMA_KEYS, *schema_keys["input"]])
    return input_payload
def filter_object_by_schema_keys(obj: Dict[str, Any], schema_keys: List[str]) -> Dict[str, Any]:
    if not obj:
        return {}
    return {k: v for k, v in obj.items() if k in schema_keys}


def stringify_if_needed(item: Any) -> str:
    if item is None:
        return ''
    if isinstance(item, str):
        return item
    return json.dumps(item)

def camel_to_snake(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

def json_safe_stringify(o):
    if is_dataclass(o):          # dataclasses like Flight(...)
        return asdict(o)
    if hasattr(o, "model_dump"): # pydantic v2
        return o.model_dump()
    if hasattr(o, "dict"):       # pydantic v1
        return o.dict()
    if hasattr(o, "__dict__"):   # plain objects
        return vars(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)                # last resort

def is_json_primitive(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None

def make_json_safe(value: Any) -> Any:
    """
    Recursively convert a value into a JSON-serializable structure.

    - Handles Pydantic models via `model_dump`.
    - Handles LangChain messages via `to_dict`.
    - Recursively walks dicts, lists, and tuples.
    - For arbitrary objects, falls back to `__dict__` if available, else `repr()`.
    """
    # Pydantic models
    if hasattr(value, "model_dump"):
        try:
            return make_json_safe(value.model_dump(by_alias=True, exclude_none=True))
        except Exception:
            pass

    # LangChain-style objects
    if hasattr(value, "to_dict"):
        try:
            return make_json_safe(value.to_dict())
        except Exception:
            pass

    # Dict
    if isinstance(value, dict):
        return {key: make_json_safe(sub_value) for key, sub_value in value.items()}

    # List / tuple
    if isinstance(value, (list, tuple)):
        return [make_json_safe(sub_value) for sub_value in value]

    if isinstance(value, Enum):
        enum_value = value.value
        if is_json_primitive(enum_value):
            return enum_value
        return {
            "__type__": type(value).__name__,
            "name": value.name,
            "value": make_json_safe(enum_value),
        }

    # Already JSON safe
    if is_json_primitive(value):
        return value

    # Arbitrary object: try __dict__ first, fallback to repr
    if hasattr(value, "__dict__"):
        return {
            "__type__": type(value).__name__,
            **make_json_safe(value.__dict__),
        }

    return repr(value)
