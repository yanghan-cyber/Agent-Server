"""
FastAPI中间件，用于自动设置日志上下文中的API路径和组合trace_id
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from utils.context import LogContext, set_log_context
from utils.logger import get_logger
import time
import uuid
import json

logger = get_logger(__name__)

class LoggingContextMiddleware(BaseHTTPMiddleware):
    """
    自动为每个请求设置日志上下文的中间件
    使用组合trace_id: thread_id-run_id
    """
    async def dispatch(self, request: Request, call_next):
        # 获取请求路径信息
        api_path = f"{request.method} {request.url.path}"
        
        # 从request.state中获取用户信息（由AuthMiddleware设置）
        user_id = getattr(request.state, 'user_id', None)
        user_type = getattr(request.state, 'user_type', 'anonymous')
        
        # 对于POST请求，尝试从请求体中提取thread_id和run_id
        combined_trace_id = None
        if request.method == "POST":
            try:
                # 读取请求体
                body = await request.body()
                if body:
                    request_data = json.loads(body.decode())
                    # 提取thread_id和run_id（支持驼峰和下划线格式）
                    thread_id = (request_data.get("threadId") or
                               request_data.get("thread_id") or
                               request_data.get("thread-id"))
                    run_id = (request_data.get("runId") or
                             request_data.get("run_id") or
                             request_data.get("run-id"))
                   
                    if thread_id and run_id:
                        # 使用组合ID作为trace_id
                        combined_trace_id = f"{thread_id}-{run_id}"
                        logger.info(f"使用客户端提供的组合trace_id: {combined_trace_id}")
                    elif thread_id:
                        # 如果只有thread_id，使用thread_id作为trace_id
                        combined_trace_id = thread_id
                        logger.info(f"使用客户端提供的thread_id作为trace_id: {combined_trace_id}")
                    else:
                        logger.debug("请求中未找到thread_id或run_id")
            except json.JSONDecodeError as e:
                logger.debug(f"无法解析请求体JSON: {e}")
            except Exception as e:
                logger.debug(f"提取trace_id时发生错误: {e}")
        
        # 如果无法从请求体获取，则生成一个临时的trace_id
        if not combined_trace_id:
            combined_trace_id = str(uuid.uuid4())
            logger.warning(f"无法从请求获取会话ID，生成临时trace_id: {combined_trace_id}")
        
        # 使用LogContext上下文管理器设置日志上下文
        # 使用从AuthMiddleware获取的user_id和user_type
        with LogContext(
            trace_id=combined_trace_id,
            api_path=api_path,
            user_name=user_id or "anonymous",
            user_type=user_type,
            env="prod"  # 可以根据环境变量设置
        ):
            # 记录请求开始
            start_time = time.time()
            logger.info(f"请求开始: {api_path}")
            
            # 处理请求
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 记录请求完成
            logger.info(
                f"请求完成: {api_path} - "
                f"状态码: {response.status_code} - "
                f"处理时间: {process_time:.3f}s"
            )
            
            # 将trace_id添加到响应头中，方便前端跟踪
            response.headers["X-Trace-ID"] = combined_trace_id
            
            return response


def setup_logging_middleware(app):
    """
    为FastAPI应用添加日志中间件的便捷函数
    """
    app.add_middleware(LoggingContextMiddleware)