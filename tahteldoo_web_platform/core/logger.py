import logging
import sys
from pathlib import Path
from core.config import Config

class Logger:
    _logger = None

    @classmethod
    def get_logger(cls):
        if cls._logger is None:
            cls._logger = logging.getLogger("TahtElDooPublisher")
            cls._logger.setLevel(logging.DEBUG)

            # Formatter
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )

            # Console Handler with UTF-8 encoding support
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            cls._logger.addHandler(console_handler)

            # File Handler
            log_file = Config.LOGS_DIR / "app.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            cls._logger.addHandler(file_handler)

        return cls._logger

logger = Logger.get_logger()
