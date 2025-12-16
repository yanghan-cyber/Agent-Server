"""
认证中间件，用于验证API key并提取用户信息
"""

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.security import HTTPBearer
from typing import Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# 使用HTTP Bearer认证
security = HTTPBearer(auto_error=False)

class AuthMiddleware(BaseHTTPMiddleware):
    """
    认证中间件，验证API key并提取用户信息
    """
    
    async def dispatch(self, request: Request, call_next):
        # 尝试从请求头中获取API key
        user_id = None
        user_type = "anonymous"
        
        try:
            # 获取Authorization头
            authorization = request.headers.get("authorization")
            if authorization and authorization.startswith("Bearer "):
                # 提取API key（暂时不验证，直接使用默认值）
                # TODO: 实现真实的API key验证逻辑
                api_key = authorization[7:]  # 去掉"Bearer "前缀
                
                # 暂时返回默认user_id，后续可以实现真实的API key验证逻辑
                user_id = settings.DEFAULT_USER_ID
                user_type = "api_user"
                
                logger.debug(f"API key认证成功，user_id: {user_id}")
            else:
                # 没有提供API key，使用默认值
                user_id = settings.DEFAULT_USER_ID
                user_type = "anonymous"
                logger.debug("未提供API key，使用默认用户")
                
        except Exception as e:
            logger.error(f"认证过程中发生错误: {e}")
            # 认证失败，返回401错误
            return Response(
                content='{"error": "Authentication failed"}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="application/json"
            )
        
        # 将用户信息存储在request.state中，供后续中间件和endpoint使用
        request.state.user_id = user_id
        request.state.user_type = user_type
        
        # 继续处理请求
        response = await call_next(request)
        
        return response


def setup_auth_middleware(app):
    """
    为FastAPI应用添加认证中间件的便捷函数
    """
    app.add_middleware(AuthMiddleware)