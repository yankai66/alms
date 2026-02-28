"""
日志中间件

记录所有HTTP请求和响应，包括：
- 请求方法、路径、参数
- 响应状态码、处理时间
- 用户信息、IP地址
- 错误和异常信息
"""

import time
import json
import re
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """HTTP请求/响应日志中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求并记录日志"""
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 获取请求信息
        request_id = request.headers.get("X-Request-ID", "")
        client_host = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else ""
        
        # 处理请求
        try:
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 添加响应头
            response.headers["X-Process-Time"] = f"{process_time:.3f}"
            if request_id:
                response.headers["X-Request-ID"] = request_id

            # 记录访问日志
            logger.info(
                "HTTP %s %s -> %s (%.3fs)",
                method,
                path,
                response.status_code,
                process_time,
                extra={
                    "client_ip": client_host,
                    "query": query_params,
                    "request_id": request_id,
                }
            )
            
            return response
            
        except Exception as e:
            logger.exception(
                "HTTP %s %s failed: %s",
                method,
                path,
                str(e),
                extra={
                    "client_ip": client_host,
                    "query": query_params,
                    "request_id": request_id,
                }
            )
            # 重新抛出异常，让FastAPI的异常处理器处理
            raise


class RequestLoggerContextMiddleware(BaseHTTPMiddleware):
    """请求上下文日志中间件 - 为每个请求添加上下文信息"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """在请求上下文中添加日志信息"""
        
        # 可以在这里添加请求级别的上下文信息
        # 例如：用户ID、租户ID等
        request.state.request_id = request.headers.get("X-Request-ID", "")
        
        response = await call_next(request)
        return response
