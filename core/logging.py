"""
NexusAgentes — Configuración centralizada de logging
"""
import logging
import sys


def setup_logging(name: str = "nexus") -> logging.Logger:
    """
    Configura y retorna un logger con formato consistente.
    """
    logger = logging.getLogger(name)

    # Evitar duplicación si ya se configuró
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger
