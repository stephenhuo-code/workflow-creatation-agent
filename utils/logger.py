"""
日志工具模块
提供统一的日志格式和工具函数
"""

import logging
import time
from functools import wraps

# 日志格式
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """
    创建模块专用 logger

    Args:
        name: 日志记录器名称
        level: 日志级别，默认 INFO

    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def log_llm_call(logger):
    """
    LLM 调用装饰器，记录耗时

    Args:
        logger: 用于记录日志的 logger 实例

    Returns:
        装饰器函数
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            logger.info(f"LLM 调用开始: {func.__name__}")
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"LLM 调用完成: {func.__name__} ({elapsed:.2f}s)")
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"LLM 调用失败: {func.__name__} ({elapsed:.2f}s) - {e}")
                raise
        return wrapper
    return decorator
