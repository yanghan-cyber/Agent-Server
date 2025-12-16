"""
示例：如何在FastAPI应用中设置中间件的顺序
"""

from fastapi import FastAPI
from api.middleware.auth_middleware import setup_auth_middleware
from api.middleware.logging_middleware import setup_logging_middleware
from api.endpoint import add_langgraph_fastapi_endpoint
from api.event_handler import LangGraphAgent
from agents.agent import agent

def create_app():
    """创建并配置FastAPI应用"""
    app = FastAPI(title="LangGraph Agents API")
    
    # 重要：中间件的添加顺序很重要！
    # 1. 首先添加认证中间件，它会验证API key并设置用户信息
    setup_auth_middleware(app)
    
    # 2. 然后添加日志中间件，它会使用认证中间件设置的用户信息
    setup_logging_middleware(app)
    
    # 3. 最后添加API端点
    langgraph_agent = LangGraphAgent(name="langgraph-agent", graph=agent)
    add_langgraph_fastapi_endpoint(app, langgraph_agent)
    
    return app

if __name__ == "__main__":
    import uvicorn
    
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)