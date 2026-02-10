import logging
import sys
from typing import Optional
from logging.handlers import RotatingFileHandler

from halfmaid.config import get_config


class Logger:
    def __init__(self):
        self.config = get_config()
        self._setup_logging()

    def _setup_logging(self):
        self.logger = logging.getLogger("halfmaid")
        self.logger.setLevel(getattr(logging, self.config.log_level.upper()))
        self.logger.handlers.clear()

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        try:
            file_handler = RotatingFileHandler(
                "logs/halfmaid.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=3,
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception:
            pass

    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        if name:
            return logging.getLogger(f"halfmaid.{name}")
        return self.logger


_logger_instance = Logger()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return _logger_instance.get_logger(name)
