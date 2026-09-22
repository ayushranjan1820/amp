import logging
import sys
from typing import Optional

# Custom log template
CUSTOM_LOG_TEMPLATE = (
    "[%(asctime)s] | [%(levelname)-8s] | [%(name)s] | [%(filename)s:%(lineno)d] - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class CustomLogFormatter(logging.Formatter):
    """
    Custom formatter supporting ANSI color coding for terminal logs and custom log template formatting.
    """

    COLORS = {
        logging.DEBUG: "\033[36m",      # Cyan
        logging.INFO: "\033[32m",       # Green
        logging.WARNING: "\033[33m",    # Yellow
        logging.ERROR: "\033[31m",      # Red
        logging.CRITICAL: "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        use_colors: bool = True,
    ):
        super().__init__(fmt=fmt or CUSTOM_LOG_TEMPLATE, datefmt=datefmt or DATE_FORMAT)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        if self.use_colors and sys.stdout.isatty():
            color = self.COLORS.get(record.levelno, self.RESET)
            record.levelname = f"{color}{record.levelname}{self.RESET}"

        result = super().format(record)
        record.levelname = original_levelname
        return result


def setup_logger(
    name: str = "agent_mart",
    level: int = logging.INFO,
    template: Optional[str] = None,
) -> logging.Logger:
    """
    Configures and returns a logger instance formatted with the custom template.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = CustomLogFormatter(fmt=template or CUSTOM_LOG_TEMPLATE)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance for the specified module name.
    """
    return setup_logger(name=name)
