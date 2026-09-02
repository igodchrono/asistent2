# logger.py — логи в файл всегда DEBUG; в консоль — INFO или DEBUG (start_debug.bat)
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on", "debug")


def _console_level() -> int:
    """Уровень консоли: DEBUG если LISICHKA_DEBUG / DEBUG_CONSOLE / LOG_LEVEL=DEBUG."""
    if _env_truthy("LISICHKA_DEBUG") or _env_truthy("DEBUG_CONSOLE"):
        return logging.DEBUG
    lvl = (os.environ.get("LOG_LEVEL") or "").strip().upper()
    if not lvl:
        try:
            import config
            lvl = str(getattr(config, "LOG_LEVEL", "INFO") or "INFO").upper()
        except Exception:
            lvl = "INFO"
    return getattr(logging, lvl, logging.INFO)


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
        try:
            from path_manager import path_manager
            log_dir = path_manager.get_logs_dir()
        except Exception:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_filename = os.path.join(
            log_dir, f"assistant_{datetime.now().strftime('%Y%m%d')}.log"
        )

        self.logger = logging.getLogger("Lisichka")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        self.logger.propagate = False

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Короткий формат для консоли — удобнее читать «живьём»
        console_fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(message)s",
            datefmt="%H:%M:%S",
        )

        file_handler = RotatingFileHandler(
            log_filename,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(_console_level())
        console_handler.setFormatter(console_fmt)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        mode = "DEBUG (консоль подробно)" if console_handler.level <= logging.DEBUG else "INFO"
        self.logger.info("=" * 60)
        self.logger.info("🚀 Логирование: файл=DEBUG, консоль=%s", mode)
        self.logger.info("📁 Лог-файл: %s", log_filename)
        self.logger.info("=" * 60)

    def get_logger(self, name: str = None) -> logging.Logger:
        if name:
            return self.logger.getChild(name)
        return self.logger


logger = LoggerManager().get_logger()


def action(msg: str, *args) -> None:
    """Всегда видно в debug-консоли: ключевое действие ассистента."""
    try:
        logger.info("▶ " + str(msg), *args)
    except Exception:
        print("▶", msg, *args, flush=True)


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
