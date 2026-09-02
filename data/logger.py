# logger.py
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from path_manager import path_manager


class LoggerManager:
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._setup_logging()
    
    def _setup_logging(self):
        # Используем PathManager
        log_dir = path_manager.get_logs_dir()
        os.makedirs(log_dir, exist_ok=True)
        
        log_filename = os.path.join(log_dir, f"assistant_{datetime.now().strftime('%Y%m%d')}.log")
        
        self.logger = logging.getLogger("Lisichka")
        self.logger.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler = RotatingFileHandler(
            log_filename,
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info("=" * 60)
        self.logger.info(f"🚀 Система логирования инициализирована")
        self.logger.info(f"📁 Лог-файл: {log_filename}")
        self.logger.info("=" * 60)
    
    def get_logger(self, name: str = None) -> logging.Logger:
        if name:
            return self.logger.getChild(name)
        return self.logger


logger = LoggerManager().get_logger()


def log_exception(logger_obj: logging.Logger, e: Exception, context: str = ""):
    logger_obj.error(f"{context} | {type(e).__name__}: {str(e)}", exc_info=True)


def log_warning(logger_obj: logging.Logger, message: str, context: str = ""):
    if context:
        logger_obj.warning(f"{context} | {message}")
    else:
        logger_obj.warning(message)


def log_info(logger_obj: logging.Logger, message: str, context: str = ""):
    if context:
        logger_obj.info(f"{context} | {message}")
    else:
        logger_obj.info(message)


def log_debug(logger_obj: logging.Logger, message: str, context: str = ""):
    if context:
        logger_obj.debug(f"{context} | {message}")
    else:
        logger_obj.debug(message)