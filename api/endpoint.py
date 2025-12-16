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
        # Create an event encoder to properly format SSE events

        async def event_generator():
            async for event in agent.run(input_data):
                yield event

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream"
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