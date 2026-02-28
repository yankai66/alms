"""
日志记录工具函数
提供统一的业务日志记录接口
"""

from app.core.logging_config import get_logger
from app.constants.operation_types import OperationResult

logger = get_logger(__name__)


def log_operation(
    operation_type: str,
    serial_number: str,
    operator: str,
    result: str = OperationResult.SUCCESS,
    message: str = None
):
    """
    记录业务操作日志
    
    Args:
        operation_type: 操作类型（使用 OperationType 常量）
        serial_number: 资产序列号或标识
        operator: 操作人
        result: 操作结果（success/failed）
        message: 日志消息（可选）
    
    Example:
        from app.constants.operation_types import OperationType, OperationResult
        
        log_operation(
            OperationType.DEVICE_POWER_ON,
            "25672138172",
            "admin",
            OperationResult.SUCCESS
        )
    """
    log_message = message or f"Operation {result}"
    
    log_func = logger.info if result == OperationResult.SUCCESS else logger.error
    
    log_func(log_message, extra={
        "operationObject": serial_number,
        "operationType": operation_type,
        "operator": operator,
        "result": result
    })
