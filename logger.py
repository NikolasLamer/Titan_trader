# titan/logger.py
import logging
import sys

def setup_logging():
    """Configures structured logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03dZ [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout
    )
