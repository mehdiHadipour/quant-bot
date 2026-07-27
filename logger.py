"""
Small logging helper used across the whole project instead of raw print().

Kept intentionally simple (no external dependency, no config files): a
single StreamHandler to stdout with a timestamp + level prefix, so GitHub
Actions logs stay just as readable as before but are now structured and
filterable by level (INFO / WARNING / ERROR).
"""

import logging
import sys


def get_logger(name="quant_bot"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


log = get_logger()
