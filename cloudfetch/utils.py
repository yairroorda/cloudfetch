import logging
import time
from contextlib import contextmanager
from functools import wraps

import requests

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def timed(task_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.info(f"{task_name} took {elapsed:.3f}s")
            return result

        return wrapper

    return decorator


@contextmanager
def status_spinner(message: str):
    logger.info(message)
    yield
    logger.info("Done.")


def has_internet(timeout: int = 3) -> bool:
    """Check if an internet connection is available."""
    try:
        requests.get("http://clients3.google.com/generate_204", timeout=timeout)
        return True
    except requests.exceptions.RequestException:
        return False
