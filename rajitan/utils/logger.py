import logging
import sys
from typing import Optional
from logging.handlers import RotatingFileHandler
from rajitan.utils.config import get_config


class Logger:
    """Centralized logging configuration"""
    
    def __init__(self):
        self.config = get_config()
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration"""
        # Create logger
        self.logger = logging.getLogger("rajitan")
        self.logger.setLevel(getattr(logging, self.config.log_level.upper()))
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # File handler (rotating)
        try:
            file_handler = RotatingFileHandler(
                'logs/rajitan.log',
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception as e:
            self.logger.warning(f"Could not create file handler: {e}")
    
    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        """Get a logger instance"""
        if name:
            return logging.getLogger(f"rajitan.{name}")
        return self.logger


# Global logger instance
_logger_instance = Logger()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance"""
    return _logger_instance.get_logger(name)