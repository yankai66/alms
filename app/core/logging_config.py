"""
日志配置模块 - 支持Logstash集成

提供结构化日志输出，支持输出到控制台、文件和Logstash
"""

import logging
import sys
import os
from pathlib import Path
from pythonjsonlogger import jsonlogger
from datetime import datetime
import socket

# 从环境变量读取配置
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO")
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR.upper(), logging.INFO)
LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_DIR.mkdir(exist_ok=True)

# Logstash配置
LOGSTASH_HOST = os.getenv("LOGSTASH_HOST", "localhost")
LOGSTASH_PORT = int(os.getenv("LOGSTASH_PORT", "5000"))
ENABLE_LOGSTASH = os.getenv("ENABLE_LOGSTASH", "false").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """自定义JSON日志格式化器 - 符合业务日志标准"""
    
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        
        # 业务日志必需字段
        log_record['logType'] = 'business'  # 固定值
        log_record['businessType'] = 'alm'  # 固定值
        log_record['source'] = 'alm'  # 固定值
        
        # 操作时间 (ISO 8601格式)
        if not log_record.get('operationTime'):
            log_record['operationTime'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        # 从extra字段中提取业务信息（优先从log_record，因为extra字段会被复制到这里）
        log_record['operationObject'] = log_record.get('operationObject', message_dict.get('operationObject', ''))  # 操作对象
        log_record['operationType'] = log_record.get('operationType', message_dict.get('operationType', ''))  # 操作类型
        log_record['operator'] = log_record.get('operator', message_dict.get('operator', 'system'))  # 操作人
        log_record['result'] = log_record.get('result', message_dict.get('result', '成功'))  # 结果：成功/失败
        log_record['remark'] = log_record.get('remark', message_dict.get('remark', ''))  # 备注信息（可选）

        # 删除所有不需要的字段
        keys_to_remove = [
            'timestamp', 'level', 'name', 'message', 'event', 'request_id', 'method', 
            'path', 'query_params', 'client_ip', 'user_agent', 'status_code', 
            'process_time', 'error', 'error_type', 'application', 'environment', 
            'host', 'module', 'function', 'line', 'process_id', 'thread_id',
            'pathname', 'filename', 'lineno', 'funcName', 'created', 'msecs',
            'relativeCreated', 'thread', 'threadName', 'processName', 'process'
        ]
        for key in keys_to_remove:
            log_record.pop(key, None)


def setup_logging():
    """设置日志配置"""
    
    # 创建根日志记录器
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)
    
    # 清除已有的处理器
    logger.handlers.clear()
    
    # 1. 控制台处理器（带颜色的格式化输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 2. JSON文件处理器（结构化日志）
    json_file_handler = logging.FileHandler(
        LOG_DIR / f'app_{datetime.now().strftime("%Y%m%d")}.json.log',
        encoding='utf-8'
    )
    json_file_handler.setLevel(LOG_LEVEL)
    json_formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )
    json_file_handler.setFormatter(json_formatter)
    logger.addHandler(json_file_handler)
    
    # 3. 普通文件处理器（便于人工查看）
    text_file_handler = logging.FileHandler(
        LOG_DIR / f'app_{datetime.now().strftime("%Y%m%d")}.log',
        encoding='utf-8'
    )
    text_file_handler.setLevel(LOG_LEVEL)
    text_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    text_file_handler.setFormatter(text_formatter)
    logger.addHandler(text_file_handler)
    
    # 4. Logstash处理器（如果启用）
    if ENABLE_LOGSTASH:
        try:
            import logstash
            logstash_handler = logstash.TCPLogstashHandler(
                host=LOGSTASH_HOST,
                port=LOGSTASH_PORT,
                version=1
            )
            logstash_handler.setLevel(LOG_LEVEL)
            logger.addHandler(logstash_handler)
            logger.info(f"Logstash handler enabled: {LOGSTASH_HOST}:{LOGSTASH_PORT}")
        except ImportError:
            logger.warning("python-logstash not installed, Logstash handler disabled")
        except Exception as e:
            logger.error(f"Failed to setup Logstash handler: {e}")
    
    # 设置第三方库的日志级别（避免过多日志）
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    return logger


def get_logger(name: str = None):
    """获取日志记录器"""
    return logging.getLogger(name or __name__)


# 初始化日志
setup_logging()
