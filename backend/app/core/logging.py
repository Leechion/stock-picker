import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    logger.remove()
    if settings.debug:
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
                "| <level>{level: <7}</level> "
                "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
                "- <level>{message}</level>"
            ),
            level="DEBUG",
        )
    from pathlib import Path
    Path("logs").mkdir(parents=True, exist_ok=True)

    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
    )
