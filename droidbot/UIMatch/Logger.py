"""
日志模块，提供统一的日志记录功能
"""

import logging
import os
import sys
from datetime import datetime

class Logger:
    """
    日志记录器类，提供统一的日志记录接口
    """
    
    # 日志级别映射
    LEVELS = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL
    }
    
    def __init__(self, name='UIMatch', level='info', log_dir='logs'):
        """
        初始化日志记录器
        
        Args:
            name: 日志记录器名称
            level: 日志级别，可选值：debug, info, warning, error, critical
            log_dir: 日志文件保存目录
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(self.LEVELS.get(level.lower(), logging.INFO))
        self.logger.propagate = False
        
        # 如果已经有处理器，不再添加
        if self.logger.handlers:
            return
            
        # 创建日志目录
        os.makedirs(log_dir, exist_ok=True)

            
        # 日志文件名包含日期
        log_file = os.path.join(log_dir, f'{name}_{datetime.now().strftime("%Y%m%d")}.log')
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.logger.level)
        
        # 创建文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(self.logger.level)
        
        # 创建日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
        )
        
        # 设置格式
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        # 添加处理器
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
    
    def debug(self, message):
        """记录调试级别日志"""
        self.logger.debug(message)
    
    def info(self, message):
        """记录信息级别日志"""
        self.logger.info(message)
    
    def warning(self, message):
        """记录警告级别日志"""
        self.logger.warning(message)
    
    def error(self, message):
        """记录错误级别日志"""
        self.logger.error(message)
    
    def critical(self, message):
        """记录严重错误级别日志"""
        self.logger.critical(message)
    
    def exception(self, message):
        """记录异常信息，包含堆栈跟踪"""
        self.logger.exception(message)


# 创建默认日志记录器实例，可在其他模块中直接导入使用
logger = Logger()


def get_logger(name=None, level=None, log_dir=None, force_new_handlers=False):
    """
    获取日志记录器实例
    
    Args:
        name: 日志记录器名称，默认为'UIMatch'
        level: 日志级别，默认为'info'
        log_dir: 日志文件保存目录，默认为'logs'
        force_new_handlers: 是否强制创建新的处理器，即使日志记录器已存在
        
    Returns:
        Logger实例
    """
    logger_name = name or 'UIMatch'
    logger_level = level or 'info'
    logger_dir = log_dir or 'logs'
    
    # 如果需要强制创建新的处理器，先移除现有的处理器
    if force_new_handlers:
        existing_logger = logging.getLogger(logger_name)
        for handler in list(existing_logger.handlers):
            existing_logger.removeHandler(handler)
    
    return Logger(
        name=logger_name,
        level=logger_level,
        log_dir=logger_dir
    )