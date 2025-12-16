from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from api.models.types import RunAgentInput
from api.event_handler import LangGraphAgent

def add_langgraph_fastapi_endpoint(app: FastAPI, agent: LangGraphAgent, path: str = "/"):
    """Adds an endpoint to the FastAPI app."""

    @app.post(path)
    async def langgraph_agent_endpoint(input_data: RunAgentInput, request: Request):
        # Get the accept header from the request
        accept_header = request.headers.get("accept")
        
        # 从request.state中获取user_id（由AuthMiddleware设置）
        user_id = getattr(request.state, 'user_id', None)
        
        # 将user_id注入到forwarded_props中
        if input_data.forwarded_props is None:
            input_data.forwarded_props = {}
        
        if user_id:
            input_data.forwarded_props["user_id"] = user_id

        async def event_generator():
            async for event in agent.run(input_data):
                # 将事件对象转换为JSON格式
                if event is not None:
                    # 使用model_dump_json方法将事件序列化为JSON
                    event_json = event.model_dump_json(exclude_none=True)
                    # 按照Server-Sent Events格式发送数据
                    yield f"data: {event_json}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )

    @app.get(f"{path}/health")
    def health():
        """Health check."""
        return {
            "status": "ok",
            "agent": {
                "name": agent.name,
            }
        }